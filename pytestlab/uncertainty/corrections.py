"""Systematic-error corrections as a first-class GUM operation (§3.2.3).

A :class:`Correction` represents a known systematic effect that is removed by
shifting the estimate (``y → y + delta``) while contributing its own standard
uncertainty ``u(delta)`` as a Type B atom. This makes "all recognized
significant systematic effects corrected, residual doubt quantified" an explicit
and auditable step rather than something buried in ad-hoc code.
"""

from __future__ import annotations

from dataclasses import dataclass

from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import Kind
from .atoms import divisor_for
from .quantity import Quantity


@dataclass
class Correction:
    """A known systematic correction with its own standard uncertainty."""

    label: str
    delta: float
    u: float = 0.0
    unit: str | None = None
    distribution: Distribution = Distribution.NORMAL
    coverage_factor: float = 1.0
    degrees_of_freedom: float | None = None
    source: str | None = None
    key: str | None = None

    def as_quantity(self, registry: AtomRegistry, unit: str | None = None) -> Quantity:
        unit = unit if unit is not None else (self.unit or "")
        grad: dict[str, float] = {}
        std = abs(self.u) / divisor_for(self.distribution, self.coverage_factor)
        if std:
            atom = registry.mint(
                nominal=0.0,
                std_uncertainty=std,
                label=self.label,
                unit=unit,
                distribution=self.distribution,
                degrees_of_freedom=self.degrees_of_freedom,
                kind=Kind.TYPE_B,
                source=self.source,
                key=self.key,
            )
            grad[atom.uid] = 1.0
        return Quantity(self.delta, unit, grad, registry)

    def apply(self, quantity: Quantity) -> Quantity:
        """Return ``quantity + delta`` carrying the correction's uncertainty."""

        return quantity + self.as_quantity(quantity.registry, quantity.unit)


def apply_correction(
    quantity: Quantity,
    delta: float,
    u: float = 0.0,
    *,
    label: str = "correction",
    distribution: Distribution = Distribution.NORMAL,
    coverage_factor: float = 1.0,
    degrees_of_freedom: float | None = None,
    source: str | None = None,
    key: str | None = None,
) -> Quantity:
    """Convenience wrapper applying a single :class:`Correction`."""

    return Correction(
        label=label,
        delta=delta,
        u=u,
        unit=quantity.unit,
        distribution=distribution,
        coverage_factor=coverage_factor,
        degrees_of_freedom=degrees_of_freedom,
        source=source,
        key=key,
    ).apply(quantity)
