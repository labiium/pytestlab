"""Validation of the GUM analytical result against Monte Carlo (JCGM 101 §8).

The GUM (first-order) result is accepted when its 95 % coverage-interval
endpoints agree with the Monte Carlo endpoints to the numerical tolerance ``δ``
associated with reporting ``u`` to the requested number of significant digits.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .montecarlo import MonteCarloResult
from .montecarlo import monte_carlo
from .quantity import Quantity


@dataclass
class ValidationReport:
    """Result of the GUM-vs-MC comparison (JCGM 101 §8.2)."""

    validated: bool
    tolerance: float
    d_low: float
    d_high: float
    gum_interval: tuple[float, float]
    mc_interval: tuple[float, float]
    gum_u: float
    mc_u: float

    def __str__(self) -> str:
        verdict = "VALIDATED" if self.validated else "NOT validated"
        return (
            f"GUM vs MC: {verdict} (delta={self.tolerance:.3g})\n"
            f"  u: GUM={self.gum_u:.4g}  MC={self.mc_u:.4g}\n"
            f"  interval GUM={self.gum_interval}  MC={self.mc_interval}\n"
            f"  d_low={self.d_low:.3g}  d_high={self.d_high:.3g}"
        )


def numerical_tolerance(u: float, significant_digits: int = 2) -> float:
    if u == 0 or not math.isfinite(u):
        return 0.0
    digits = math.floor(math.log10(abs(u)))
    return 0.5 * 10.0 ** (digits - significant_digits + 1)


def validate(
    analytical: Quantity,
    mc: MonteCarloResult,
    *,
    significant_digits: int = 2,
    confidence: float = 0.95,
) -> ValidationReport:
    budget = analytical.budget()
    U = budget.expanded_uncertainty(confidence=confidence)
    gum_lo, gum_hi = analytical.nominal - U, analytical.nominal + U
    mc_lo, mc_hi = mc.interval
    delta = numerical_tolerance(analytical.u, significant_digits)
    d_low = abs(gum_lo - mc_lo)
    d_high = abs(gum_hi - mc_hi)
    return ValidationReport(
        validated=(d_low <= delta and d_high <= delta),
        tolerance=delta,
        d_low=d_low,
        d_high=d_high,
        gum_interval=(gum_lo, gum_hi),
        mc_interval=(mc_lo, mc_hi),
        gum_u=analytical.u,
        mc_u=mc.std,
    )


def validate_model(
    func: Callable[..., Any],
    inputs: Mapping[str, Quantity],
    *,
    significant_digits: int = 2,
    confidence: float = 0.95,
    samples: int = 1_000_000,
    seed: int | None = None,
) -> ValidationReport:
    """Validate the analytical propagation of ``func`` against Monte Carlo."""

    analytical = func(**inputs)
    if not isinstance(analytical, Quantity):
        raise TypeError("func must return a Quantity when called with Quantity inputs.")
    mc = monte_carlo(func, inputs, samples=samples, seed=seed, confidence=confidence)
    return validate(analytical, mc, significant_digits=significant_digits, confidence=confidence)
