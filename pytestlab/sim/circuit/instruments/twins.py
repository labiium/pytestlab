from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import numpy as np

from ..bench import AWG
from ..bench import DMM
from ..bench import PSU
from ..bench import BenchLimits
from ..bench import PSUChannel
from ..bench import Scope
from .base import InstrumentState
from .base import InstrumentTwin
from .base import MeasurementResult


def normalize_dmm_function(value: str) -> str:
    normalized = str(value).strip().upper().replace('"', "")
    mapping = {
        "DCV": "DCV",
        "VOLT:DC": "DCV",
        "VOLT": "DCV",
        "ACV": "ACV",
        "VOLT:AC": "ACV",
        "DCI": "DCI",
        "CURR:DC": "DCI",
        "CURR": "DCI",
        "ACI": "ACI",
        "CURR:AC": "ACI",
    }
    return mapping.get(normalized, normalized)


def reject_unsupported_dmm_function(function: str) -> None:
    if normalize_dmm_function(function) == "ACI":
        raise ValueError("AC current measurement is unsupported; use DCI/CURR:DC")


@dataclass
class PSUChannelState:
    voltage_setpoint: float = 0.0
    current_limit: float = 0.1
    enabled: bool = False
    mode: str = "CV"


@dataclass
class PSUState(InstrumentState):
    channels: dict[str, PSUChannelState] = field(default_factory=dict)
    selected_channel: str = "CH1"


class PSUTwin(InstrumentTwin):
    def __init__(self, seed: int, config: PSU, limits: BenchLimits):
        super().__init__(seed)
        self.cfg = config
        self.limits = limits
        channels = {ch.name: PSUChannelState() for ch in (config.channels or [])}
        selected = next(iter(channels.keys()), "CH1")
        self.state = PSUState(channels=channels, selected_channel=selected)

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "PSU",
            "modes": ["CV", "CC"],
            "channels": list(self.state.channels.keys()),
        }

    def set_state(self, **kwargs: Any) -> None:
        self._clear_warnings()
        channel_name = kwargs.pop("channel", None)
        if "selected_channel" in kwargs:
            selected = str(kwargs.pop("selected_channel"))
            if selected not in self.state.channels:
                raise ValueError("unknown PSU channel")
            self.state.selected_channel = selected

        channel_name = channel_name or self.state.selected_channel
        if channel_name not in self.state.channels:
            raise ValueError("unknown PSU channel")
        channel_cfg = self._channel_config(channel_name)
        channel_state = self.state.channels[channel_name]

        if "voltage_setpoint" in kwargs:
            voltage = float(kwargs.pop("voltage_setpoint"))
            voltage = self._clamp_capability(
                voltage,
                channel_cfg.v_max,
                "voltage_setpoint",
            )
            if abs(voltage) > self.limits.hard.max_node_voltage_v:
                raise ValueError("voltage_setpoint exceeds hard bench limit")
            channel_state.voltage_setpoint = voltage

        if "current_limit" in kwargs:
            current = float(kwargs.pop("current_limit"))
            current = self._clamp_capability(
                current,
                channel_cfg.i_max,
                "current_limit",
            )
            if abs(current) > self.limits.hard.max_branch_current_a:
                raise ValueError("current_limit exceeds hard bench limit")
            channel_state.current_limit = current

        if "enabled" in kwargs:
            channel_state.enabled = bool(kwargs.pop("enabled"))

        if kwargs:
            raise ValueError(f"unknown state field(s) {', '.join(sorted(kwargs.keys()))}")

    def measure(
        self, *, load_ohm: float | None = None, channel: str | None = None
    ) -> MeasurementResult:
        channel_name = channel or self.state.selected_channel
        if channel_name not in self.state.channels:
            raise ValueError("unknown PSU channel")
        channel_state = self.state.channels[channel_name]
        load = 10.0 if load_ohm is None else max(1e-6, float(load_ohm))
        ideal_current = channel_state.voltage_setpoint / load
        if abs(ideal_current) > channel_state.current_limit:
            current = math.copysign(channel_state.current_limit, ideal_current)
            voltage = current * load
            mode = "CC"
        else:
            voltage = channel_state.voltage_setpoint
            current = ideal_current
            mode = "CV"

        voltage = self._apply_noise(voltage, 1e-3)
        current = self._apply_noise(current, 1e-4)
        channel_state.mode = mode
        return MeasurementResult(
            values={
                "channel": channel_name,
                "voltage": voltage,
                "current": current,
                "mode": mode,
            },
            units="V/A",
        )

    def _channel_config(self, name: str) -> PSUChannel:
        for channel in self.cfg.channels:
            if channel.name == name:
                return channel
        return PSUChannel(name=name, v_max=30.0, i_max=3.0)

    def _clamp_capability(self, value: float, limit: float, label: str) -> float:
        if abs(value) <= limit:
            return value
        self._warn(f"{label} clamped to {limit}")
        return math.copysign(limit, value)


