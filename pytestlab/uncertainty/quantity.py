"""The scalar measurand value type :class:`Quantity`.

A ``Quantity`` is a first-order Taylor model of a measurand ``Y`` over the shared
atom space: it carries a ``nominal`` value, a ``unit``, and a ``gradient``
mapping each contributing atom ``uid`` to the sensitivity coefficient
``c_i = ∂Y/∂X_i``. This is GUM linearization made explicit, so correlation and
arbitrary-function propagation both fall out of the gradient:

    u_c²(Y) = Σ_i Σ_j c_i c_j Cov(X_i, X_j)          (GUM Eq. 16)

Independent atoms ⇒ diagonal covariance ⇒ root-sum-of-squares. Shared atoms or
declared off-diagonal covariance ⇒ the full correlated result.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from . import units
from .atoms import AtomRegistry
from .atoms import InfluenceQuantity
from .atoms import default_registry

if TYPE_CHECKING:  # pragma: no cover
    from .budget import UncertaintyBudget

Number = int | float


class Quantity:
    """A measurand with a nominal value, unit, and gradient over atoms."""

    __slots__ = ("nominal", "unit", "grad", "registry")

    def __init__(
        self,
        nominal: float,
        unit: str = "",
        grad: dict[str, float] | None = None,
        registry: AtomRegistry | None = None,
    ) -> None:
        self.nominal = float(nominal)
        self.unit = unit or ""
        self.grad: dict[str, float] = dict(grad or {})
        self.registry = registry or default_registry()

    # -- constructors -------------------------------------------------------
    @classmethod
    def constant(cls, value: Number, unit: str = "", registry: AtomRegistry | None = None) -> "Quantity":
        return cls(float(value), unit, {}, registry)

    @classmethod
    def from_atom(cls, atom: InfluenceQuantity, registry: AtomRegistry | None = None) -> "Quantity":
        reg = registry or default_registry()
        reg.register(atom)
        return cls(atom.nominal, atom.unit or "", {atom.uid: 1.0}, reg)

    # -- uncertainty --------------------------------------------------------
    @property
    def variance(self) -> float:
        reg = self.registry
        var = 0.0
        for uid, g in self.grad.items():
            var += g * g * reg.atoms[uid].variance
        for (a, b), cov in reg._covariances.items():
            ga = self.grad.get(a)
            gb = self.grad.get(b)
            if ga and gb:
                var += 2.0 * ga * gb * cov
        return max(var, 0.0)

    @property
    def u(self) -> float:
        """Combined standard uncertainty u_c(Y)."""

        return math.sqrt(self.variance)

    @property
    def std_dev(self) -> float:
        return self.u

    # ufloat-style short accessors
    @property
    def n(self) -> float:
        return self.nominal

    @property
    def nominal_value(self) -> float:
        return self.nominal

    @property
    def s(self) -> float:
        return self.u

    @property
    def relative_u(self) -> float:
        return abs(self.u / self.nominal) if self.nominal else math.inf

    def expanded(self, k: float = 2.0) -> float:
        return self.u * k

    def U(self, k: float = 2.0) -> float:
        return self.expanded(k)

    def budget(self) -> "UncertaintyBudget":
        from .budget import UncertaintyBudget

        return UncertaintyBudget.from_quantity(self)

    # -- low level gradient algebra ----------------------------------------
    def _combine_grads(self, other: "Quantity", ca: float, cb: float) -> dict[str, float]:
        """Return ``ca * self.grad + cb * other.grad``."""

        out: dict[str, float] = {}
        for uid, g in self.grad.items():
            out[uid] = ca * g
        for uid, g in other.grad.items():
            out[uid] = out.get(uid, 0.0) + cb * g
        return {uid: g for uid, g in out.items() if g != 0.0}

    def _scaled_grad(self, factor: float) -> dict[str, float]:
        return {uid: factor * g for uid, g in self.grad.items() if factor * g != 0.0}

    def _lift(self, other: object) -> "Quantity":
        if isinstance(other, Quantity):
            if other.registry is not self.registry:
                raise ValueError(
                    "Cannot combine quantities from different atom registries; "
                    "they would not share a correlation space."
                )
            return other
        if isinstance(other, (int, float)):
            return Quantity.constant(other, "", self.registry)
        return NotImplemented  # type: ignore[return-value]

    def _new(self, nominal: float, unit: str, grad: dict[str, float]) -> "Quantity":
        return Quantity(nominal, unit, grad, self.registry)

    # -- arithmetic ---------------------------------------------------------
    def __add__(self, other: object) -> "Quantity":
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        if self.unit and o.unit and self.unit != o.unit:
            nominal, unit = units.add_sub_nominal(self.nominal, self.unit, o.nominal, o.unit, "add")
        else:
            nominal = self.nominal + o.nominal
            unit = self.unit or o.unit
        return self._new(nominal, unit, self._combine_grads(o, 1.0, 1.0))

    __radd__ = __add__

    def __sub__(self, other: object) -> "Quantity":
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        if self.unit and o.unit and self.unit != o.unit:
            nominal, unit = units.add_sub_nominal(self.nominal, self.unit, o.nominal, o.unit, "sub")
        else:
            nominal = self.nominal - o.nominal
            unit = self.unit or o.unit
        return self._new(nominal, unit, self._combine_grads(o, 1.0, -1.0))

    def __rsub__(self, other: object) -> "Quantity":
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        return o.__sub__(self)

    def __mul__(self, other: object) -> "Quantity":
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        nominal, unit, scale = units.product_nominal(
            self.nominal, self.unit, o.nominal, o.unit, "mul"
        )
        grad = self._combine_grads(o, o.nominal * scale, self.nominal * scale)
        return self._new(nominal, unit, grad)

    __rmul__ = __mul__

    def __truediv__(self, other: object) -> "Quantity":
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        nominal, unit, scale = units.product_nominal(
            self.nominal, self.unit, o.nominal, o.unit, "truediv"
        )
        # d(a/b) = (1/b) da - (a/b^2) db, scaled for unit reconciliation
        grad = self._combine_grads(
            o, scale / o.nominal, -scale * self.nominal / (o.nominal**2)
        )
        return self._new(nominal, unit, grad)

    def __rtruediv__(self, other: object) -> "Quantity":
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        return o.__truediv__(self)

    def __neg__(self) -> "Quantity":
        return self._new(-self.nominal, self.unit, self._scaled_grad(-1.0))

    def __pos__(self) -> "Quantity":
        return self

    def __pow__(self, power: object) -> "Quantity":
        if isinstance(power, Quantity) and power.grad:
            # a**b = exp(b ln a): d = a**b * (b/a da + ln a db)
            if not units.is_dimensionless(self.unit):
                raise units.UnitCompatibilityError(
                    "Exponent with an uncertain power requires a dimensionless base."
                )
            p = power.nominal
            nominal = self.nominal**p
            da = p / self.nominal if self.nominal else 0.0
            db = math.log(self.nominal) if self.nominal > 0 else 0.0
            grad = self._combine_grads(power, nominal * da, nominal * db)
            return self._new(nominal, "", grad)
        p = float(power.nominal if isinstance(power, Quantity) else power)
        nominal = self.nominal**p
        unit = self._pow_unit(p)
        factor = p * (self.nominal ** (p - 1.0)) if self.nominal != 0 or p >= 1 else 0.0
        return self._new(nominal, unit, self._scaled_grad(factor))

    def _pow_unit(self, p: float) -> str:
        if not self.unit or p == 1.0:
            return self.unit
        if p == 0.0:
            return ""
        return f"{self.unit}**{p:g}"

    # -- conversions --------------------------------------------------------
    def __float__(self) -> float:
        return float(self.nominal)

    def __format__(self, spec: str) -> str:
        return format(self.nominal, spec)

    def __repr__(self) -> str:
        return f"Quantity({self.nominal!r}, {self.unit!r}, u={self.u:.6g})"

    def __str__(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.nominal} +/- {self.u}{unit}"

    def to_ufloat(self):  # pragma: no cover - optional interop
        from uncertainties import ufloat

        return ufloat(self.nominal, self.u)

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        """Serialize nominal, unit, gradient, referenced atoms and covariances."""

        from .atoms import Distribution, Kind  # noqa: F401

        reg = self.registry
        atoms = {}
        for uid in self.grad:
            a = reg.atoms[uid]
            atoms[uid] = {
                "label": a.label,
                "nominal": a.nominal,
                "std_uncertainty": a.std_uncertainty,
                "unit": a.unit,
                "distribution": a.distribution.value,
                "degrees_of_freedom": a.degrees_of_freedom,
                "kind": a.kind.value,
                "source": a.source,
            }
        covariances = [
            [a, b, cov]
            for (a, b), cov in reg._covariances.items()
            if a in self.grad and b in self.grad
        ]
        return {
            "nominal": self.nominal,
            "unit": self.unit,
            "standard_uncertainty": self.u,
            "grad": dict(self.grad),
            "atoms": atoms,
            "covariances": covariances,
        }

    @classmethod
    def from_dict(cls, data: dict, registry: AtomRegistry | None = None) -> "Quantity":
        from .atoms import Distribution, InfluenceQuantity, Kind

        reg = registry or AtomRegistry()
        for uid, a in data.get("atoms", {}).items():
            reg.register(
                InfluenceQuantity(
                    uid=uid,
                    label=a["label"],
                    nominal=a["nominal"],
                    std_uncertainty=a["std_uncertainty"],
                    unit=a.get("unit"),
                    distribution=Distribution(a.get("distribution", "normal")),
                    degrees_of_freedom=a.get("degrees_of_freedom"),
                    kind=Kind(a.get("kind", "type_b")),
                    source=a.get("source"),
                )
            )
        for a, b, cov in data.get("covariances", []):
            reg.set_covariance(a, b, cov)
        grad = {uid: float(g) for uid, g in data.get("grad", {}).items()}
        return cls(data["nominal"], data.get("unit", ""), grad, reg)
