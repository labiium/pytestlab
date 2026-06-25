"""Multi-channel waveform acquisition results with shared clock covariance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty.atoms import AtomRegistry
from pytestlab.uncertainty.timing import TimingEstimator
from pytestlab.uncertainty.timing import TimingUncertaintyModel

from .waveform_result import AcquisitionTrace
from .waveform_result import WaveformResult


class WaveformSetTiming:
    """Timing façade for one channel in a shared-clock waveform set."""

    def __init__(self, channel: WaveformSetChannel) -> None:
        self._channel = channel

    def estimator(self) -> TimingEstimator:
        return self._channel._parent._timing_estimator(self._channel.channel)

    def threshold(self, level: float, *, edge: str = "rising", occurrence: int = 0) -> Quantity:
        return self.estimator().threshold_crossing_time(
            level,
            edge=edge,  # type: ignore[arg-type]
            occurrence=occurrence,
        )

    def period(
        self, *, level: float | None = None, edge: str = "rising", cycle: int = 0
    ) -> Quantity:
        return self.estimator().period(level=level, edge=edge, cycle=cycle)  # type: ignore[arg-type]

    def frequency(
        self, *, level: float | None = None, edge: str = "rising", cycle: int = 0
    ) -> Quantity:
        return self.estimator().frequency(level=level, edge=edge, cycle=cycle)  # type: ignore[arg-type]

    def rise_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        return self.estimator().rise_time(low=low, high=high, occurrence=occurrence)

    def fall_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        return self.estimator().fall_time(low=low, high=high, occurrence=occurrence)

    def duty_cycle(self, *, level: float | None = None, cycle: int = 0) -> Quantity:
        return self.estimator().duty_cycle(level=level, cycle=cycle)

    def delay(
        self,
        other: WaveformSetChannel,
        *,
        level: float | None = None,
        edge: str = "rising",
    ) -> Quantity:
        if not isinstance(other, WaveformSetChannel) or other._parent is not self._channel._parent:
            raise ValueError(
                "Cross-channel delay must use channels from the same WaveformSetResult to "
                "preserve shared-clock covariance. Use waveform_set.delay(a, b) or "
                "waveform_set.channel(a).timing.delay(waveform_set.channel(b))."
            )
        return self._channel._parent.delay(
            self._channel.channel,
            other.channel,
            level=level,
            edge=edge,
        )


class WaveformSetChannel:
    """Set-bound channel view that preserves shared covariance for reductions."""

    def __init__(self, parent: WaveformSetResult, channel: int) -> None:
        self._parent = parent
        self.channel = channel

    @property
    def raw(self) -> WaveformResult:
        return self._parent.raw_channel(self.channel)

    @property
    def values(self):
        return self.raw.values

    @property
    def time(self):
        return self.raw.time

    @property
    def unit(self) -> str:
        return self.raw.unit

    @property
    def point_count(self) -> int:
        return self.raw.point_count

    @property
    def instrument(self) -> str | None:
        return self.raw.instrument

    def quantity_array(self):
        return self._parent.quantity_array(self.channel)

    quantity = quantity_array

    def mean(self, *, dof_method: str = "validated_independent") -> Quantity:
        return self.quantity_array().mean(dof_method=dof_method)

    def rms(self, *, dof_method: str = "lag1_autocorrelation") -> Quantity:
        return self.quantity_array().rms(dof_method=dof_method)

    def integrate(
        self, *, dx: float | None = None, dof_method: str = "validated_independent"
    ) -> Quantity:
        if dx is None:
            if self.time is not None and self.time.size > 1:
                dx = float(np.median(np.diff(self.time)))
            else:
                dx = 1.0
        return self.quantity_array().integrate(dx=dx, dof_method=dof_method)

    def peak_to_peak(self) -> Quantity:
        return self.quantity_array().peak_to_peak()

    def peak_to_peak_monte_carlo(
        self, *, samples: int = 20_000, seed: int | None = None
    ) -> Quantity:
        return self.quantity_array().peak_to_peak_monte_carlo(samples=samples, seed=seed)

    @property
    def timing(self) -> WaveformSetTiming:
        return WaveformSetTiming(self)


@dataclass(frozen=True)
class SharedClockModel:
    """Shared horizontal timing model for one simultaneous acquisition."""

    source_key: str
    timebase_relative_std: float | None = None
    trigger_jitter_std_s: float | None = None
    sample_aperture_s: float | None = None
    interpolation_model: str = "linear"
    channel_skew_std_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WaveformSetResult:
    """A simultaneous multi-channel waveform result sharing one covariance space."""

    def __init__(
        self,
        channels: dict[int, WaveformResult],
        *,
        acquisition: AcquisitionTrace | None = None,
        clock_model: SharedClockModel | None = None,
        registry: AtomRegistry | None = None,
    ) -> None:
        if not channels:
            raise ValueError("WaveformSetResult requires at least one channel.")
        self.channels = dict(sorted(channels.items()))
        self.acquisition = acquisition or AcquisitionTrace(mode="read_only")
        self.registry = registry or AtomRegistry()
        first = next(iter(self.channels.values()))
        self.clock_model = clock_model or SharedClockModel(
            source_key=self._default_source_key(),
            timebase_relative_std=first.model.axis.timebase_relative_std,
            trigger_jitter_std_s=first.model.axis.trigger_jitter_std_s,
            sample_aperture_s=first.model.axis.sample_aperture_s,
            interpolation_model=first.model.axis.interpolation_model,
            channel_skew_std_s=first.model.axis.channel_skew_std_s,
        )
        self._quantities = {
            channel: wave.model.quantity_array(wave.values, registry=self.registry)
            for channel, wave in self.channels.items()
        }

    def _default_source_key(self) -> str:
        payload = {
            str(channel): hashlib.sha256(wave.values.tobytes()).hexdigest()
            for channel, wave in self.channels.items()
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return f"waveform_set:{digest}"

    def raw_channel(self, channel: int) -> WaveformResult:
        try:
            return self.channels[channel]
        except KeyError as exc:
            raise KeyError(f"Channel not present in waveform set: {channel}") from exc

    def channel(self, channel: int) -> WaveformSetChannel:
        self.raw_channel(channel)
        return WaveformSetChannel(self, channel)

    ch = channel

    def quantity_array(self, channel: int):
        """Return the set-owned QuantityArray for a channel in the shared registry."""

        try:
            return self._quantities[channel]
        except KeyError as exc:
            raise KeyError(f"Channel not present in waveform set: {channel}") from exc

    def _timing_estimator(self, channel: int) -> TimingEstimator:
        wave = self.raw_channel(channel)
        model = TimingUncertaintyModel(
            timebase_relative_std=self.clock_model.timebase_relative_std,
            timebase_reference_s=wave.model.axis.timebase_reference_s,
            trigger_jitter_std_s=self.clock_model.trigger_jitter_std_s,
            sample_aperture_s=self.clock_model.sample_aperture_s,
            interpolation_model=self.clock_model.interpolation_model,
            channel_skew_std_s=self.clock_model.channel_skew_std_s,
            traceability=wave.model.traceability,
            source_key=self.clock_model.source_key,
        )
        return TimingEstimator(
            self._quantities[channel],
            time=wave.time,
            axis=wave.model.axis,
            model=model,
            channel=channel,
        )

    def delay(
        self,
        ch_a: int,
        ch_b: int,
        *,
        level: float | None = None,
        edge: str = "rising",
    ) -> Quantity:
        """Return ``t(ch_b) - t(ch_a)`` with shared-clock cancellation."""

        return self._timing_estimator(ch_a).delay(
            self._timing_estimator(ch_b),
            level=level,
            edge=edge,  # type: ignore[arg-type]
        )

    def skew(self, ch_a: int, ch_b: int, **kwargs: Any) -> Quantity:
        """Alias for cross-channel delay, using oscilloscope skew terminology."""

        return self.delay(ch_a, ch_b, **kwargs)

    def to_evidence_bundle(
        self,
        output_dir: str | Path,
        *,
        identifier_prefix: str = "waveform-set",
    ) -> Path:
        """Write a compact multi-channel evidence bundle with shared clock metadata."""

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        channel_payload: dict[str, Any] = {}
        for channel, wave in self.channels.items():
            channel_payload[str(channel)] = {
                "waveform_sha256": hashlib.sha256(wave.values.tobytes()).hexdigest(),
                "time_sha256": hashlib.sha256(wave.time.tobytes()).hexdigest()
                if wave.time is not None
                else None,
                "point_count": wave.point_count,
                "unit": wave.unit,
                "metrics": {
                    "mean": _quantity_payload(self._quantities[channel].mean()),
                    "rms": _quantity_payload(self._quantities[channel].rms()),
                },
            }
        cross_channel = {}
        channel_ids = list(self.channels)
        for idx, a in enumerate(channel_ids):
            for b in channel_ids[idx + 1 :]:
                try:
                    cross_channel[f"delay_{a}_{b}"] = _quantity_payload(self.delay(a, b))
                except Exception as exc:  # evidence should record why delay was unavailable
                    cross_channel[f"delay_{a}_{b}"] = {"error": str(exc)}
        payload = {
            "schema": "pytestlab.waveform_set_evidence.v1",
            "generated_utc": datetime.now(UTC).isoformat(),
            "identifier_prefix": identifier_prefix,
            "acquisition": self.acquisition.to_dict(),
            "shared_clock_model": self.clock_model.to_dict(),
            "channels": channel_payload,
            "cross_channel": cross_channel,
            "non_accreditation_notice": (
                "PyTestLab waveform-set evidence is software-validation evidence, not accreditation, "
                "not a signed DCC, and not a calibration certificate."
            ),
        }
        payload["payload_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        path = out / "waveform_set_evidence.json"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        return path


def _quantity_payload(quantity: Quantity) -> dict[str, Any]:
    return {
        "nominal": quantity.nominal,
        "standard_uncertainty": quantity.u,
        "unit": quantity.unit,
        "measurement_model_method": getattr(quantity.measurement_model, "method", None),
        "budget": quantity.budget().to_dicts(),
    }
