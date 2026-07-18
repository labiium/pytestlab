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
import numbers
import operator
import re
import warnings
from dataclasses import dataclass
from html import escape
from types import NotImplementedType
from typing import TYPE_CHECKING
from typing import Any

from . import units
from .atoms import AtomRegistry
from .atoms import InfluenceQuantity
from .atoms import default_registry

if TYPE_CHECKING:  # pragma: no cover
    from .budget import UncertaintyBudget

Number = int | float


class CorrelationComponentWarning(UserWarning):
    """Diagonal-only uncertainty components are incomplete for correlated quantities."""


class NominalOnlyDecisionWarning(UserWarning):
    """A decision helper used a non-report-grade nominal-only quantity."""


@dataclass(frozen=True)
class QuantityComparison:
    """Uncertainty-aware comparison result for two quantities or a quantity and limit."""

    left_nominal: float
    right_nominal: float
    delta: float
    combined_standard_uncertainty: float
    coverage_factor: float
    en_ratio: float
    consistent: bool
    direction: str
    unit: str


class Quantity:
    """A measurand with a nominal value, unit, and gradient over atoms."""

    __array_priority__ = 1000

    __slots__ = (
        "nominal",
        "unit",
        "grad",
        "registry",
        "measurement_model",
        "provenance",
        "dof_method",
    )

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
        self.measurement_model = None
        self.provenance = None
        self.dof_method = None

    # -- constructors -------------------------------------------------------
    @classmethod
    def constant(
        cls, value: Number, unit: str = "", registry: AtomRegistry | None = None
    ) -> Quantity:
        return cls(float(value), unit, {}, registry)

    @classmethod
    def from_atom(cls, atom: InfluenceQuantity, registry: AtomRegistry | None = None) -> Quantity:
        reg = registry or default_registry()
        reg.register(atom)
        return cls(atom.nominal, atom.unit or "", {atom.uid: 1.0}, reg)

    # -- uncertainty --------------------------------------------------------
    @property
    def variance(self) -> float:
        # Cost scales with this quantity's own complexity (k atoms -> O(k^2)
        # covariance lookups), independent of the registry's total size.
        reg = self.registry
        atoms = reg.atoms
        diagonal = 0.0
        cross = 0.0
        items = list(self.grad.items())
        for i, (uid, g) in enumerate(items):
            diagonal += g * g * atoms[uid].variance
            if reg.has_correlations:
                for uid2, g2 in items[i + 1 :]:
                    cov = reg.covariance(uid, uid2)
                    if cov:
                        cross += 2.0 * g * g2 * cov
        var = diagonal + cross
        if var < 0.0:
            # A meaningfully negative variance means the declared correlations
            # form a non-positive-semidefinite covariance matrix (a data error);
            # a tiny negative is floating-point noise and is clamped to zero.
            if var < -1e-9 * max(diagonal, 1e-300):
                raise ValueError(
                    "Combined variance is negative: the declared correlations are not "
                    "positive semi-definite. Check set_correlation()/set_covariance() inputs."
                )
            return 0.0
        return var

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

    def budget(self) -> UncertaintyBudget:
        from .budget import UncertaintyBudget

        return UncertaintyBudget.from_quantity(self)

    @property
    def is_report_grade(self) -> bool:
        """Whether this result currently passes PyTestLab's report-grade gates."""

        from .metrology import is_report_grade

        return is_report_grade(self)

    def report_grade_blockers(self) -> list[str]:
        """Return human-readable reasons this value must not be treated as report-grade."""

        from .metrology import report_grade_blockers

        return report_grade_blockers(self)

    # -- uncertainty-aware decisions -----------------------------------------
    def compare(self, other: object, *, k: float = 2.0) -> QuantityComparison:
        """Compare against another value using expanded uncertainty ``k * u_c``.

        Rich comparison operators use nominal values. This method is the auditable,
        uncertainty-aware alternative for measurement decisions. Scalars are treated
        as exact thresholds in this quantity's unit.
        """

        if k <= 0.0 or not math.isfinite(k):
            raise ValueError("coverage factor k must be positive and finite.")
        right_nominal, right_u, unit, delta, combined_u = self._comparison_terms(other)
        self._warn_if_nominal_only_decision(other)
        expanded = k * combined_u
        en_ratio = (
            math.inf
            if expanded == 0.0 and delta != 0.0
            else (0.0 if expanded == 0.0 else abs(delta) / expanded)
        )
        direction = "consistent"
        if delta > expanded:
            direction = "above"
        elif delta < -expanded:
            direction = "below"
        return QuantityComparison(
            left_nominal=self.nominal,
            right_nominal=right_nominal,
            delta=delta,
            combined_standard_uncertainty=combined_u,
            coverage_factor=k,
            en_ratio=en_ratio,
            consistent=abs(delta) <= expanded,
            direction=direction,
            unit=unit,
        )

    def consistent_with(self, other: object, *, k: float = 2.0) -> bool:
        """Return whether ``self`` agrees with ``other`` within ``k`` standard uncertainties."""

        return self.compare(other, k=k).consistent

    def en_ratio(self, other: object, *, k: float = 2.0) -> float:
        """Return ``abs(delta) / (k * combined_standard_uncertainty)``."""

        return self.compare(other, k=k).en_ratio

    def exceeds(self, threshold: object, *, k: float = 2.0) -> bool:
        """True only when the lower expanded-uncertainty bound exceeds ``threshold``."""

        comparison = self.compare(threshold, k=k)
        return comparison.delta > k * comparison.combined_standard_uncertainty

    def below(self, threshold: object, *, k: float = 2.0) -> bool:
        """True only when the upper expanded-uncertainty bound is below ``threshold``."""

        comparison = self.compare(threshold, k=k)
        return comparison.delta < -k * comparison.combined_standard_uncertainty

    def within(self, lower: object, upper: object, *, k: float = 2.0) -> bool:
        """True when the expanded interval is strictly inside ``[lower, upper]``."""

        return self.exceeds(lower, k=k) and self.below(upper, k=k)

    def _comparison_terms(self, other: object) -> tuple[float, float, str, float, float]:
        if isinstance(other, Quantity):
            right_nominal = units.convert_units(other.nominal, other.unit, self.unit)
            right_u = abs(units.convert_units(other.u, other.unit, self.unit))
            if other.registry is self.registry:
                delta_q = self - other
                return right_nominal, right_u, delta_q.unit, delta_q.nominal, delta_q.u
            return (
                right_nominal,
                right_u,
                self.unit,
                self.nominal - right_nominal,
                math.hypot(self.u, right_u),
            )
        if isinstance(other, numbers.Real):
            right_nominal = float(other)
            return right_nominal, 0.0, self.unit, self.nominal - right_nominal, self.u
        raise TypeError(
            "Quantity comparison expects another Quantity or a real scalar threshold. "
            "Use q.n for routine nominal-only control flow or q.compare(...) for an "
            "uncertainty-aware decision."
        )

    def _warn_if_nominal_only_decision(self, other: object) -> None:
        blockers: list[str] = []
        if self._is_nominal_only_non_report_grade():
            blockers.append("left operand")
        if isinstance(other, Quantity) and other._is_nominal_only_non_report_grade():
            blockers.append("right operand")
        if blockers:
            warnings.warn(
                "Decision made using a nominal-only non-report-grade Quantity "
                f"({', '.join(blockers)}) with no uncertainty metadata. The verdict is "
                "not guard-banded; inspect q.report_grade_blockers().",
                NominalOnlyDecisionWarning,
                stacklevel=3,
            )

    def _is_nominal_only_non_report_grade(self) -> bool:
        if self.u != 0.0:
            return False
        try:
            return bool(self.report_grade_blockers())
        except Exception:  # pragma: no cover - reportability checks are defensive
            return False

    # -- low level gradient algebra ----------------------------------------
    def _combine_grads(self, other: Quantity, ca: float, cb: float) -> dict[str, float]:
        """Return ``ca * self.grad + cb * other.grad``."""

        out: dict[str, float] = {}
        for uid, g in self.grad.items():
            out[uid] = ca * g
        for uid, g in other.grad.items():
            out[uid] = out.get(uid, 0.0) + cb * g
        return {uid: g for uid, g in out.items() if g != 0.0}

    def _scaled_grad(self, factor: float) -> dict[str, float]:
        return {uid: factor * g for uid, g in self.grad.items() if factor * g != 0.0}

    def _lift(self, other: object) -> Quantity:
        if isinstance(other, Quantity):
            if other.registry is not self.registry:
                raise ValueError(
                    "Cannot combine quantities from different atom registries; "
                    "they would not share a correlation space."
                )
            return other
        if isinstance(other, numbers.Real):
            return Quantity.constant(float(other), "", self.registry)
        return NotImplemented

    def _new(
        self,
        nominal: float,
        unit: str,
        grad: dict[str, float],
        *operands: Quantity,
    ) -> Quantity:
        q = Quantity(nominal, unit, grad, self.registry)
        # Arithmetic creates a derived result.  Preserve provenance/dof lineage so
        # technical records are not silently lost, but require callers to attach a
        # new MeasurementModel before claiming report-grade status.
        q.provenance = self._derived_provenance(*operands)
        q.dof_method = self._derived_dof_method(*operands)
        return q

    def _derived_dof_method(self, *operands: Quantity) -> object:
        methods = [self.dof_method, *(operand.dof_method for operand in operands)]
        non_null = [method for method in methods if method is not None]
        if not non_null:
            return None
        first = non_null[0]
        return first if all(method == first for method in non_null) else None

    def _derived_provenance(self, *operands: Quantity) -> object:
        provenances = [
            provenance
            for provenance in [self.provenance, *(operand.provenance for operand in operands)]
            if provenance is not None
        ]
        if not provenances:
            return None
        from .metrology import DataOrigin
        from .metrology import EvidencePurpose
        from .metrology import ResultProvenance

        origins = [
            provenance.data_origin
            for provenance in provenances
            if isinstance(provenance, ResultProvenance)
        ]
        purposes = [
            provenance.evidence_purpose
            for provenance in provenances
            if isinstance(provenance, ResultProvenance)
        ]
        data_origin = (
            origins[0]
            if origins and all(origin == origins[0] for origin in origins)
            else DataOrigin.UNKNOWN
        )
        evidence_purpose = (
            purposes[0]
            if purposes and all(purpose == purposes[0] for purpose in purposes)
            else EvidencePurpose.SOFTWARE_VALIDATION
        )
        merged = ResultProvenance.current(
            data_origin=data_origin,
            evidence_purpose=evidence_purpose,
            provenance_complete=False,
        )
        merged.amendments.append(
            {
                "operation": "derived_arithmetic",
                "provenance_complete": False,
                "derived_from": [
                    provenance.model_dump(mode="json")
                    if hasattr(provenance, "model_dump")
                    else repr(provenance)
                    for provenance in provenances
                ],
            }
        )
        return merged

    # -- arithmetic ---------------------------------------------------------
    def __add__(self, other: object) -> Quantity:
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        if self.unit and o.unit and self.unit != o.unit:
            nominal, unit = units.add_sub_nominal(self.nominal, self.unit, o.nominal, o.unit, "add")
            right_scale = units.convert_units(1.0, o.unit, self.unit)
            grad = self._combine_grads(o, 1.0, right_scale)
        else:
            nominal = self.nominal + o.nominal
            unit = self.unit or o.unit
            grad = self._combine_grads(o, 1.0, 1.0)
        return self._new(nominal, unit, grad, o)

    __radd__ = __add__

    def __sub__(self, other: object) -> Quantity:
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        if self.unit and o.unit and self.unit != o.unit:
            nominal, unit = units.add_sub_nominal(self.nominal, self.unit, o.nominal, o.unit, "sub")
            right_scale = units.convert_units(1.0, o.unit, self.unit)
            grad = self._combine_grads(o, 1.0, -right_scale)
        else:
            nominal = self.nominal - o.nominal
            unit = self.unit or o.unit
            grad = self._combine_grads(o, 1.0, -1.0)
        return self._new(nominal, unit, grad, o)

    def __rsub__(self, other: object) -> Quantity:
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        return o.__sub__(self)

    def __mul__(self, other: object) -> Quantity:
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        nominal, unit, scale = units.product_nominal(
            self.nominal, self.unit, o.nominal, o.unit, "mul"
        )
        grad = self._combine_grads(o, o.nominal * scale, self.nominal * scale)
        return self._new(nominal, unit, grad, o)

    __rmul__ = __mul__

    def __truediv__(self, other: object) -> Quantity:
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        nominal, unit, scale = units.product_nominal(
            self.nominal, self.unit, o.nominal, o.unit, "truediv"
        )
        # d(a/b) = (1/b) da - (a/b^2) db, scaled for unit reconciliation
        grad = self._combine_grads(o, scale / o.nominal, -scale * self.nominal / (o.nominal**2))
        return self._new(nominal, unit, grad, o)

    def __rtruediv__(self, other: object) -> Quantity:
        o = self._lift(other)
        if o is NotImplemented:
            return NotImplemented
        return o.__truediv__(self)

    def __neg__(self) -> Quantity:
        return self._new(-self.nominal, self.unit, self._scaled_grad(-1.0))

    def __pos__(self) -> Quantity:
        return self

    def __abs__(self) -> Quantity:
        factor = 1.0 if self.nominal >= 0.0 else -1.0
        return self._new(abs(self.nominal), self.unit, self._scaled_grad(factor))

    def __pow__(self, power: object) -> Quantity:
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
            return self._new(nominal, "", grad, power)
        p = float(power.nominal) if isinstance(power, Quantity) else float(power)  # type: ignore[arg-type]
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

    # -- comparisons ---------------------------------------------------------
    def _nominal_comparison_value(self, other: object) -> float | NotImplementedType:
        """Return ``other`` expressed as a nominal value in this quantity's unit."""

        if isinstance(other, Quantity):
            if bool(self.unit) != bool(other.unit):
                raise units.UnitCompatibilityError(
                    f"Incompatible units: {self.unit!r} and {other.unit!r}"
                )
            return units.convert_units(other.nominal, other.unit, self.unit)
        if isinstance(other, numbers.Real):
            # Bare scalars are interpreted in this quantity's unit. This mirrors
            # arithmetic with scalars and keeps ordinary Python control flow concise.
            return float(other)
        return NotImplemented

    def same_representation(self, other: object) -> bool:
        """Return whether two quantities have the same scalar representation.

        Unlike ``==``, which compares unit-converted nominal values, this checks the
        uncertainty engine's scalar identity fields: nominal value, unit spelling,
        gradient, and correlation registry identity. It does not compare provenance
        or measurement-model metadata.
        """

        if not isinstance(other, Quantity):
            return False
        return (
            self.nominal == other.nominal
            and self.unit == other.unit
            and self.grad == other.grad
            and self.registry is other.registry
        )

    def __eq__(self, other: object) -> bool:
        right = self._nominal_comparison_value(other)
        if right is NotImplemented:
            return NotImplemented
        return self.nominal == right

    def __ne__(self, other: object) -> bool:
        equal = self.__eq__(other)
        if equal is NotImplemented:
            return NotImplemented
        return not equal

    __hash__ = None

    def __lt__(self, other: object) -> bool:
        right = self._nominal_comparison_value(other)
        if right is NotImplemented:
            return NotImplemented
        return self.nominal < right

    def __le__(self, other: object) -> bool:
        right = self._nominal_comparison_value(other)
        if right is NotImplemented:
            return NotImplemented
        return self.nominal <= right

    def __gt__(self, other: object) -> bool:
        right = self._nominal_comparison_value(other)
        if right is NotImplemented:
            return NotImplemented
        return self.nominal > right

    def __ge__(self, other: object) -> bool:
        right = self._nominal_comparison_value(other)
        if right is NotImplemented:
            return NotImplemented
        return self.nominal >= right

    def __bool__(self) -> bool:
        """Use the nominal value for ordinary Python truth testing."""

        return bool(self.nominal)

    # -- conversions --------------------------------------------------------
    def __float__(self) -> float:
        raise TypeError(
            "Quantity cannot be converted to float implicitly because that would discard "
            "uncertainty, correlations, units, and provenance. Use q.n, q.nominal, or "
            "nominal_value(q) when nominal extraction is intentional; use nominal_values(...) "
            "or QuantityArray.nominal for arrays/waveforms."
        )

    def __format__(self, spec: str) -> str:
        if not spec:
            return str(self)
        if "u" in spec:
            return self._format_with_uncertainty(spec)
        return format(self.nominal, spec)

    def _format_with_uncertainty(self, spec: str) -> str:
        match = re.fullmatch(r"(?:\.(\d+))?u([SPL]?)", spec)
        if match is None:
            raise ValueError(f"Invalid uncertainty format specifier: {spec!r}")
        sig = int(match.group(1) or "1")
        mode = match.group(2)
        y, u, decimals = self._rounded_nominal_uncertainty(sig)
        value = f"{y:.{decimals}f}"
        uncert = f"{u:.{decimals}f}"
        if mode == "S":
            digits = int(round(u * (10**decimals)))
            return f"{value}({digits})"
        if mode == "P":
            return f"{value}\N{PLUS-MINUS SIGN}{uncert}"
        if mode == "L":
            return f"{value} \\pm {uncert}"
        return f"{value}+/-{uncert}"

    def _rounded_nominal_uncertainty(self, sig: int) -> tuple[float, float, int]:
        from .budget import round_to_significant

        u = round_to_significant(self.u, sig)
        if u and math.isfinite(u):
            decimals = max(0, sig - 1 - math.floor(math.log10(abs(u))))
            y = round(self.nominal, decimals)
        else:
            decimals = max(0, sig)
            y = self.nominal
        return y, u, decimals

    def __repr__(self) -> str:
        status = ", status='nominal-only'" if self._is_nominal_only_non_report_grade() else ""
        return f"Quantity({self.nominal!r}, {self.unit!r}, u={self.u:.6g}{status})"

    def __str__(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        status = (
            " [nominal-only, not report-grade]" if self._is_nominal_only_non_report_grade() else ""
        )
        return f"{self.nominal} +/- {self.u}{unit}{status}"

    def _repr_html_(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        status = (
            " <span class='status'>[nominal-only, not report-grade]</span>"
            if self._is_nominal_only_non_report_grade()
            else ""
        )
        return (
            "<span class='pytestlab-quantity'>"
            f"<span class='nominal'>{escape(f'{self.nominal:g}')}</span> "
            f"&plusmn; <span class='uncertainty'>{escape(f'{self.u:g}')}</span>"
            f"<span class='unit'>{escape(unit)}</span>"
            f"{status}"
            "</span>"
        )

    def __array_ufunc__(self, ufunc: Any, method: str, *inputs: Any, **kwargs: Any) -> Any:
        if method != "__call__" or kwargs.get("out") is not None:
            return NotImplemented
        import numpy as np

        from . import functions as fn

        if ufunc is np.add:
            left, right = inputs
            if isinstance(left, Quantity):
                return left.__add__(right)
            if isinstance(right, Quantity):
                return right.__radd__(left)
        if ufunc is np.subtract:
            left, right = inputs
            if isinstance(left, Quantity):
                return left.__sub__(right)
            if isinstance(right, Quantity):
                return right.__rsub__(left)
        if ufunc is np.multiply:
            left, right = inputs
            if isinstance(left, Quantity):
                return left.__mul__(right)
            if isinstance(right, Quantity):
                return right.__rmul__(left)
        if ufunc in (np.divide, np.true_divide):
            left, right = inputs
            if isinstance(left, Quantity):
                return left.__truediv__(right)
            if isinstance(right, Quantity):
                return right.__rtruediv__(left)
        if ufunc is np.power:
            base, power = inputs
            if isinstance(base, Quantity):
                return base**power
            if isinstance(power, Quantity):
                if power.unit:
                    raise units.UnitCompatibilityError(
                        "Exponent quantity must be dimensionless for scalar base ** Quantity."
                    )
                base_float = float(base)
                if base_float <= 0.0:
                    raise ValueError("Scalar base must be positive for uncertain exponent.")
                nominal = base_float**power.nominal
                grad = power._scaled_grad(nominal * math.log(base_float))
                return power._new(nominal, "", grad)
            return NotImplemented
        if ufunc is np.negative:
            return -inputs[0]
        if ufunc is np.positive:
            return +inputs[0]
        if ufunc is np.absolute:
            return fn.absolute(inputs[0])
        if ufunc is np.sqrt:
            return fn.sqrt(inputs[0])
        if ufunc is np.exp:
            return fn.exp(inputs[0])
        if ufunc is np.log:
            return fn.log(inputs[0])
        if ufunc is np.log10:
            return fn.log10(inputs[0])
        if ufunc is np.sin:
            return fn.sin(inputs[0])
        if ufunc is np.cos:
            return fn.cos(inputs[0])
        if ufunc is np.tan:
            return fn.tan(inputs[0])
        if ufunc is np.arctan2:
            return fn.atan2(inputs[0], inputs[1])
        comparison = {
            np.equal: operator.eq,
            np.not_equal: operator.ne,
            np.less: operator.lt,
            np.less_equal: operator.le,
            np.greater: operator.gt,
            np.greater_equal: operator.ge,
        }.get(ufunc)
        if comparison is not None:
            left, right = (
                value.item() if isinstance(value, np.ndarray) and value.ndim == 0 else value
                for value in inputs
            )
            return comparison(left, right)
        return NotImplemented

    def error_components(
        self,
        *,
        basis: str = "std",
        correlation: str = "diagonal",
    ) -> list[dict[str, Any]]:
        """Return auditable uncertainty component rows.

        Diagonal rows report individual atom contributions.  When correlations
        exist, ``correlation="include_cross"`` with ``basis="variance"`` adds
        signed covariance cross terms so the row variances sum to ``variance``.
        """

        if basis not in {"std", "variance"}:
            raise ValueError("basis must be 'std' or 'variance'.")
        if correlation not in {"diagonal", "include_cross"}:
            raise ValueError("correlation must be 'diagonal' or 'include_cross'.")
        if basis == "std" and correlation == "include_cross":
            raise ValueError("cross terms are variance contributions; use basis='variance'.")

        reg = self.registry
        rows: list[dict[str, Any]] = []
        for uid, sensitivity in self.grad.items():
            atom = reg.atoms[uid]
            std_contribution = abs(sensitivity) * atom.std_uncertainty
            rows.append(
                {
                    "type": "diagonal",
                    "uid": uid,
                    "label": atom.label,
                    "sensitivity": sensitivity,
                    "input_uncertainty": atom.std_uncertainty,
                    "std_contribution": std_contribution,
                    "variance_contribution": (sensitivity**2) * atom.variance,
                    "unit": atom.unit,
                    "kind": atom.kind.value,
                    "distribution": atom.distribution.value,
                    "source": atom.source,
                }
            )
        has_relevant_correlations = any(
            self.grad.get(a, 0.0) != 0.0 and self.grad.get(b, 0.0) != 0.0
            for (a, b) in reg._covariances
        )
        if has_relevant_correlations and correlation == "diagonal":
            warnings.warn(
                "Diagonal error components do not include covariance cross terms; "
                "use basis='variance', correlation='include_cross' for a complete variance budget.",
                CorrelationComponentWarning,
                stacklevel=2,
            )
        if correlation == "include_cross":
            for (uid_a, uid_b), covariance in reg._covariances.items():
                sensitivity_a = self.grad.get(uid_a, 0.0)
                sensitivity_b = self.grad.get(uid_b, 0.0)
                if sensitivity_a == 0.0 or sensitivity_b == 0.0:
                    continue
                atom_a = reg.atoms[uid_a]
                atom_b = reg.atoms[uid_b]
                rows.append(
                    {
                        "type": "cross",
                        "uid_a": uid_a,
                        "uid_b": uid_b,
                        "label": f"{atom_a.label} × {atom_b.label}",
                        "sensitivity_a": sensitivity_a,
                        "sensitivity_b": sensitivity_b,
                        "covariance": covariance,
                        "variance_contribution": 2.0 * sensitivity_a * sensitivity_b * covariance,
                    }
                )
        key = "variance_contribution" if basis == "variance" else "std_contribution"
        rows.sort(key=lambda row: abs(float(row.get(key, 0.0))), reverse=True)
        return rows

    def dominant(self, n: int = 3) -> list[Any]:
        return self.budget().entries[:n]

    def to_dsi(self, *, coverage_factor: float = 2.0) -> dict:
        from .units import to_dsi_unit

        dsi_unit, unit_resolved = to_dsi_unit(self.unit)
        return {
            "value": self.nominal,
            "unit": dsi_unit,
            "unit_resolved": unit_resolved,
            "standard_uncertainty": self.u,
            "expanded_uncertainty": self.u * coverage_factor,
            "coverageFactor": coverage_factor,
            "coverageProbability": None,
            "distribution": "derived",
        }

    def to_ufloat(self):  # pragma: no cover - optional interop
        from .compat import make_ufloat

        return make_ufloat(self.nominal, self.u)

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        """Serialize nominal, unit, gradient, referenced atoms and covariances."""

        from .atoms import Distribution  # noqa: F401
        from .atoms import Kind  # noqa: F401

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
                "traceability": a.traceability.model_dump(mode="json") if a.traceability else None,
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
            "measurement_model": self.measurement_model.model_dump(mode="json")
            if self.measurement_model
            else None,
            "provenance": self.provenance.model_dump(mode="json") if self.provenance else None,
            "dof_method": self.dof_method,
        }

    @classmethod
    def from_dict(cls, data: dict, registry: AtomRegistry | None = None) -> Quantity:
        from .atoms import Distribution
        from .atoms import InfluenceQuantity
        from .atoms import Kind
        from .metrology import model_from_any
        from .metrology import provenance_from_any
        from .metrology import traceability_ref_from_any

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
                    traceability=traceability_ref_from_any(a.get("traceability")),
                )
            )
        for a, b, cov in data.get("covariances", []):
            reg.set_covariance(a, b, cov)
        grad = {uid: float(g) for uid, g in data.get("grad", {}).items()}
        q = cls(data["nominal"], data.get("unit", ""), grad, reg)
        q.measurement_model = model_from_any(data.get("measurement_model"))
        q.provenance = provenance_from_any(data.get("provenance"))
        q.dof_method = data.get("dof_method")
        return q
