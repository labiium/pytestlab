"""GUM §7 uncertainty budget and reporting.

Builds an auditable per-atom contribution table from a :class:`Quantity`,
computes the Welch–Satterthwaite effective degrees of freedom, expanded
uncertainty, and a coverage interval, and renders a report with GUM §7.2.6
significant-figure rounding.
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:  # pragma: no cover
    from .quantity import Quantity

_SCIPY_STATS: Any | None
try:  # pragma: no cover - exercised when optional dependency is installed
    _SCIPY_STATS = importlib.import_module("scipy.stats")
except Exception:  # pragma: no cover
    _SCIPY_STATS = None


def _scipy_stats() -> Any | None:
    global _SCIPY_STATS
    if _SCIPY_STATS is None:
        try:
            _SCIPY_STATS = importlib.import_module("scipy.stats")
        except Exception:
            return None
    return _SCIPY_STATS


@dataclass
class BudgetEntry:
    """One row of the GUM §7 uncertainty budget."""

    uid: str
    label: str
    sensitivity: float  # c_i = ∂Y/∂X_i
    input_uncertainty: float  # u(x_i)
    contribution: float  # |c_i| u(x_i)
    unit: str | None
    kind: str
    distribution: str
    degrees_of_freedom: float | None
    source: str | None

    @property
    def variance_contribution(self) -> float:
        return self.contribution**2


@dataclass
class UncertaintyBudget:
    """Combined standard uncertainty plus the auditable component table."""

    nominal: float
    unit: str
    combined_standard_uncertainty: float
    entries: list[BudgetEntry]
    has_correlations: bool = False

    @classmethod
    def from_quantity(cls, quantity: Quantity) -> UncertaintyBudget:
        reg = quantity.registry
        entries: list[BudgetEntry] = []
        for uid, c in quantity.grad.items():
            atom = reg.atoms[uid]
            entries.append(
                BudgetEntry(
                    uid=uid,
                    label=atom.label,
                    sensitivity=c,
                    input_uncertainty=atom.std_uncertainty,
                    contribution=abs(c) * atom.std_uncertainty,
                    unit=atom.unit,
                    kind=atom.kind.value,
                    distribution=atom.distribution.value,
                    degrees_of_freedom=atom.degrees_of_freedom,
                    source=atom.source,
                )
            )
        entries.sort(key=lambda e: e.contribution, reverse=True)
        has_corr = any(quantity.grad.get(a) and quantity.grad.get(b) for (a, b) in reg._covariances)
        return cls(
            nominal=quantity.nominal,
            unit=quantity.unit,
            combined_standard_uncertainty=quantity.u,
            entries=entries,
            has_correlations=has_corr,
        )

    @property
    def effective_degrees_of_freedom(self) -> float | None:
        """Welch–Satterthwaite ν_eff (valid under the independence approximation)."""

        u_c = self.combined_standard_uncertainty
        if u_c == 0:
            return None
        denom = 0.0
        for entry in self.entries:
            if entry.degrees_of_freedom:
                denom += entry.contribution**4 / entry.degrees_of_freedom
        return (u_c**4 / denom) if denom else None

    def coverage_factor_for(self, confidence: float = 0.95) -> float:
        if not 0 < confidence < 1:
            raise ValueError("confidence must be between 0 and 1.")
        tail = (1.0 + confidence) / 2.0
        dof = self.effective_degrees_of_freedom
        stats = _scipy_stats()
        if stats is not None:
            if dof is not None:
                return float(stats.t.ppf(tail, dof))
            return float(stats.norm.ppf(tail))
        if math.isclose(confidence, 0.95, abs_tol=0.01):
            return 2.0
        raise RuntimeError("scipy is required for non-default coverage factors.")

    def expanded_uncertainty(
        self, coverage_factor: float | None = None, *, confidence: float | None = None
    ) -> float:
        k = (
            self.coverage_factor_for(confidence)
            if confidence is not None
            else (coverage_factor or 2.0)
        )
        return self.combined_standard_uncertainty * k

    def coverage_interval(self, *, confidence: float = 0.95) -> tuple[float, float]:
        u_exp = self.expanded_uncertainty(confidence=confidence)
        return (self.nominal - u_exp, self.nominal + u_exp)

    def percentage_contributions(self) -> dict[str, float]:
        total = sum(e.variance_contribution for e in self.entries)
        if total == 0:
            return {e.uid: 0.0 for e in self.entries}
        return {e.uid: 100.0 * e.variance_contribution / total for e in self.entries}

    def report(self, *, confidence: float = 0.95) -> UncertaintyReport:
        return UncertaintyReport(self, confidence=confidence)


def round_to_significant(value: float, sig: int) -> float:
    if value == 0 or not math.isfinite(value):
        return value
    digits = sig - 1 - math.floor(math.log10(abs(value)))
    return round(value, digits)


@dataclass
class UncertaintyReport:
    """A GUM §7-style rendering with significant-figure rounding."""

    budget: UncertaintyBudget
    confidence: float = 0.95
    uncertainty_sig_figs: int = 2

    def _rounded(self) -> tuple[float, float, float]:
        u = self.budget.combined_standard_uncertainty
        u_round = round_to_significant(u, self.uncertainty_sig_figs)
        # Round y to the same decimal place as u.
        if u_round and math.isfinite(u_round):
            decimals = self.uncertainty_sig_figs - 1 - math.floor(math.log10(abs(u_round)))
            y_round = round(self.budget.nominal, decimals)
        else:
            y_round = self.budget.nominal
        return (
            y_round,
            u_round,
            round_to_significant(
                self.budget.expanded_uncertainty(confidence=self.confidence),
                self.uncertainty_sig_figs,
            ),
        )

    def __str__(self) -> str:
        y, u, U = self._rounded()
        b = self.budget
        dof = b.effective_degrees_of_freedom
        k = b.coverage_factor_for(self.confidence)
        unit = f" {b.unit}" if b.unit else ""
        pct = b.percentage_contributions()
        lines = [
            f"y  = {y}{unit}",
            f"u_c = {u}{unit}",
            f"nu_eff = {'inf' if dof is None else f'{dof:.1f}'}",
            f"k({self.confidence:.0%}) = {k:.3f}    U = {U}{unit}",
            f"coverage interval = [{y - U}, {y + U}]{unit}"
            + ("  (has correlations)" if b.has_correlations else ""),
            "budget:",
        ]
        for e in b.entries:
            lines.append(
                f"  {e.label:<24} c={e.sensitivity:.4g}  u(x)={e.input_uncertainty:.4g}"
                f"  u_i={e.contribution:.4g}  {pct[e.uid]:5.1f}%  [{e.kind}, {e.distribution}]"
            )
        return "\n".join(lines)