@dataclass
class AWGState(InstrumentState):
    waveform: str = "sine"
    frequency_hz: float = 1e3
    amplitude_vpp: float = 1.0
    offset_v: float = 0.0
    voltage_unit: str = "VPP"
    phase_deg: float = 0.0
    duty_cycle: float = 0.5
    burst_enabled: bool = False
    burst_count: int = 1
    phase_continuous: bool = True


class AWGTwin(InstrumentTwin):
    def __init__(self, seed: int, config: AWG, limits: BenchLimits):
        super().__init__(seed)
        self.cfg = config
        self.limits = limits
        self.state = AWGState()

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "AWG",
            "waveforms": ["sine", "square", "triangle", "pulse", "dc"],
            "phase_policy": "continuous" if self.state.phase_continuous else "reset",
        }

    def set_state(self, **kwargs: Any) -> None:
        self._clear_warnings()
        unit = str(kwargs.get("voltage_unit", self.state.voltage_unit)).upper()
        if "waveform" in kwargs:
            waveform = str(kwargs["waveform"]).lower()
            allowed = {"sine", "square", "triangle", "pulse", "dc"}
            if waveform not in allowed:
                raise ValueError(f"unsupported waveform: {waveform}")
            kwargs["waveform"] = waveform

        if "frequency_hz" in kwargs:
            freq = float(kwargs["frequency_hz"])
            if freq < 0:
                raise ValueError("frequency_hz must be non-negative")
            kwargs["frequency_hz"] = freq

        if "amplitude_vpp" in kwargs:
            amp = float(kwargs["amplitude_vpp"])
            if amp < 0:
                raise ValueError("amplitude_vpp must be non-negative")
            max_amp = self._max_amplitude_for_unit(unit)
            amp = self._clamp_capability(amp, max_amp, "amplitude_vpp")
            kwargs["amplitude_vpp"] = amp

        if "offset_v" in kwargs:
            kwargs["offset_v"] = float(kwargs["offset_v"])

        if "phase_deg" in kwargs:
            kwargs["phase_deg"] = float(kwargs["phase_deg"]) % 360.0

        if "duty_cycle" in kwargs:
            duty = float(kwargs["duty_cycle"])
            if not 0.0 < duty < 1.0:
                raise ValueError("duty_cycle must be between 0 and 1")
            kwargs["duty_cycle"] = duty

        if "burst_count" in kwargs:
            count = int(kwargs["burst_count"])
            if count < 1:
                raise ValueError("burst_count must be >= 1")
            kwargs["burst_count"] = count

        amp = float(kwargs.get("amplitude_vpp", self.state.amplitude_vpp))
        offset = float(kwargs.get("offset_v", self.state.offset_v))
        peak = abs(offset) + self._amplitude_vpp_from_unit(amp, unit) / 2.0
        if peak > self.limits.hard.max_node_voltage_v:
            raise ValueError("AWG output exceeds hard bench voltage limit")

        super().set_state(**kwargs)

    def render_waveform(self, duration_s: float, sample_rate: float) -> MeasurementResult:
        duration_s = max(0.0, float(duration_s))
        sample_rate = max(1.0, float(sample_rate))
        t = np.arange(0, duration_s, 1.0 / sample_rate)
        freq = float(self.state.frequency_hz)
        phase = float(self.state.phase_deg) / 360.0

        if self.state.waveform == "sine":
            raw = np.sin(2 * math.pi * (freq * t + phase))
        elif self.state.waveform == "square":
            duty = float(self.state.duty_cycle)
            phase_t = (freq * t + phase) % 1.0
            raw = np.where(phase_t < duty, 1.0, -1.0)
        elif self.state.waveform == "triangle":
            phase_t = (freq * t + phase) % 1.0
            raw = 2.0 * np.abs(2.0 * phase_t - 1.0) - 1.0
        elif self.state.waveform == "pulse":
            duty = float(self.state.duty_cycle)
            phase_t = (freq * t + phase) % 1.0
            raw = np.where(phase_t < duty, 1.0, -1.0)
        else:
            raw = np.ones_like(t)

        amp_vpp = self._amplitude_vpp_from_unit(self.state.amplitude_vpp)
        scaled = (amp_vpp / 2.0) * raw
        waveform = scaled + float(self.state.offset_v)

        if self.state.burst_enabled and freq > 0:
            burst_duration = self.state.burst_count / freq
            waveform = np.where(t <= burst_duration, waveform, float(self.state.offset_v))

        waveform += self.random.normalvariate(0, 1e-3)
        return MeasurementResult(values={"t": t, "v": waveform}, units="s/V")

    def _amplitude_vpp_from_unit(self, amplitude: float, unit: str | None = None) -> float:
        unit = str(unit or self.state.voltage_unit).upper()
        if unit == "VRMS":
            return float(amplitude) * 2.0 * math.sqrt(2.0)
        return float(amplitude)

    def _max_amplitude_for_unit(self, unit: str) -> float:
        if unit == "VRMS":
            return float(self.cfg.vpp_max) / (2.0 * math.sqrt(2.0))
        return float(self.cfg.vpp_max)

    def _clamp_capability(self, value: float, limit: float, label: str) -> float:
        if abs(value) <= limit:
            return value
        self._warn(f"{label} clamped to {limit}")
        return math.copysign(limit, value)


