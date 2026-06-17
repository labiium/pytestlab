from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field

from ..parameters import ParameterSpec
from .sensitivity import SensitivityResult
from .sensitivity import check_parameter_sensitivity


@dataclass(frozen=True)
class FitResult:
    params: dict[str, float]
    loss: float
    iterations: int
    converged: bool
    backend: str = "coordinate_search"
    sensitivity: list[SensitivityResult] = field(default_factory=list)


def fit_parameters(
    specs: Mapping[str, ParameterSpec],
    initial: Mapping[str, float] | None,
    loss_fn: Callable[[dict[str, float]], float],
    *,
    max_iterations: int = 80,
    tolerance: float = 1e-9,
    backend: str = "coordinate_search",
) -> FitResult:
    if backend == "scipy":
        return _fit_with_scipy(specs, initial, loss_fn, max_iterations=max_iterations, tolerance=tolerance)
    if backend != "coordinate_search":
        raise ValueError(f"unsupported fitter backend: {backend}")
    params = {name: float((initial or {}).get(name, spec.nominal)) for name, spec in specs.items()}
    params = {name: specs[name].clamp(value) for name, value in params.items()}
    best = float(loss_fn(dict(params)))
    step = {
        name: max(abs(spec.max_value - spec.min_value) * 0.25, 1e-12)
        if spec.min_value is not None and spec.max_value is not None
        else max(abs(params[name]) * 0.25, 1.0)
        for name, spec in specs.items()
        if spec.free
    }
    converged = False
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        iterations = iteration
        improved = False
        for name, delta in list(step.items()):
            for sign in (1.0, -1.0):
                candidate = dict(params)
                candidate[name] = specs[name].clamp(params[name] + sign * delta)
                loss = float(loss_fn(candidate))
                if loss + tolerance < best:
                    params, best, improved = candidate, loss, True
        if not improved:
            step = {name: value * 0.5 for name, value in step.items()}
            if all(value <= tolerance for value in step.values()):
                converged = True
                break
    sensitivity = check_parameter_sensitivity(specs, params, loss_fn, min_observable_delta=tolerance)
    return FitResult(params=params, loss=best, iterations=iterations, converged=converged, sensitivity=sensitivity)


def _fit_with_scipy(specs, initial, loss_fn, *, max_iterations: int, tolerance: float) -> FitResult:
    try:
        from scipy.optimize import minimize  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("scipy fitter backend requires scipy; use coordinate_search otherwise") from exc
    names = [name for name, spec in specs.items() if spec.free]
    fixed = {name: float((initial or {}).get(name, spec.nominal)) for name, spec in specs.items() if not spec.free}
    x0 = [float((initial or {}).get(name, specs[name].nominal)) for name in names]
    bounds = [(specs[name].min_value, specs[name].max_value) for name in names]

    def objective(x):
        params = dict(fixed)
        params.update({name: float(value) for name, value in zip(names, x, strict=True)})
        return float(loss_fn(params))

    result = minimize(objective, x0, method="Nelder-Mead", bounds=bounds, options={"maxiter": max_iterations, "xatol": tolerance, "fatol": tolerance})
    params = dict(fixed)
    params.update({name: float(value) for name, value in zip(names, result.x, strict=True)})
    sensitivity = check_parameter_sensitivity(specs, params, loss_fn, min_observable_delta=tolerance)
    return FitResult(params=params, loss=float(result.fun), iterations=int(result.nit), converged=bool(result.success), backend="scipy", sensitivity=sensitivity)
