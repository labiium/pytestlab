from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from .results import BodeResult
from .results import FrequencySpectrum
from .results import ImpedanceResult

if TYPE_CHECKING:
    from .spice import SpiceResult


def phasor_extract(time_s: np.ndarray, voltage: np.ndarray, freq_hz: float) -> complex:
    time = np.asarray(time_s, dtype=float)
    volts = np.asarray(voltage, dtype=float)
    if time.shape != volts.shape:
        raise ValueError("time_s and voltage must have the same shape")
    if time.size == 0:
        return 0.0 + 0.0j
    basis = np.exp(-1j * 2.0 * np.pi * float(freq_hz) * time)
    return complex(2.0 * np.mean(volts * basis))


def bode_from_ac_result(result: SpiceResult, input_node: str, output_node: str) -> BodeResult:
    vin = np.asarray(result.node_voltages[input_node])
    vout = np.asarray(result.node_voltages[output_node])
    h = np.divide(vout, vin, out=np.zeros_like(vout, dtype=complex), where=np.abs(vin) > 0)
    magnitude = np.abs(h)
    mag_db = np.full(magnitude.shape, -np.inf, dtype=float)
    np.log10(magnitude, out=mag_db, where=magnitude > 0)
    mag_db *= 20.0
    phase_deg = np.degrees(np.unwrap(np.angle(h)))
    return BodeResult(
        freq_hz=np.asarray(result.scale, dtype=float),
        magnitude_db=mag_db,
        phase_deg=phase_deg,
        metadata=dict(getattr(result, "metadata", {})),
    )


def impedance_deembed(
    freq_hz: np.ndarray,
    h_complex: np.ndarray,
    r_sense_ohm: float,
) -> ImpedanceResult:
    h = np.asarray(h_complex, dtype=complex)
    z = float(r_sense_ohm) * h / (1.0 - h)
    return ImpedanceResult(
        freq_hz=np.asarray(freq_hz, dtype=float),
        z_magnitude=np.abs(z),
        z_phase_deg=np.degrees(np.angle(z)),
    )


def rise_time_10_90(
    time_s: np.ndarray,
    voltage: np.ndarray,
    *,
    low: float = 0.1,
    high: float = 0.9,
) -> float | None:
    time = np.asarray(time_s, dtype=float)
    volts = np.asarray(voltage, dtype=float)
    if time.shape != volts.shape or time.size < 2:
        return None
    initial = float(volts[0])
    final = _final_value(volts)
    span = final - initial
    if np.isclose(span, 0.0):
        return None
    low_v = initial + float(low) * span
    high_v = initial + float(high) * span
    t_low = _first_crossing_time(time, volts, low_v, rising=span > 0)
    t_high = _first_crossing_time(time, volts, high_v, rising=span > 0)
    if t_low is None or t_high is None or t_high < t_low:
        return None
    return float(t_high - t_low)


def settling_time(
    time_s: np.ndarray,
    voltage: np.ndarray,
    *,
    threshold: float = 0.02,
    final: float | None = None,
) -> float | None:
    time = np.asarray(time_s, dtype=float)
    volts = np.asarray(voltage, dtype=float)
    if time.shape != volts.shape or time.size == 0:
        return None
    final_value = _final_value(volts) if final is None else float(final)
    band = abs(final_value) * float(threshold)
    if band == 0.0:
        band = float(threshold)
    within = np.abs(volts - final_value) <= band
    for idx in range(within.size):
        if bool(np.all(within[idx:])):
            return float(time[idx])
    return None


def overshoot_pct(time_s: np.ndarray, voltage: np.ndarray) -> float:
    _ = time_s
    volts = np.asarray(voltage, dtype=float)
    if volts.size == 0:
        return 0.0
    final = _final_value(volts)
    initial = float(volts[0])
    span = final - initial
    if np.isclose(span, 0.0):
        return 0.0
    if span > 0:
        overshoot = float(np.max(volts) - final)
    else:
        overshoot = float(final - np.min(volts))
    return max(0.0, overshoot / max(abs(final), abs(span), 1e-30) * 100.0)


def compute_spectrum(
    time_s: np.ndarray,
    voltage: np.ndarray,
    *,
    window: str = "hann",
) -> FrequencySpectrum:
    time = np.asarray(time_s, dtype=float)
    volts = np.asarray(voltage, dtype=float)
    if time.shape != volts.shape:
        raise ValueError("time_s and voltage must have the same shape")
    if time.size == 0:
        return FrequencySpectrum(np.asarray([]), np.asarray([]), np.asarray([]))
    dt = _sample_interval(time)
    sample_rate = 1.0 / dt
    win = _window(window, volts.size)
    coherent_gain = float(np.sum(win) / volts.size) if volts.size else 1.0
    coherent_gain = coherent_gain if coherent_gain > 0 else 1.0
    centered = volts - float(np.mean(volts))
    spectrum = np.fft.rfft(centered * win)
    magnitude = np.abs(spectrum) * 2.0 / (volts.size * coherent_gain)
    if magnitude.size:
        magnitude[0] /= 2.0
        if volts.size % 2 == 0:
            magnitude[-1] /= 2.0
    phase = np.angle(spectrum)
    freq = np.fft.rfftfreq(volts.size, d=dt)
    fundamental = _dominant_frequency(freq, magnitude)
    return FrequencySpectrum(
        freq_hz=freq,
        magnitude=magnitude,
        phase=phase,
        fundamental_hz=fundamental if fundamental > 0 else None,
        metadata={"sample_rate": sample_rate, "window": window},
    )


