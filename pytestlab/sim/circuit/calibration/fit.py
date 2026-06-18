from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

import numpy as np

from .parameters import ParameterDeclaration
from .parameters import ParameterSet

LossFunction = Callable[[dict[str, float]], float]


@dataclass(frozen=True)
class FitResult:
    initial_values: dict[str, float]
    fitted_values: dict[str, float]
    initial_loss: float
    final_loss: float
    evaluations: int
    history: tuple[dict[str, float], ...] = field(default_factory=tuple)

    @property
    def improved(self) -> bool:
        return self.final_loss < self.initial_loss


def fit_parameters(
    parameter_set: ParameterSet,
    loss_fn: LossFunction,
    *,
    max_evaluations: int = 100,
    seed: int = 1337,
    step_fraction: float = 0.25,
) -> FitResult:
    """Deterministic bounded coordinate/random search with no scipy requirement."""

    if max_evaluations < 1:
        raise ValueError("max_evaluations must be positive")
    rng = np.random.default_rng(seed)
    free = parameter_set.free_declarations()
    current = parameter_set.bounded_values()
    current_loss = _finite_loss(loss_fn(current))
    initial = dict(current)
    initial_loss = current_loss
    history = [_history(current, current_loss)]
    evaluations = 1
    step_sizes = {decl.name: max((decl.upper - decl.lower) * step_fraction, 1e-12) for decl in free}

    while evaluations < max_evaluations and free:
        improved = False
        for decl in free:
            if evaluations >= max_evaluations:
                break
            for direction in (-1.0, 1.0):
                if evaluations >= max_evaluations:
                    break
                candidate = dict(current)
                candidate[decl.name] = decl.clamp(
                    candidate[decl.name] + direction * step_sizes[decl.name]
                )
                loss = _finite_loss(loss_fn(candidate))
                evaluations += 1
                history.append(_history(candidate, loss))
                if loss < current_loss:
                    current = candidate
                    current_loss = loss
                    improved = True
        if evaluations >= max_evaluations:
            break
        random_candidate = _random_candidate(current, free, rng)
        loss = _finite_loss(loss_fn(random_candidate))
        evaluations += 1
        history.append(_history(random_candidate, loss))
        if loss < current_loss:
            current = random_candidate
            current_loss = loss
            improved = True
        if not improved:
            for name in step_sizes:
                step_sizes[name] *= 0.5
            if max(step_sizes.values()) < 1e-12:
                break

    return FitResult(
        initial_values=initial,
        fitted_values=current,
        initial_loss=initial_loss,
        final_loss=current_loss,
        evaluations=evaluations,
        history=tuple(history),
    )


def scipy_fit_parameters(
    parameter_set: ParameterSet,
    residual_fn: Callable[[dict[str, float]], list[float] | np.ndarray],
    *,
    max_evaluations: int = 100,
) -> FitResult:
    try:
        from scipy.optimize import least_squares
    except ImportError as exc:  # pragma: no cover - depends on optional scipy absence
        raise RuntimeError("scipy is required for scipy_fit_parameters") from exc

    free = parameter_set.free_declarations()
    initial = parameter_set.bounded_values()
    x0 = np.asarray([initial[decl.name] for decl in free], dtype=float)
    lower = np.asarray([decl.lower for decl in free], dtype=float)
    upper = np.asarray([decl.upper for decl in free], dtype=float)

    def unpack(x: np.ndarray) -> dict[str, float]:
        values = dict(initial)
        for decl, value in zip(free, x, strict=False):
            values[decl.name] = float(value)
        return values

    def residuals(x: np.ndarray) -> np.ndarray:
        return np.asarray(residual_fn(unpack(x)), dtype=float)

    initial_loss = float(np.sum(residuals(x0) ** 2))
    result = least_squares(residuals, x0, bounds=(lower, upper), max_nfev=max_evaluations)
    fitted = unpack(result.x)
    final_loss = float(np.sum(residuals(result.x) ** 2))
    return FitResult(initial, fitted, initial_loss, final_loss, int(result.nfev))


def _random_candidate(
    current: dict[str, float], free: tuple[ParameterDeclaration, ...], rng: np.random.Generator
) -> dict[str, float]:
    candidate = dict(current)
    for decl in free:
        candidate[decl.name] = float(rng.uniform(decl.lower, decl.upper))
    return candidate


def _finite_loss(value: float) -> float:
    value = float(value)
    return value if math.isfinite(value) else math.inf


def _history(values: dict[str, float], loss: float) -> dict[str, float]:
    return dict(values) | {"loss": float(loss)}