@dataclass
class DMMState(InstrumentState):
    function: str = "DCV"
    aperture_s: float = 0.02
    range_v: float = 10.0
    auto_range: bool = True
    resolution_digits: float = 6.5


class DMMTwin(InstrumentTwin):
    def __init__(self, seed: int, config: DMM, limits: BenchLimits):
        super().__init__(seed)
        self.cfg = config
        self.limits = limits
        self.state = DMMState(resolution_digits=float(config.digits))

    def describe(self) -> dict[str, Any]:
        return {"kind": "DMM", "functions": ["DCV", "ACV", "DCI"]}

    def set_state(self, **kwargs: Any) -> None:
        self._clear_warnings()
        if "function" in kwargs:
            kwargs["function"] = self._normalize_function(str(kwargs["function"]))
            reject_unsupported_dmm_function(str(kwargs["function"]))
        if "aperture_s" in kwargs:
            aperture = float(kwargs["aperture_s"])
            if aperture <= 0:
                raise ValueError("aperture_s must be positive")
            kwargs["aperture_s"] = aperture
        if "range_v" in kwargs:
            rng = float(kwargs["range_v"])
            if rng <= 0:
                raise ValueError("range_v must be positive")
            kwargs["range_v"] = rng
        if "auto_range" in kwargs:
            kwargs["auto_range"] = bool(kwargs["auto_range"])
        if "resolution_digits" in kwargs:
            kwargs["resolution_digits"] = float(kwargs["resolution_digits"])
        super().set_state(**kwargs)

    def measure(
        self, signal: float | np.ndarray, *, sample_rate: float | None = None
    ) -> MeasurementResult:
        reject_unsupported_dmm_function(self.state.function)
        if isinstance(signal, np.ndarray):
            wave = np.asarray(signal, dtype=float)
            if sample_rate and sample_rate > 0:
                window = int(round(self.state.aperture_s * sample_rate))
                if window > 1 and wave.size >= window:
                    wave = wave[-window:]
        else:
            wave = np.asarray([float(signal)], dtype=float)

        if self.state.function == "ACV":
            dc = float(np.mean(wave))
            value = float(np.sqrt(np.mean((wave - dc) ** 2)))
        else:
            value = float(np.mean(wave))

        value = self._apply_noise(value, 1e-5)
        value = self._quantize(value)
        units = "A" if self.state.function == "DCI" else "V"
        return MeasurementResult(values=value, units=units)

    def _quantize(self, value: float) -> float:
        rng = self.state.range_v
        if self.state.auto_range:
            rng = self._auto_range(abs(value))
            self.state.range_v = rng

        if rng <= 0:
            return value

        counts = 10 ** float(self.state.resolution_digits)
        lsb = rng / counts
        if lsb <= 0:
            return value

        if abs(value) > rng:
            self._warn("reading clipped to range")
            value = math.copysign(rng, value)
        return round(value / lsb) * lsb

    def _auto_range(self, magnitude: float) -> float:
        ranges = [0.1, 1.0, 10.0, 100.0, 1000.0]
        for rng in ranges:
            if magnitude <= rng:
                return rng
        return ranges[-1]

    def _normalize_function(self, value: str) -> str:
        return normalize_dmm_function(value)


