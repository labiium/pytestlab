"""JCGM 102 (GUM Supplement 2): multivariate and complex measurands.

Because every :class:`Quantity` carries an exact gradient over the shared atom
space, the cross-covariance of two output quantities is

    Cov(Y_a, Y_b) = Σ_i Σ_j (∂Y_a/∂X_i)(∂Y_b/∂X_j) Cov(X_i, X_j)

so the output covariance matrix ``Σ_Y = J Σ_X Jᵀ`` is obtained directly from the
stored gradients. A covariance matrix can also be imported (correlated inputs)
by minting unit atoms and mixing them with the Cholesky factor.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from . import functions as fn
from .atoms import AtomRegistry
from .atoms import default_registry
from .quantity import Quantity


def covariance_between(a: Quantity, b: Quantity) -> float:
    """Cross-covariance of two quantities sharing an atom registry."""

    if a.registry is not b.registry:
        raise ValueError("covariance is only defined for quantities sharing a registry.")
    reg = a.registry
    cov = 0.0
    for uid, ga in a.grad.items():
        gb = b.grad.get(uid)
        if gb:
            cov += ga * gb * reg.atoms[uid].variance
    for (p, q), c in reg._covariances.items():
        ap, aq = a.grad.get(p, 0.0), a.grad.get(q, 0.0)
        bp, bq = b.grad.get(p, 0.0), b.grad.get(q, 0.0)
        if c and (ap or aq) and (bp or bq):
            cov += (ap * bq + aq * bp) * c
    return cov


class QuantityVector:
    """A vector measurand: components sharing one atom space (JCGM 102)."""

    def __init__(self, components: Sequence[Quantity], labels: Sequence[str] | None = None):
        if not components:
            raise ValueError("QuantityVector requires at least one component.")
        reg = components[0].registry
        if any(c.registry is not reg for c in components):
            raise ValueError("all components must share one atom registry.")
        self.components = list(components)
        self.labels = list(labels) if labels else [f"y{i}" for i in range(len(components))]
        self.registry = reg

    def __len__(self) -> int:
        return len(self.components)

    def __getitem__(self, i: int) -> Quantity:
        return self.components[i]

    def means(self) -> np.ndarray:
        return np.array([c.nominal for c in self.components])

    def covariance_matrix(self) -> np.ndarray:
        n = len(self.components)
        cov = np.empty((n, n))
        for i in range(n):
            for j in range(i, n):
                cov[i, j] = cov[j, i] = covariance_between(self.components[i], self.components[j])
        return cov

    def correlation_matrix(self) -> np.ndarray:
        cov = self.covariance_matrix()
        d = np.sqrt(np.diag(cov))
        outer = np.outer(d, d)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.where(outer > 0, cov / outer, 0.0)
        return corr

    @classmethod
    def from_covariance(
        cls,
        means: Sequence[float],
        covariance: np.ndarray,
        *,
        labels: Sequence[str] | None = None,
        units: Sequence[str] | str = "",
        registry: AtomRegistry | None = None,
        key_prefix: str | None = None,
    ) -> "QuantityVector":
        """Build correlated quantities reproducing ``covariance`` exactly."""

        reg = registry or default_registry()
        means = np.asarray(means, dtype=float)
        cov = np.asarray(covariance, dtype=float)
        n = means.size
        if cov.shape != (n, n):
            raise ValueError("covariance must be square and match means length.")
        # Cholesky (with a jitter fallback for PSD-but-singular matrices).
        try:
            L = np.linalg.cholesky(cov)
        except np.linalg.LinAlgError:
            w, V = np.linalg.eigh(cov)
            w = np.clip(w, 0.0, None)
            L = V @ np.diag(np.sqrt(w))
        unit_list = [units] * n if isinstance(units, str) else list(units)
        labels = list(labels) if labels else [f"y{i}" for i in range(n)]
        # Mint n independent unit (std=1) atoms.
        z = [
            reg.mint(
                nominal=0.0,
                std_uncertainty=1.0,
                label=f"{labels[k]}:z",
                key=f"{key_prefix}:z{k}" if key_prefix else None,
            )
            for k in range(n)
        ]
        components = []
        for i in range(n):
            grad = {z[k].uid: float(L[i, k]) for k in range(n) if L[i, k] != 0.0}
            components.append(Quantity(float(means[i]), unit_list[i], grad, reg))
        return cls(components, labels)


class ComplexQuantity:
    """A complex measurand with correlated real and imaginary parts (JCGM 102 §6)."""

    def __init__(self, real: Quantity, imag: Quantity):
        if real.registry is not imag.registry:
            raise ValueError("real and imag parts must share an atom registry.")
        self.real = real
        self.imag = imag
        self.registry = real.registry

    @property
    def nominal(self) -> complex:
        return complex(self.real.nominal, self.imag.nominal)

    def covariance_matrix(self) -> np.ndarray:
        """2x2 covariance of (Re, Im)."""

        return QuantityVector([self.real, self.imag]).covariance_matrix()

    def __add__(self, other: "ComplexQuantity") -> "ComplexQuantity":
        return ComplexQuantity(self.real + other.real, self.imag + other.imag)

    def __sub__(self, other: "ComplexQuantity") -> "ComplexQuantity":
        return ComplexQuantity(self.real - other.real, self.imag - other.imag)

    def __mul__(self, other: "ComplexQuantity") -> "ComplexQuantity":
        # (a+bi)(c+di) = (ac - bd) + (ad + bc) i
        a, b = self.real, self.imag
        c, d = other.real, other.imag
        return ComplexQuantity(a * c - b * d, a * d + b * c)

    def magnitude(self) -> Quantity:
        return fn.sqrt(self.real * self.real + self.imag * self.imag)

    def phase(self) -> Quantity:
        return fn.atan2(self.imag, self.real)

    def __repr__(self) -> str:
        return f"ComplexQuantity({self.real.nominal}+{self.imag.nominal}j)"
