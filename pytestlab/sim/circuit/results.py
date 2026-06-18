from __future__ import annotations

import warnings
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import numpy as np

_PLOT_WARNING_EMITTED = False


def _polars():
    try:
        import polars as pl
    except ImportError as exc:  # pragma: no cover - depends on optional environment
        raise ImportError(
            "Polars is required for result.to_dataframe(). Install polars>=1.0."
        ) from exc
    return pl


def _matplotlib_pyplot():
    global _PLOT_WARNING_EMITTED
    try:
        import matplotlib.pyplot as plt
    except ImportError:  # pragma: no cover - optional plotting extra
        if not _PLOT_WARNING_EMITTED:
            warnings.warn(
                "matplotlib is not installed; plot() is a no-op.",
                RuntimeWarning,
                stacklevel=2,
            )
            _PLOT_WARNING_EMITTED = True
        return None
    return plt


@dataclass(frozen=True)
class WaveformResult:
    time_s: np.ndarray
    voltage: np.ndarray
    sample_rate: float
    instrument: str
    units: str = "V"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        time_s = np.asarray(self.time_s, dtype=float)
        voltage = np.asarray(self.voltage, dtype=float)
        if time_s.shape != voltage.shape:
            raise ValueError("time_s and voltage must have the same shape")
        if time_s.ndim != 1:
            raise ValueError("WaveformResult arrays must be one-dimensional")
        object.__setattr__(self, "time_s", time_s)
        object.__setattr__(self, "voltage", voltage)
        object.__setattr__(self, "sample_rate", float(self.sample_rate))

    def peak_to_peak(self) -> float:
        return float(np.max(self.voltage) - np.min(self.voltage)) if self.voltage.size else 0.0

    def rms(self) -> float:
        return float(np.sqrt(np.mean(self.voltage**2))) if self.voltage.size else 0.0

    def dc_mean(self) -> float:
        return float(np.mean(self.voltage)) if self.voltage.size else 0.0

    def ac_rms(self) -> float:
        if not self.voltage.size:
            return 0.0
        ac = self.voltage - np.mean(self.voltage)
        return float(np.sqrt(np.mean(ac**2)))

    def rise_time(self, low: float = 0.1, high: float = 0.9) -> float | None:
        from .analysis import rise_time_10_90

        return rise_time_10_90(self.time_s, self.voltage, low=low, high=high)

    def settling_time(self, threshold: float = 0.02) -> float | None:
        from .analysis import settling_time

        return settling_time(self.time_s, self.voltage, threshold=threshold)

    def overshoot_pct(self) -> float:
        from .analysis import overshoot_pct

        return overshoot_pct(self.time_s, self.voltage)

    def fft(self, window: str = "hann") -> FrequencySpectrum:
        from .analysis import compute_spectrum

        return compute_spectrum(self.time_s, self.voltage, window=window)

    def to_dataframe(self):
        pl = _polars()
        return pl.DataFrame({"Time (s)": self.time_s, f"Voltage ({self.units})": self.voltage})

    def plot(self, **kwargs) -> None:
        plt = _matplotlib_pyplot()
        if plt is None:
            return None
        plt.plot(self.time_s, self.voltage, **kwargs)
        plt.xlabel("Time (s)")
        plt.ylabel(f"Voltage ({self.units})")
        return None

    def __getitem__(self, idx):
        return self.time_s[idx], self.voltage[idx]