@dataclass
class ScopeState(InstrumentState):
    timebase_s: float = 1e-3
    sample_rate: float = 1e6
    record_length: int = 10_000
    trigger_level: float = 0.0
    trigger_source: str = "CH1"
    trigger_slope: str = "POS"
    coupling: str = "DC"
    bandwidth_hz: float = 20e6
    enob: float = 8.0
    vertical_scale_v: float = 1.0
    vertical_offset_v: float = 0.0


class ScopeTwin(InstrumentTwin):
    def __init__(self, seed: int, config: Scope, limits: BenchLimits):
        super().__init__(seed)
        self.cfg = config
        self.limits = limits
        max_points = limits.soft.get("max_scope_record_points", 2_000_000)
        self.max_record_length = int(max_points) if max_points else 2_000_000
        default_rate = min(float(config.sample_rate_sps_max), 1.0e6)
        self.state = ScopeState(
            bandwidth_hz=float(config.bandwidth_hz),
            enob=float(config.enob),
            sample_rate=default_rate,
        )
        if self.state.record_length > self.max_record_length:
            self.state.record_length = self.max_record_length

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "SCOPE",
            "capabilities": ["edge_trigger"],
            "max_record_length": self.max_record_length,
        }

    def set_state(self, **kwargs: Any) -> None:
        self._clear_warnings()
        if "sample_rate" in kwargs:
            rate = float(kwargs["sample_rate"])
            if rate <= 0:
                raise ValueError("sample_rate must be positive")
            if rate > self.cfg.sample_rate_sps_max:
                self._warn("sample_rate clamped to max")
                rate = float(self.cfg.sample_rate_sps_max)
            kwargs["sample_rate"] = rate

        if "record_length" in kwargs:
            length = int(kwargs["record_length"])
            if length <= 0:
                raise ValueError("record_length must be positive")
            if length > self.max_record_length:
                self._warn("record_length clamped to max")
                length = self.max_record_length
            kwargs["record_length"] = length

        if "timebase_s" in kwargs and "record_length" not in kwargs:
            timebase = float(kwargs["timebase_s"])
            if timebase > 0 and self.state.sample_rate > 0:
                points = int(round(timebase * self.state.sample_rate * 10.0))
                points = max(1, min(points, self.max_record_length))
                kwargs["record_length"] = points

        if "bandwidth_hz" in kwargs:
            bw = float(kwargs["bandwidth_hz"])
            if bw <= 0:
                raise ValueError("bandwidth_hz must be positive")
            if bw > self.cfg.bandwidth_hz:
                self._warn("bandwidth clamped to max")
                bw = float(self.cfg.bandwidth_hz)
            kwargs["bandwidth_hz"] = bw

        if "enob" in kwargs:
            enob = float(kwargs["enob"])
            if enob <= 0:
                raise ValueError("enob must be positive")
            kwargs["enob"] = enob

        if "vertical_scale_v" in kwargs:
            scale = float(kwargs["vertical_scale_v"])
            if scale <= 0:
                raise ValueError("vertical_scale_v must be positive")
            kwargs["vertical_scale_v"] = scale

        if "vertical_offset_v" in kwargs:
            kwargs["vertical_offset_v"] = float(kwargs["vertical_offset_v"])

        if "coupling" in kwargs:
            coupling = str(kwargs["coupling"]).upper()
            if coupling not in {"AC", "DC"}:
                raise ValueError("unsupported coupling")
            kwargs["coupling"] = coupling

        if "trigger_slope" in kwargs:
            slope = str(kwargs["trigger_slope"]).upper()
            if slope not in {"POS", "NEG"}:
                raise ValueError("unsupported trigger slope")
            kwargs["trigger_slope"] = slope

        super().set_state(**kwargs)

    def compute_trigger_index(
        self, waveform: np.ndarray, *, probe_attenuation: float = 1.0
    ) -> int | None:
        if waveform.size == 0:
            return None
        record_length = int(self.state.record_length)
        sample_rate = float(self.state.sample_rate)
        if sample_rate <= 0:
            return None

        raw = np.asarray(waveform, dtype=float)
        if raw.size != record_length:
            raw = (
                raw[:record_length]
                if raw.size > record_length
                else np.pad(raw, (0, record_length - raw.size))
            )

        attenuation = probe_attenuation if probe_attenuation > 0 else 1.0
        wave_in = raw / attenuation
        if self.state.coupling == "AC":
            wave_in = wave_in - float(np.mean(wave_in))

        wave_filt = _lowpass_filter(wave_in, self.state.bandwidth_hz, sample_rate)
        _, trigger_index = _align_trigger(
            wave_filt, self.state.trigger_level, self.state.trigger_slope
        )
        return trigger_index

    def acquire(
        self,
        waveform: np.ndarray,
        *,
        probe_attenuation: float = 1.0,
        trigger_index: int | None = None,
    ) -> MeasurementResult:
        if waveform.size == 0:
            raise ValueError("empty waveform")
        record_length = int(self.state.record_length)
        sample_rate = float(self.state.sample_rate)
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

        raw = np.asarray(waveform, dtype=float)
        if raw.size != record_length:
            raw = (
                raw[:record_length]
                if raw.size > record_length
                else np.pad(raw, (0, record_length - raw.size))
            )

        attenuation = probe_attenuation if probe_attenuation > 0 else 1.0
        wave_in = raw / attenuation
        if self.state.coupling == "AC":
            wave_in = wave_in - float(np.mean(wave_in))

        wave_filt = _lowpass_filter(wave_in, self.state.bandwidth_hz, sample_rate)
        if trigger_index is None:
            wave_trig, trigger_index = _align_trigger(
                wave_filt, self.state.trigger_level, self.state.trigger_slope
            )
        else:
            wave_trig = np.roll(wave_filt, -trigger_index)

        wave_quant = _quantize_waveform(
            wave_trig,
            self.state.vertical_scale_v,
            self.state.vertical_offset_v,
            self.state.enob,
        )
        wave_out = wave_quant * attenuation

        time_axis = np.arange(0, wave_out.size) / sample_rate
        return MeasurementResult(
            values={"t": time_axis, "v": wave_out},
            units="s/V",
            metadata={
                "trigger_source": self.state.trigger_source,
                "trigger_level": self.state.trigger_level,
                "trigger_index": trigger_index,
                "bandwidth_hz": self.state.bandwidth_hz,
                "probe_attenuation": attenuation,
            },
        )


