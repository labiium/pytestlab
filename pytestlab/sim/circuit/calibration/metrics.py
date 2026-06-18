from __future__ import annotations

import math
from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float
    unit: str = ""
    passed: bool | None = None
    threshold: float | None = None


def rmse(measured: Sequence[float], simulated: Sequence[float]) -> float:
    diff = _diff(measured, simulated)
    return float(np.sqrt(np.mean(diff**2)))


def mae(measured: Sequence[float], simulated: Sequence[float]) -> float:
    diff = np.abs(_diff(measured, simulated))
    return float(np.mean(diff))


def percent_error(measured: float, simulated: float) -> MetricResult:
    denom = abs(float(measured))
    value = math.inf if denom == 0 else abs(float(simulated) - float(measured)) / denom * 100.0
    return MetricResult("percent_error", value, "%")


def gain_db_error(measured_db: float, simulated_db: float) -> MetricResult:
    return MetricResult("gain_db_error", abs(float(simulated_db) - float(measured_db)), "dB")


def phase_deg_error(measured_deg: float, simulated_deg: float) -> MetricResult:
    delta = (float(simulated_deg) - float(measured_deg) + 180.0) % 360.0 - 180.0
    return MetricResult("phase_deg_error", abs(delta), "deg")


def transition_accuracy(measured: Iterable[str], simulated: Iterable[str]) -> MetricResult:
    measured_values = list(measured)
    simulated_values = list(simulated)
    if len(measured_values) != len(simulated_values):
        raise ValueError("measured and simulated transitions must have the same length")
    if not measured_values:
        raise ValueError("transition lists must not be empty")
    correct = sum(
        1 for lhs, rhs in zip(measured_values, simulated_values, strict=False) if lhs == rhs
    )
    return MetricResult("transition_accuracy", correct / len(measured_values), "ratio")


def summarize_by_split(
    rows: Iterable[tuple[str, float, float]],
) -> dict[str, dict[str, float]]:
    grouped: dict[str, tuple[list[float], list[float]]] = {}
    for split, measured, simulated in rows:
        measured_values, simulated_values = grouped.setdefault(split, ([], []))
        measured_values.append(float(measured))
        simulated_values.append(float(simulated))
    summary = {}
    for split, (measured_values, simulated_values) in grouped.items():
        summary[split] = {
            "rmse": rmse(measured_values, simulated_values),
            "mae": mae(measured_values, simulated_values),
            "count": float(len(measured_values)),
        }
    return summary


def compare_scalar(
    measured: float,
    simulated: float,
    *,
    tolerance: float | None = None,
    name: str = "scalar_error",
    unit: str = "",
) -> MetricResult:
    value = abs(float(simulated) - float(measured))
    return MetricResult(
        name,
        value,
        unit,
        passed=None if tolerance is None else value <= float(tolerance),
        threshold=tolerance,
    )


def classify_transition(
    value: float,
    *,
    high_threshold: float,
    low_threshold: float,
) -> str:
    value = float(value)
    if value >= high_threshold:
        return "PULLED_HIGH"
    if value <= low_threshold:
        return "SATURATED_LOW"
    return "INVERTING"


def transition_graph(states) -> list:
    values = list(states)
    if not values:
        return []
    if isinstance(values[0], tuple) and len(values[0]) == 2:
        regions = []
        start_x, current = values[0]
        previous_x = start_x
        for x, state in values[1:]:
            if state != current:
                regions.append(
                    {
                        "start": float(start_x),
                        "stop": float(previous_x),
                        "state": current,
                    }
                )
                start_x, current = x, state
            previous_x = x
        regions.append({"start": float(start_x), "stop": float(previous_x), "state": current})
        return regions
    graph: list[tuple[str, str]] = []
    previous: str | None = None
    for state in values:
        if previous is not None and state != previous:
            edge = (previous, state)
            if edge not in graph:
                graph.append(edge)
        previous = state
    return graph


def _diff(measured: Sequence[float], simulated: Sequence[float]) -> np.ndarray:
    measured_arr = np.asarray(measured, dtype=float)
    simulated_arr = np.asarray(simulated, dtype=float)
    if measured_arr.shape != simulated_arr.shape:
        raise ValueError("measured and simulated arrays must have the same shape")
    return simulated_arr - measured_arr