@dataclass(frozen=True)
class BodeResult:
    freq_hz: np.ndarray
    magnitude_db: np.ndarray
    phase_deg: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        freq = np.asarray(self.freq_hz, dtype=float)
        mag = np.asarray(self.magnitude_db, dtype=float)
        phase = np.asarray(self.phase_deg, dtype=float)
        if freq.shape != mag.shape or freq.shape != phase.shape:
            raise ValueError("BodeResult arrays must have the same shape")
        object.__setattr__(self, "freq_hz", freq)
        object.__setattr__(self, "magnitude_db", mag)
        object.__setattr__(self, "phase_deg", phase)

    def bandwidth_3db(self) -> float | None:
        if self.freq_hz.size == 0:
            return None
        target = float(self.magnitude_db[0]) - 3.0
        crossings = np.where(self.magnitude_db <= target)[0]
        return None if crossings.size == 0 else float(self.freq_hz[int(crossings[0])])

    def gain_at(self, freq_hz: float) -> float:
        return float(np.interp(float(freq_hz), self.freq_hz, self.magnitude_db))

    def phase_at(self, freq_hz: float) -> float:
        return float(np.interp(float(freq_hz), self.freq_hz, self.phase_deg))

    def plot(self, **kwargs) -> None:
        plt = _matplotlib_pyplot()
        if plt is None:
            return None
        fig, (ax_mag, ax_phase) = plt.subplots(2, 1, sharex=True)
        ax_mag.semilogx(self.freq_hz, self.magnitude_db, **kwargs)
        ax_phase.semilogx(self.freq_hz, self.phase_deg, **kwargs)
        ax_mag.set_ylabel("Magnitude (dB)")
        ax_phase.set_ylabel("Phase (deg)")
        ax_phase.set_xlabel("Frequency (Hz)")
        fig.tight_layout()
        return None

    def to_dataframe(self):
        pl = _polars()
        return pl.DataFrame(
            {
                "freq_hz": self.freq_hz,
                "magnitude_db": self.magnitude_db,
                "phase_deg": self.phase_deg,
            }
        )


@dataclass(frozen=True)
class FrequencySpectrum:
    freq_hz: np.ndarray
    magnitude: np.ndarray
    phase: np.ndarray
    fundamental_hz: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        freq = np.asarray(self.freq_hz, dtype=float)
        mag = np.asarray(self.magnitude, dtype=float)
        phase = np.asarray(self.phase, dtype=float)
        if freq.shape != mag.shape or freq.shape != phase.shape:
            raise ValueError("FrequencySpectrum arrays must have the same shape")
        object.__setattr__(self, "freq_hz", freq)
        object.__setattr__(self, "magnitude", mag)
        object.__setattr__(self, "phase", phase)

    def thd(self, n_harmonics: int = 7) -> float:
        from .analysis import thd_n_from_spectrum

        return thd_n_from_spectrum(self, n_harmonics=n_harmonics)["thd"]

    def thd_n(self, n_harmonics: int = 7) -> float:
        from .analysis import thd_n_from_spectrum

        return thd_n_from_spectrum(self, n_harmonics=n_harmonics)["thd_n"]

    def sinad(self, n_harmonics: int = 7) -> float:
        from .analysis import thd_n_from_spectrum

        return thd_n_from_spectrum(self, n_harmonics=n_harmonics)["sinad"]

    def sfdr_db(self) -> float:
        from .analysis import thd_n_from_spectrum

        return thd_n_from_spectrum(self)["sfdr_db"]

    def harmonic_magnitudes(self, n: int) -> np.ndarray:
        if n <= 0:
            return np.asarray([], dtype=float)
        fundamental = self.fundamental_hz or _dominant_frequency(self.freq_hz, self.magnitude)
        harmonics = []
        for harmonic in range(1, n + 1):
            target = fundamental * harmonic
            if self.freq_hz.size == 0 or target > self.freq_hz[-1]:
                harmonics.append(0.0)
                continue
            idx = int(np.argmin(np.abs(self.freq_hz - target)))
            harmonics.append(float(self.magnitude[idx]))
        return np.asarray(harmonics, dtype=float)

    def plot(self, **kwargs) -> None:
        plt = _matplotlib_pyplot()
        if plt is None:
            return None
        plt.plot(self.freq_hz, self.magnitude, **kwargs)
        plt.xlabel("Frequency (Hz)")
        plt.ylabel("Magnitude")
        return None

    def to_dataframe(self):
        pl = _polars()
        return pl.DataFrame(
            {"freq_hz": self.freq_hz, "magnitude": self.magnitude, "phase": self.phase}
        )