def _lowpass_filter(wave: np.ndarray, cutoff_hz: float, sample_rate: float) -> np.ndarray:
    if cutoff_hz <= 0 or sample_rate <= 0:
        return np.asarray(wave, dtype=float)
    dt = 1.0 / sample_rate
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    alpha = dt / (rc + dt)
    out = np.empty_like(wave, dtype=float)
    out[0] = wave[0]
    for idx in range(1, wave.size):
        out[idx] = out[idx - 1] + alpha * (wave[idx] - out[idx - 1])
    return out


def _align_trigger(wave: np.ndarray, level: float, slope: str) -> tuple[np.ndarray, int | None]:
    if wave.size < 2:
        return wave, None
    if slope == "NEG":
        crossings = np.where((wave[:-1] > level) & (wave[1:] <= level))[0]
    else:
        crossings = np.where((wave[:-1] < level) & (wave[1:] >= level))[0]
    if crossings.size == 0:
        return wave, None
    idx = int(crossings[0])
    return np.roll(wave, -idx), idx


def _quantize_waveform(
    wave: np.ndarray, vertical_scale_v: float, vertical_offset_v: float, enob: float
) -> np.ndarray:
    if vertical_scale_v <= 0:
        return np.asarray(wave, dtype=float)
    full_scale = vertical_scale_v * 8.0
    bits = max(1, int(round(enob)))
    lsb = full_scale / (2**bits)
    v_min = vertical_offset_v - full_scale / 2.0
    v_max = vertical_offset_v + full_scale / 2.0
    clipped = np.clip(wave, v_min, v_max)
    quantized = np.round((clipped - vertical_offset_v) / lsb) * lsb + vertical_offset_v
    return quantized