def transition_boundaries(states: Iterable[tuple[float, str]]) -> dict[str, float]:
    """Return transition boundary voltages from an ordered bias/state sweep.

    The boundary is the midpoint between adjacent sampled bias points where the
    state label changes. This is deterministic and intentionally conservative;
    denser sweeps can later replace this with interpolation without changing the
    public metric names.
    """
    ordered = sorted((float(x), str(state)) for x, state in states)
    if not ordered:
        raise ValueError("transition boundary sweep must not be empty")
    boundaries: dict[str, float] = {}
    previous_x, previous_state = ordered[0]
    for x, state in ordered[1:]:
        if state != previous_state:
            key = f"{previous_state}->{state}"
            boundaries[key] = (previous_x + x) / 2.0
        previous_x, previous_state = x, state
    return boundaries


def transition_boundary_error(
    measured: Iterable[tuple[float, str]],
    simulated: Iterable[tuple[float, str]],
    *,
    mae_threshold_v: float | None = None,
    max_threshold_v: float | None = None,
) -> list[MetricResult]:
    measured_boundaries = transition_boundaries(measured)
    simulated_boundaries = transition_boundaries(simulated)
    missing = sorted(set(measured_boundaries).symmetric_difference(simulated_boundaries))
    if missing:
        raise ValueError(f"missing transition boundary: {', '.join(missing)}")
    if not measured_boundaries:
        raise ValueError("expected at least one transition boundary")
    errors = [
        abs(simulated_boundaries[name] - measured_boundaries[name])
        for name in sorted(measured_boundaries)
    ]
    mae_value = float(np.mean(errors))
    max_value = float(np.max(errors))
    return [
        MetricResult(
            "transition_boundary_mae_v",
            mae_value,
            "V",
            passed=None if mae_threshold_v is None else mae_value <= mae_threshold_v,
            threshold=mae_threshold_v,
        ),
        MetricResult(
            "transition_boundary_max_error_v",
            max_value,
            "V",
            passed=None if max_threshold_v is None else max_value <= max_threshold_v,
            threshold=max_threshold_v,
        ),
    ]


def two_transistor_validation_metrics(
    *,
    measured_vout_v: Sequence[float],
    simulated_vout_v: Sequence[float],
    measured_current_ma: Sequence[float],
    simulated_current_ma: Sequence[float],
    measured_states: Sequence[str],
    simulated_states: Sequence[str],
    measured_bias_states: Iterable[tuple[float, str]],
    simulated_bias_states: Iterable[tuple[float, str]],
    thresholds: dict[str, float] | None = None,
) -> list[MetricResult]:
    """Return first-scope metrics for the two-transistor hardware target."""
    limits = thresholds or {}
    vout = mae(measured_vout_v, simulated_vout_v)
    current = mae(measured_current_ma, simulated_current_ma)
    state = transition_accuracy(measured_states, simulated_states).value
    results = [
        MetricResult(
            "vout_mae_v",
            vout,
            "V",
            passed=None if "vout_mae_v" not in limits else vout <= limits["vout_mae_v"],
            threshold=limits.get("vout_mae_v"),
        ),
        MetricResult(
            "supply_current_mae_ma",
            current,
            "mA",
            passed=None
            if "supply_current_mae_ma" not in limits
            else current <= limits["supply_current_mae_ma"],
            threshold=limits.get("supply_current_mae_ma"),
        ),
        MetricResult(
            "state_classification_accuracy",
            state,
            "ratio",
            passed=None
            if "state_classification_accuracy" not in limits
            else state >= limits["state_classification_accuracy"],
            threshold=limits.get("state_classification_accuracy"),
        ),
    ]
    results.extend(
        transition_boundary_error(
            measured_bias_states,
            simulated_bias_states,
            mae_threshold_v=limits.get("transition_boundary_mae_v"),
            max_threshold_v=limits.get("transition_boundary_max_error_v"),
        )
    )
    return results