@dataclass(frozen=True)
class ImpedanceResult:
    freq_hz: np.ndarray
    z_magnitude: np.ndarray
    z_phase_deg: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        freq = np.asarray(self.freq_hz, dtype=float)
        mag = np.asarray(self.z_magnitude, dtype=float)
        phase = np.asarray(self.z_phase_deg, dtype=float)
        if freq.shape != mag.shape or freq.shape != phase.shape:
            raise ValueError("ImpedanceResult arrays must have the same shape")
        object.__setattr__(self, "freq_hz", freq)
        object.__setattr__(self, "z_magnitude", mag)
        object.__setattr__(self, "z_phase_deg", phase)

    def resonant_frequency(self) -> float | None:
        if self.freq_hz.size == 0:
            return None
        return float(self.freq_hz[int(np.argmin(self.z_magnitude))])

    def plot(self, **kwargs) -> None:
        plt = _matplotlib_pyplot()
        if plt is None:
            return None
        fig, (ax_mag, ax_phase) = plt.subplots(2, 1, sharex=True)
        ax_mag.semilogx(self.freq_hz, self.z_magnitude, **kwargs)
        ax_phase.semilogx(self.freq_hz, self.z_phase_deg, **kwargs)
        ax_mag.set_ylabel("|Z| (ohm)")
        ax_phase.set_ylabel("Phase (deg)")
        ax_phase.set_xlabel("Frequency (Hz)")
        fig.tight_layout()
        return None

    def to_dataframe(self):
        pl = _polars()
        return pl.DataFrame(
            {
                "freq_hz": self.freq_hz,
                "z_magnitude": self.z_magnitude,
                "z_phase_deg": self.z_phase_deg,
            }
        )


@dataclass(frozen=True)
class SweepResult:
    param_name: str
    param_values: np.ndarray
    param_unit: str
    data: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "param_values", np.asarray(self.param_values, dtype=float))

    def __getitem__(self, column: str) -> np.ndarray:
        return np.asarray(self.data[column])

    def plot(self, x: str, y: str | list[str], **kwargs) -> None:
        plt = _matplotlib_pyplot()
        if plt is None:
            return None
        ys = [y] if isinstance(y, str) else y
        x_values = np.asarray(self.data[x])
        for column in ys:
            plt.plot(x_values, np.asarray(self.data[column]), label=column, **kwargs)
        if len(ys) > 1:
            plt.legend()
        plt.xlabel(x)
        return None

    def to_dataframe(self):
        return self.data


@dataclass(frozen=True)
class SimChannelReadingResult:
    channels: list[int]
    time: np.ndarray
    readings: dict[int, WaveformResult]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "time", np.asarray(self.time, dtype=float))
        object.__setattr__(self, "channels", [int(ch) for ch in self.channels])

    def __getitem__(self, channel: int):
        return self.for_channel(channel).time_s, self.for_channel(channel).voltage

    def for_channel(self, channel: int) -> WaveformResult:
        try:
            return self.readings[int(channel)]
        except KeyError as exc:
            raise KeyError(f"unknown channel {channel}") from exc

    def to_dataframe(self):
        pl = _polars()
        payload = {"Time (s)": self.time}
        for channel in self.channels:
            payload[f"Channel {channel} (V)"] = self.for_channel(channel).voltage
        return pl.DataFrame(payload)


def _dominant_frequency(freq_hz: np.ndarray, magnitude: np.ndarray) -> float:
    if freq_hz.size <= 1:
        return 0.0
    start = 1 if np.isclose(freq_hz[0], 0.0) else 0
    if start >= magnitude.size:
        return 0.0
    idx = start + int(np.argmax(magnitude[start:]))
    return float(freq_hz[idx])
