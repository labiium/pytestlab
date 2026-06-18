from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .parameters import ParameterSet


@dataclass(frozen=True)
class SensitivityResult:
    baseline: float
    derivatives: dict[str, float]
    observable: str = "loss"
    parameter: str = ""

    def observable_parameters(self, *, min_abs: float = 1e-12) -> dict[str, float]:
        return {name: value for name, value in self.derivatives.items() if abs(value) >= min_abs}


def finite_difference_sensitivity(
    parameter_set: ParameterSet,
    observable_fn: Callable[[dict[str, float]], float],
    *,
    step_fraction: float = 1e-4,
    observable: str = "loss",
) -> SensitivityResult:
    values = parameter_set.bounded_values()
    baseline = float(observable_fn(values))
    derivatives: dict[str, float] = {}
    for decl in parameter_set.free_declarations():
        span = max(decl.upper - decl.lower, 1.0)
        step = span * step_fraction
        plus = dict(values)
        minus = dict(values)
        plus[decl.name] = decl.clamp(values[decl.name] + step)
        minus[decl.name] = decl.clamp(values[decl.name] - step)
        plus_value = float(observable_fn(plus))
        minus_value = float(observable_fn(minus))
        denom = plus[decl.name] - minus[decl.name]
        derivatives[decl.name] = 0.0 if denom == 0 else (plus_value - minus_value) / denom
    return SensitivityResult(baseline=baseline, derivatives=derivatives, observable=observable)


def check_parameter_sensitivity(
    specs,
    values: dict[str, float],
    observable_fn: Callable[[dict[str, float]], float],
    *,
    min_observable_delta: float = 1e-12,
):
    """Compatibility helper for ParameterSpec-based callers."""

    baseline = float(observable_fn(dict(values)))
    results = []
    for name, spec in specs.items():
        if not getattr(spec, "free", True):
            continue
        current = float(values.get(name, getattr(spec, "nominal", 0.0)))
        min_value = getattr(spec, "min_value", None)
        max_value = getattr(spec, "max_value", None)
        if min_value is not None and max_value is not None:
            step = max(abs(float(max_value) - float(min_value)) * 1e-4, 1e-12)
        else:
            step = max(abs(current) * 1e-4, 1e-12)
        plus = dict(values)
        minus = dict(values)
        plus[name] = spec.clamp(current + step) if hasattr(spec, "clamp") else current + step
        minus[name] = spec.clamp(current - step) if hasattr(spec, "clamp") else current - step
        plus_value = float(observable_fn(plus))
        minus_value = float(observable_fn(minus))
        denom = plus[name] - minus[name]
        derivative = 0.0 if denom == 0 else (plus_value - minus_value) / denom
        if (
            abs(plus_value - baseline) >= min_observable_delta
            or abs(minus_value - baseline) >= min_observable_delta
        ):
            results.append(
                SensitivityResult(baseline=baseline, derivatives={name: derivative}, parameter=name)
            )
    return results
