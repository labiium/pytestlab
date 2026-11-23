"""Timing measurands with explicit horizontal uncertainty propagation.

This module keeps oscilloscope timing reductions in the same first-order GUM
model as scalar and waveform-voltage quantities.  Edge times are estimated by
linear interpolation and carry sensitivities to adjacent voltage samples,
threshold level, trigger jitter, and timebase scale.  Interval measurands then
compose those edge-time quantities so shared trigger terms cancel naturally.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike

from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import Kind
from .metrology import InputQuantityRecord
from .metrology import MeasurementModel
from .metrology import ResultProvenance
from .metrology import TraceabilityRef
from .quantity import Quantity
from .quantity_array import QuantityArray
from .waveform import WaveformAxis

Edge = Literal["rising", "falling", "either"]


class TimingMeasurementError(ValueError):
    """Raised when a waveform cannot support an unambiguous timing measurand."""


@dataclass(frozen=True)
class TimingUncertaintyModel:
    """Horizontal timing uncertainty inputs for waveform timing reductions.

    Standard uncertainties are used throughout.  ``timebase_relative_std`` is a
    relative scale term; ``trigger_jitter_std_s`` is a shared additive time term;
    ``sample_aperture_s`` is currently recorded as an assumption until a
    reconstruction model is selected.
    """

    timebase_relative_std: float | None = None
    timebase_reference_s: float = 0.0
    trigger_jitter_std_s: float | None = None
    sample_aperture_s: float | None = None
    interpolation_model: str = "linear"
    channel_skew_std_s: float | None = None
    traceability: TraceabilityRef | None = None
    source_key: str | None = None

    @classmethod
    def from_axis(
        cls,
        axis: WaveformAxis | None,
        *,
        traceability: TraceabilityRef | None = None,
        source_key: str | None = None,
    ) -> TimingUncertaintyModel:
        if axis is None:
            return cls(traceability=traceability, source_key=source_key)
        return cls(
            timebase_relative_std=axis.timebase_relative_std,
            timebase_reference_s=axis.timebase_reference_s,
            trigger_jitter_std_s=axis.trigger_jitter_std_s,
            sample_aperture_s=axis.sample_aperture_s,
            interpolation_model=axis.interpolation_model,
            channel_skew_std_s=axis.channel_skew_std_s,
            traceability=traceability,
            source_key=source_key,
        )

    @property
    def has_reportable_horizontal_terms(self) -> bool:
        return bool(self.timebase_relative_std or self.trigger_jitter_std_s)

    def assumptions(self) -> list[str]:
        assumptions = [f"interpolation_model={self.interpolation_model}"]
        if self.sample_aperture_s is None:
            assumptions.append("sample_aperture_s missing; timing output is not report-grade")
        else:
            assumptions.append(f"sample_aperture_s={self.sample_aperture_s:g}")
        if not self.has_reportable_horizontal_terms:
            assumptions.append("horizontal timebase/trigger specifications missing")
        if self.channel_skew_std_s is not None:
            assumptions.append(f"channel_skew_std_s={self.channel_skew_std_s:g}")
        return assumptions


@dataclass(frozen=True)
class EdgeTime:
    """One threshold-crossing event and its uncertainty-bearing time."""

    quantity: Quantity
    index: int
    fraction: float
    level: float
    edge: str


class TimingEstimator:
    """Pure-function timing estimator façade for a waveform quantity array."""

    def __init__(
        self,
        voltage: QuantityArray,
        *,
        time: ArrayLike | None = None,
        axis: WaveformAxis | None = None,
        model: TimingUncertaintyModel | None = None,
        channel: int | None = None,
    ) -> None:
        self.voltage = voltage
        self.time = _resolve_time_axis(time, axis, len(voltage))
        self.model = model or TimingUncertaintyModel.from_axis(axis)
        self.channel = channel

    def threshold_crossing_time(
        self, level: float | Quantity, *, edge: Edge = "rising", occurrence: int = 0
    ) -> Quantity:
        return threshold_crossing_time(
            self.time,
            self.voltage,
            level,
            edge=edge,
            occurrence=occurrence,
            model=self.model,
            channel=self.channel,
        )

    def period(
        self, *, level: float | None = None, edge: Edge = "rising", cycle: int = 0
    ) -> Quantity:
        return period_from_edges(
            self.time,
            self.voltage,
            level=level,
            edge=edge,
            cycle=cycle,
            model=self.model,
            channel=self.channel,
        )

    def frequency(
        self, *, level: float | None = None, edge: Edge = "rising", cycle: int = 0
    ) -> Quantity:
        return frequency_from_period(self.period(level=level, edge=edge, cycle=cycle))

    def rise_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        return rise_time_10_90(
            self.time,
            self.voltage,
            low=low,
            high=high,
            occurrence=occurrence,
            model=self.model,
            channel=self.channel,
        )

    def fall_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        return fall_time_90_10(
            self.time,
            self.voltage,
            low=low,
            high=high,
            occurrence=occurrence,
            model=self.model,
            channel=self.channel,
        )

    def duty_cycle(self, *, level: float | None = None, cycle: int = 0) -> Quantity:
        return duty_cycle(
            self.time,
            self.voltage,
            level=level,
            cycle=cycle,
            model=self.model,
            channel=self.channel,
        )

    def delay(
        self, other: TimingEstimator, *, level: float | None = None, edge: Edge = "rising"
    ) -> Quantity:
        return delay_between(self, other, level=level, edge=edge)


def threshold_crossing_time(
    time: ArrayLike,
    voltage: QuantityArray | ArrayLike,
    level: float | Quantity,
    *,
    edge: Edge = "rising",
    occurrence: int = 0,
    model: TimingUncertaintyModel | None = None,
    channel: int | None = None,
) -> Quantity:
    """Return the uncertainty-bearing time of a threshold crossing.

    The interpolation model is linear.  Voltage uncertainty is propagated through
    exact local sensitivities to the two bracketing samples; horizontal
    uncertainty is added as shared trigger jitter and relative timebase scale.
    """

    qa = _as_quantity_array(voltage)
    t = _as_time(time, len(qa))
    level_nominal = level.nominal if isinstance(level, Quantity) else float(level)
    crossings = _crossing_indices(t, qa.nominal, level_nominal, edge=edge)
    if occurrence < 0:
        occurrence = len(crossings) + occurrence
    if occurrence < 0 or occurrence >= len(crossings):
        raise TimingMeasurementError(
            f"No {edge} threshold crossing #{occurrence} at level {level_nominal:g}."
        )
    idx = crossings[occurrence]
    return _edge_time_quantity(
        t,
        qa,
        level,
        idx,
        edge=edge,
        model=model or TimingUncertaintyModel(),
        channel=channel,
    )


def period_from_edges(
    time: ArrayLike,
    voltage: QuantityArray | ArrayLike,
    *,
    level: float | None = None,
    edge: Edge = "rising",
    cycle: int = 0,
    model: TimingUncertaintyModel | None = None,
    channel: int | None = None,
) -> Quantity:
    qa = _as_quantity_array(voltage)
    t = _as_time(time, len(qa))
    threshold = _default_level(qa.nominal) if level is None else float(level)
    first = threshold_crossing_time(
        t, qa, threshold, edge=edge, occurrence=cycle, model=model, channel=channel
    )
    second = threshold_crossing_time(
        t, qa, threshold, edge=edge, occurrence=cycle + 1, model=model, channel=channel
    )
    return interval_between(
        first,
        second,
        output_name="period",
        function="period_from_edges(waveform)",
        assumptions=["period from consecutive same-edge threshold crossings"],
    )


def frequency_from_period(period: Quantity) -> Quantity:
    if period.nominal <= 0.0:
        raise TimingMeasurementError("Period must be positive to compute frequency.")
    q = Quantity(
        1.0 / period.nominal,
        "Hz",
        {uid: -g / (period.nominal**2) for uid, g in period.grad.items()},
        period.registry,
    )
    q.measurement_model = MeasurementModel(
        output_name="frequency",
        output_unit="Hz",
        function="1 / period",
        inputs=_inputs_from_grad(q),
        method="gum_first_order",
        assumptions=["frequency derived from period; first-order reciprocal propagation"],
        dof_method=period.dof_method or "first_order_reciprocal",
    )
    q.provenance = period.provenance
    q.dof_method = period.dof_method or "first_order_reciprocal"
    return q


def rise_time_10_90(
    time: ArrayLike,
    voltage: QuantityArray | ArrayLike,
    *,
    low: float = 0.1,
    high: float = 0.9,
    occurrence: int = 0,
    model: TimingUncertaintyModel | None = None,
    channel: int | None = None,
) -> Quantity:
    qa = _as_quantity_array(voltage)
    lo, hi = _fractional_levels(qa.nominal, low, high)
    t_low = threshold_crossing_time(
        time, qa, lo, edge="rising", occurrence=occurrence, model=model, channel=channel
    )
    t_high = threshold_crossing_time(
        time, qa, hi, edge="rising", occurrence=occurrence, model=model, channel=channel
    )
    return interval_between(
        t_low,
        t_high,
        output_name="rise_time",
        function="rise_time_10_90(waveform)",
        assumptions=[f"rise time thresholds {low:g}/{high:g} of observed min/max"],
    )


def fall_time_90_10(
    time: ArrayLike,
    voltage: QuantityArray | ArrayLike,
    *,
    low: float = 0.1,
    high: float = 0.9,
    occurrence: int = 0,
    model: TimingUncertaintyModel | None = None,
    channel: int | None = None,
) -> Quantity:
    qa = _as_quantity_array(voltage)
    lo, hi = _fractional_levels(qa.nominal, low, high)
    t_high = threshold_crossing_time(
        time, qa, hi, edge="falling", occurrence=occurrence, model=model, channel=channel
    )
    t_low = threshold_crossing_time(
        time, qa, lo, edge="falling", occurrence=occurrence, model=model, channel=channel
    )
    return interval_between(
        t_high,
        t_low,
        output_name="fall_time",
        function="fall_time_90_10(waveform)",
        assumptions=[f"fall time thresholds {high:g}/{low:g} of observed min/max"],
    )


def duty_cycle(
    time: ArrayLike,
    voltage: QuantityArray | ArrayLike,
    *,
    level: float | None = None,
    cycle: int = 0,
    model: TimingUncertaintyModel | None = None,
    channel: int | None = None,
) -> Quantity:
    qa = _as_quantity_array(voltage)
    t = _as_time(time, len(qa))
    threshold = _default_level(qa.nominal) if level is None else float(level)
    rising = _crossing_indices(t, qa.nominal, threshold, edge="rising")
    falling = _crossing_indices(t, qa.nominal, threshold, edge="falling")
    if cycle < 0 or cycle + 1 >= len(rising):
        raise TimingMeasurementError("Duty cycle requires two rising edges for one complete cycle.")
    rise_a = threshold_crossing_time(
        t, qa, threshold, edge="rising", occurrence=cycle, model=model, channel=channel
    )
    rise_b = threshold_crossing_time(
        t, qa, threshold, edge="rising", occurrence=cycle + 1, model=model, channel=channel
    )
    fall_between = [
        idx
        for idx in falling
        if _crossing_nominal_time(t, qa.nominal, threshold, idx) > rise_a.nominal
    ]
    fall_between = [
        idx
        for idx in fall_between
        if _crossing_nominal_time(t, qa.nominal, threshold, idx) < rise_b.nominal
    ]
    if not fall_between:
        raise TimingMeasurementError(
            "Duty cycle requires a falling edge between consecutive rising edges."
        )
    fall_idx = falling.index(fall_between[0])
    fall = threshold_crossing_time(
        t, qa, threshold, edge="falling", occurrence=fall_idx, model=model, channel=channel
    )
    high_time = interval_between(
        rise_a, fall, output_name="high_time", function="high_time(waveform)"
    )
    period = interval_between(
        rise_a, rise_b, output_name="period", function="period_from_edges(waveform)"
    )
    if period.nominal <= 0.0:
        raise TimingMeasurementError("Duty cycle period must be positive.")
    q = high_time / period
    q.measurement_model = MeasurementModel(
        output_name="duty_cycle",
        output_unit="",
        function="high_time / period",
        inputs=_inputs_from_grad(q),
        method="gum_first_order",
        assumptions=["duty cycle from rising/falling/rising threshold crossings"],
        dof_method=high_time.dof_method or period.dof_method or "first_order_ratio",
    )
    q.provenance = _shared_provenance(high_time.provenance, period.provenance)
    q.dof_method = high_time.dof_method or period.dof_method or "first_order_ratio"
    return q


def delay_between(
    first: TimingEstimator,
    second: TimingEstimator,
    *,
    level: float | None = None,
    edge: Edge = "rising",
) -> Quantity:
    level_a = _default_level(first.voltage.nominal) if level is None else float(level)
    level_b = _default_level(second.voltage.nominal) if level is None else float(level)
    a = first.threshold_crossing_time(level_a, edge=edge)
    b = second.threshold_crossing_time(level_b, edge=edge)
    return interval_between(
        a,
        b,
        output_name="delay",
        function="delay_between(wave_a, wave_b)",
        assumptions=["positive delay means second waveform crosses after first"],
    )


def interval_between(
    start: Quantity,
    stop: Quantity,
    *,
    output_name: str,
    function: str,
    assumptions: list[str] | None = None,
) -> Quantity:
    if stop.registry is start.registry:
        q = stop - start
        q.registry = stop.registry
    else:
        # Conservative fallback for independent single-wave acquisitions.  Shared
        # clock cancellation requires WaveformSetResult, so do not invent it here.
        warnings.warn(
            "Timing quantities come from different uncertainty registries; returning a "
            "conservative independent interval without shared-clock cancellation. Use "
            "WaveformSetResult.delay(...) or waveform_set.channel(a).timing.delay(...) "
            "for simultaneous cross-channel acquisitions.",
            RuntimeWarning,
            stacklevel=2,
        )
        reg = AtomRegistry()
        std = math.hypot(start.u, stop.u)
        grad: dict[str, float] = {}
        if std > 0.0:
            atom = reg.mint(
                nominal=0.0,
                std_uncertainty=std,
                label=f"{function}:independent_waveform_events",
                unit="s",
                distribution=Distribution.STANDARD,
                kind=Kind.TYPE_B,
                source="independent_waveform_combination",
                traceability=TraceabilityRef(source="assumed"),
            )
            grad[atom.uid] = 1.0
        q = Quantity(stop.nominal - start.nominal, "s", grad, reg)
        assumptions = [
            *(assumptions or []),
            "event registries differ; shared-clock cancellation unavailable",
        ]
    q.measurement_model = MeasurementModel(
        output_name=output_name,
        output_unit="s" if output_name != "duty_cycle" else "",
        function=function,
        inputs=_inputs_from_grad(q),
        method="gum_first_order",
        assumptions=assumptions or [],
        dof_method="first_order_interval",
    )
    q.provenance = _shared_provenance(start.provenance, stop.provenance)
    q.dof_method = "first_order_interval"
    return q


def _edge_time_quantity(
    time: np.ndarray,
    voltage: QuantityArray,
    level: float | Quantity,
    idx: int,
    *,
    edge: str,
    model: TimingUncertaintyModel,
    channel: int | None,
) -> Quantity:
    v0 = float(voltage.nominal[idx])
    v1 = float(voltage.nominal[idx + 1])
    t0 = float(time[idx])
    t1 = float(time[idx + 1])
    level_nominal = level.nominal if isinstance(level, Quantity) else float(level)
    dv = v1 - v0
    dt = t1 - t0
    if not math.isfinite(dv) or not math.isfinite(dt) or dt <= 0.0 or dv == 0.0:
        raise TimingMeasurementError("Threshold crossing is not locally monotonic in time/value.")
    fraction = (level_nominal - v0) / dv
    if fraction < -1e-12 or fraction > 1.0 + 1e-12:
        raise TimingMeasurementError("Selected segment does not bracket the threshold.")
    nominal = t0 + fraction * dt
    weights = np.zeros(len(voltage), dtype=float)
    weights[idx] = dt * (level_nominal - v1) / (dv**2)
    weights[idx + 1] = -dt * (level_nominal - v0) / (dv**2)
    diag_var = float(np.sum((weights**2) * voltage.diagonal_variance))
    grad = {
        uid: dot
        for uid, sensitivity in voltage.atom_sensitivities.items()
        if (dot := float(np.dot(weights, sensitivity))) != 0.0
    }
    if isinstance(level, Quantity):
        if level.registry is not voltage.registry and level.grad:
            raise TimingMeasurementError(
                "Uncertain threshold level must share the waveform registry."
            )
        level_sensitivity = dt / dv
        for uid, g in level.grad.items():
            grad[uid] = grad.get(uid, 0.0) + level_sensitivity * g
    reg = voltage.registry
    trace = model.traceability or TraceabilityRef(source="manufacturer_spec")
    if diag_var > 0.0:
        atom = reg.mint(
            nominal=0.0,
            std_uncertainty=math.sqrt(diag_var),
            label="edge_voltage_noise_to_time",
            unit="s",
            distribution=Distribution.STANDARD,
            degrees_of_freedom=max(1.0, len(voltage) - 1.0),
            kind=Kind.TYPE_A,
            source="type_a_measurement",
            traceability=TraceabilityRef(source="type_a_measurement"),
        )
        grad[atom.uid] = grad.get(atom.uid, 0.0) + 1.0
    if model.trigger_jitter_std_s and model.trigger_jitter_std_s > 0.0:
        atom = reg.mint(
            nominal=0.0,
            std_uncertainty=float(model.trigger_jitter_std_s),
            label="trigger_jitter",
            unit="s",
            distribution=Distribution.STANDARD,
            kind=Kind.TYPE_B,
            source=trace.source,
            traceability=trace,
            key=f"{_timing_source_key(model, reg)}:trigger_jitter",
        )
        grad[atom.uid] = grad.get(atom.uid, 0.0) + 1.0
    if model.timebase_relative_std and model.timebase_relative_std > 0.0:
        atom = reg.mint(
            nominal=0.0,
            std_uncertainty=float(model.timebase_relative_std),
            label="timebase_relative_scale",
            unit="",
            distribution=Distribution.STANDARD,
            kind=Kind.TYPE_B,
            source=trace.source,
            traceability=trace,
            key=f"{_timing_source_key(model, reg)}:timebase_relative_scale",
        )
        grad[atom.uid] = grad.get(atom.uid, 0.0) + (nominal - model.timebase_reference_s)
    if model.channel_skew_std_s and model.channel_skew_std_s > 0.0 and channel is not None:
        atom = reg.mint(
            nominal=0.0,
            std_uncertainty=float(model.channel_skew_std_s),
            label=f"channel_{channel}_timing_skew",
            unit="s",
            distribution=Distribution.STANDARD,
            kind=Kind.TYPE_B,
            source=trace.source,
            traceability=trace,
            key=f"{_timing_source_key(model, reg)}:channel_skew:{channel}",
        )
        grad[atom.uid] = grad.get(atom.uid, 0.0) + 1.0
    q = Quantity(nominal, "s", grad, reg)
    inputs = _inputs_from_grad(q)
    assumptions = [
        *model.assumptions(),
        f"edge={edge}",
        f"threshold_level={level_nominal:g}",
        f"bracketing_samples={idx},{idx + 1}",
        "voltage sensitivity propagated through local inverse slew rate",
    ]
    q.measurement_model = MeasurementModel(
        output_name="threshold_crossing_time"
        if channel is None
        else f"threshold_crossing_time_ch{channel}",
        output_unit="s",
        function="linear_threshold_crossing(time, voltage, level)",
        inputs=inputs,
        method="gum_first_order",
        linearization_note="First-order interpolation around the selected monotonic edge.",
        assumptions=assumptions,
        dof_method="first_order_edge_interpolation"
        if model.has_reportable_horizontal_terms
        else "horizontal_spec_required",
    )
    q.provenance = voltage.provenance
    q.dof_method = q.measurement_model.dof_method
    return q


def _inputs_from_grad(quantity: Quantity) -> list[InputQuantityRecord]:
    inputs: list[InputQuantityRecord] = []
    for uid in quantity.grad:
        atom = quantity.registry.atoms[uid]
        inputs.append(
            InputQuantityRecord(
                name=atom.label,
                unit=atom.unit or "",
                distribution=atom.distribution.value,
                traceability_ref=atom.traceability,
                dof=atom.degrees_of_freedom,
            )
        )
    return inputs


def _crossing_indices(
    time: np.ndarray, values: np.ndarray, level: float, *, edge: Edge
) -> list[int]:
    _ = time
    if edge not in {"rising", "falling", "either"}:
        raise ValueError("edge must be 'rising', 'falling', or 'either'.")
    crossings: list[int] = []
    for idx, (v0, v1) in enumerate(zip(values[:-1], values[1:], strict=True)):
        if not (math.isfinite(float(v0)) and math.isfinite(float(v1))):
            continue
        rising = v1 > v0 and v0 <= level <= v1
        falling = v1 < v0 and v1 <= level <= v0
        if (
            (edge == "rising" and rising)
            or (edge == "falling" and falling)
            or (edge == "either" and (rising or falling))
        ):
            crossings.append(idx)
    return crossings


def _crossing_nominal_time(time: np.ndarray, values: np.ndarray, level: float, idx: int) -> float:
    v0 = float(values[idx])
    v1 = float(values[idx + 1])
    fraction = (level - v0) / (v1 - v0)
    return float(time[idx] + fraction * (time[idx + 1] - time[idx]))


def _as_quantity_array(value: QuantityArray | ArrayLike) -> QuantityArray:
    if isinstance(value, QuantityArray):
        return value
    return QuantityArray.constant(value)


def _as_time(time: ArrayLike, expected_len: int) -> np.ndarray:
    arr = np.asarray(time, dtype=float)
    if arr.ndim != 1 or arr.size != expected_len:
        raise ValueError("time must be a 1-D array matching the waveform length.")
    if not np.all(np.isfinite(arr)):
        raise ValueError("time must contain only finite values.")
    if np.any(np.diff(arr) <= 0.0):
        raise ValueError("time must be strictly increasing.")
    return arr


def _resolve_time_axis(
    time: ArrayLike | None, axis: WaveformAxis | None, expected_len: int
) -> np.ndarray:
    if time is not None:
        return _as_time(time, expected_len)
    if axis is None or axis.sample_interval_s is None:
        raise TimingMeasurementError(
            "Timing measurands require an explicit time axis or sample interval."
        )
    idx = np.arange(expected_len, dtype=float)
    return (idx - axis.reference) * axis.sample_interval_s + axis.origin_s


def _default_level(values: np.ndarray) -> float:
    return 0.5 * (float(np.nanmin(values)) + float(np.nanmax(values)))


def _fractional_levels(values: np.ndarray, low: float, high: float) -> tuple[float, float]:
    if not 0.0 <= low < high <= 1.0:
        raise ValueError("low/high fractions must satisfy 0 <= low < high <= 1.")
    v_min = float(np.nanmin(values))
    v_max = float(np.nanmax(values))
    span = v_max - v_min
    if span <= 0.0:
        raise TimingMeasurementError("Rise/fall time requires a non-constant waveform.")
    return v_min + low * span, v_min + high * span


def _shared_provenance(*provenances: object) -> object:
    filtered = [p for p in provenances if isinstance(p, ResultProvenance)]
    if filtered and all(p == filtered[0] for p in filtered):
        return filtered[0]
    if filtered:
        return ResultProvenance.current(
            data_origin=filtered[0].data_origin,
            evidence_purpose=filtered[0].evidence_purpose,
            provenance_complete=False,
        )
    return None


def _timing_source_key(model: TimingUncertaintyModel, registry: AtomRegistry) -> str:
    if model.source_key:
        return model.source_key
    # Deterministic fallback for callers that do not provide an acquisition key.
    # It is intentionally generic, so independent acquisitions do not appear
    # correlated unless they share a registry and explicit model context.
    return "timing:unspecified_source"