def thd_n_from_spectrum(
    spectrum: FrequencySpectrum,
    n_harmonics: int = 7,
) -> dict[str, float]:
    freq = spectrum.freq_hz
    mag = spectrum.magnitude
    if freq.size <= 1 or mag.size <= 1:
        return {"thd": 0.0, "thd_n": 0.0, "sinad": math.inf, "sfdr_db": math.inf}

    fundamental = spectrum.fundamental_hz or _dominant_frequency(freq, mag)
    if fundamental <= 0:
        return {"thd": 0.0, "thd_n": 0.0, "sinad": math.inf, "sfdr_db": math.inf}
    fund_idx = int(np.argmin(np.abs(freq - fundamental)))
    fund = float(mag[fund_idx])
    if fund <= 0:
        return {"thd": 0.0, "thd_n": 0.0, "sinad": math.inf, "sfdr_db": math.inf}

    harmonic_indices: list[int] = []
    for harmonic in range(2, int(n_harmonics) + 1):
        target = fundamental * harmonic
        if target > freq[-1]:
            continue
        harmonic_indices.append(int(np.argmin(np.abs(freq - target))))

    harmonic_power = float(np.sum(mag[harmonic_indices] ** 2)) if harmonic_indices else 0.0
    excluded = {0, fund_idx, *harmonic_indices}
    residual_indices = [idx for idx in range(mag.size) if idx not in excluded]
    noise_dist_power = harmonic_power + float(np.sum(mag[residual_indices] ** 2))
    thd = math.sqrt(harmonic_power) / fund if harmonic_power > 0 else 0.0
    thd_n = math.sqrt(noise_dist_power) / fund if noise_dist_power > 0 else 0.0
    sinad = (
        20.0 * math.log10(fund / math.sqrt(noise_dist_power)) if noise_dist_power > 0 else math.inf
    )

    spur = 0.0
    for idx, value in enumerate(mag):
        if idx in {0, fund_idx}:
            continue
        spur = max(spur, float(value))
    sfdr = 20.0 * math.log10(fund / spur) if spur > 0 else math.inf
    return {"thd": thd, "thd_n": thd_n, "sinad": sinad, "sfdr_db": sfdr}


def _sample_interval(time_s: np.ndarray) -> float:
    if time_s.size < 2:
        return 1.0
    diffs = np.diff(time_s)
    dt = float(np.median(diffs))
    if dt <= 0:
        raise ValueError("time_s must be monotonic increasing")
    return dt


def _window(name: str, size: int) -> np.ndarray:
    normalized = name.lower()
    if normalized in {"hann", "hanning"}:
        return np.hanning(size)
    if normalized == "blackman":
        return np.blackman(size)
    if normalized in {"rect", "rectangular", "none"}:
        return np.ones(size)
    raise ValueError(f"unsupported FFT window: {name}")


def _final_value(voltage: np.ndarray) -> float:
    if voltage.size < 5:
        return float(voltage[-1])
    tail = voltage[-max(5, voltage.size // 10) :]
    return float(np.mean(tail))


def _first_crossing_time(
    time_s: np.ndarray,
    voltage: np.ndarray,
    level: float,
    *,
    rising: bool,
) -> float | None:
    if rising:
        candidates = np.where((voltage[:-1] <= level) & (voltage[1:] >= level))[0]
    else:
        candidates = np.where((voltage[:-1] >= level) & (voltage[1:] <= level))[0]
    if candidates.size == 0:
        return None
    idx = int(candidates[0])
    v0 = float(voltage[idx])
    v1 = float(voltage[idx + 1])
    if np.isclose(v0, v1):
        return float(time_s[idx])
    ratio = (level - v0) / (v1 - v0)
    return float(time_s[idx] + ratio * (time_s[idx + 1] - time_s[idx]))


def _dominant_frequency(freq_hz: np.ndarray, magnitude: np.ndarray) -> float:
    start = 1 if freq_hz.size and np.isclose(freq_hz[0], 0.0) else 0
    if start >= magnitude.size:
        return 0.0
    return float(freq_hz[start + int(np.argmax(magnitude[start:]))])
