from __future__ import annotations

import ast
import importlib
import math
import operator
from enum import Enum
from typing import Any
from typing import Literal
from typing import TypeAlias

import numpy as np
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

try:  # pragma: no cover - exercised when optional dependency is installed
    import pint

    _UNIT_REGISTRY = pint.UnitRegistry()
except Exception:  # pragma: no cover - fallback keeps core usable in minimal envs
    _UNIT_REGISTRY = None

_SCIPY_STATS: Any | None
try:  # pragma: no cover - exercised when optional dependency is installed
    _SCIPY_STATS = importlib.import_module("scipy.stats")
except Exception:  # pragma: no cover - fallback keeps core usable in minimal envs
    _SCIPY_STATS = None


class UncertaintyDistribution(str, Enum):
    """Supported assumptions for converting limits to standard uncertainty."""

    STANDARD = "standard"
    NORMAL = "normal"
    RECTANGULAR = "rectangular"
    TRIANGULAR = "triangular"


class UncertaintyKind(str, Enum):
    """GUM-style component source classification."""

    TYPE_A = "type_a"
    TYPE_B = "type_b"


class UnitCompatibilityError(ValueError):
    """Raised when uncertainty operands use incompatible units."""


def _unit_name(unit: str | None) -> str:
    return unit or ""


def assert_compatible_units(left: str | None, right: str | None) -> None:
    """Validate unit compatibility, using pint when available and exact strings otherwise."""

    if not left or not right or left == right:
        return
    if _UNIT_REGISTRY is None:
        raise UnitCompatibilityError(f"Incompatible units: {left!r} and {right!r}")
    try:
        (1 * _UNIT_REGISTRY(left)).to(right)
    except Exception as exc:
        raise UnitCompatibilityError(f"Incompatible units: {left!r} and {right!r}") from exc


def _convert_units(value: float, source: str | None, target: str | None) -> float:
    if not source or not target or source == target:
        return value
    assert_compatible_units(source, target)
    if _UNIT_REGISTRY is None:
        return value
    return float((value * _UNIT_REGISTRY(source)).to(target).magnitude)


def _format_unit(unit: Any) -> str:
    unit_text = str(unit)
    return "" if unit_text == "dimensionless" else unit_text


def _combine_units(left: str | None, right: str | None, op: str) -> str:
    left = _unit_name(left)
    right = _unit_name(right)
    if _UNIT_REGISTRY is not None:
        try:
            left_quantity = 1 * _UNIT_REGISTRY(left) if left else 1
            right_quantity = 1 * _UNIT_REGISTRY(right) if right else 1
            if op == "mul":
                return _format_unit(getattr(left_quantity * right_quantity, "units", ""))
            if op == "truediv":
                return _format_unit(getattr(left_quantity / right_quantity, "units", ""))
        except Exception:
            pass
    if op == "mul":
        if left and right:
            return f"{left}*{right}"
        return left or right
    if op == "truediv":
        if left and right:
            return "" if left == right else f"{left}/{right}"
        return left or (f"1/{right}" if right else "")
    raise NotImplementedError(op)


def _pint_quantity(value: float, unit: str | None) -> Any:
    if _UNIT_REGISTRY is None:
        return None
    return value * (_UNIT_REGISTRY(unit) if unit else _UNIT_REGISTRY.dimensionless)


def _operation_nominal_and_unit(
    left_value: float,
    left_unit: str | None,
    right_value: float,
    right_unit: str | None,
    op: str,
) -> tuple[float, str]:
    if _UNIT_REGISTRY is not None:
        try:
            left_quantity = _pint_quantity(left_value, left_unit)
            right_quantity = _pint_quantity(right_value, right_unit)
            if op == "add":
                result = left_quantity + right_quantity
                result = result.to(_unit_name(left_unit)) if left_unit else result
            elif op == "sub":
                result = left_quantity - right_quantity
                result = result.to(_unit_name(left_unit)) if left_unit else result
            elif op == "mul":
                result = left_quantity * right_quantity
            elif op == "truediv":
                result = left_quantity / right_quantity
                try:
                    result = result.to("")
                except Exception:
                    pass
            else:
                raise NotImplementedError(op)
            unit = _unit_name(left_unit) if op in {"add", "sub"} else _format_unit(result.units)
            return float(result.magnitude), unit
        except Exception as exc:
            if op in {"add", "sub"}:
                raise UnitCompatibilityError(
                    f"Incompatible units: {left_unit!r} and {right_unit!r}"
                ) from exc
    if op in {"add", "sub"}:
        other_value = _convert_units(right_value, right_unit, left_unit)
        nominal = left_value + other_value if op == "add" else left_value - other_value
        return nominal, _unit_name(left_unit)
    if op == "mul":
        return left_value * right_value, _combine_units(left_unit, right_unit, op)
    if op == "truediv":
        return left_value / right_value, _combine_units(left_unit, right_unit, op)
    raise NotImplementedError(op)


def _scipy_stats() -> Any | None:
    global _SCIPY_STATS
    if _SCIPY_STATS is None:
        try:
            _SCIPY_STATS = importlib.import_module("scipy.stats")
        except Exception:
            return None
    return _SCIPY_STATS


def _distribution_divisor(distribution: UncertaintyDistribution, coverage_factor: float) -> float:
    if distribution == UncertaintyDistribution.STANDARD:
        return 1.0
    if distribution == UncertaintyDistribution.RECTANGULAR:
        return math.sqrt(3.0)
    if distribution == UncertaintyDistribution.TRIANGULAR:
        return math.sqrt(6.0)
    if coverage_factor <= 0:
        raise ValueError("coverage_factor must be positive for normal distributions.")
    return coverage_factor


class UncertaintyContext(BaseModel):
    """Runtime context used to evaluate instrument uncertainty models."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    reading: float
    unit: str | None = None
    function: str | None = None
    range_value: float | None = None
    range_unit: str | None = None
    resolution: float | None = None
    frequency: float | None = None
    temperature_C: float | None = None
    humidity_percent: float | None = None
    nplc: float | None = None
    bandwidth: float | None = None
    channel: int | None = None
    sample_count: int | None = None
    calibration_age_days: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UncertaintyComponent(BaseModel):
    """One contribution to a measurement uncertainty budget."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    name: str
    value: float
    unit: str | None = None
    kind: UncertaintyKind = UncertaintyKind.TYPE_B
    distribution: UncertaintyDistribution = UncertaintyDistribution.RECTANGULAR
    coverage_factor: float = Field(1.0, gt=0)
    sensitivity: float = 1.0
    degrees_of_freedom: float | None = Field(None, gt=0)
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def divisor(self) -> float:
        return _distribution_divisor(self.distribution, self.coverage_factor)

    @property
    def standard_uncertainty(self) -> float:
        return abs(self.value * self.sensitivity) / self.divisor

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class UncertaintyBudget(BaseModel):
    """Combined standard uncertainty plus auditable component details."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    components: list[UncertaintyComponent] = Field(default_factory=list)
    unit: str | None = None
    method: str = "analytical"
    coverage_factor: float = Field(2.0, gt=0)
    samples: list[float] | None = None

    @property
    def combined_standard_uncertainty(self) -> float:
        variance = sum(component.standard_uncertainty**2 for component in self.components)
        return math.sqrt(variance)

    @property
    def effective_degrees_of_freedom(self) -> float | None:
        u_c = self.combined_standard_uncertainty
        if u_c == 0:
            return None
        denom = 0.0
        for component in self.components:
            if component.degrees_of_freedom:
                denom += component.standard_uncertainty**4 / component.degrees_of_freedom
        return (u_c**4 / denom) if denom else None

    def coverage_factor_for(self, confidence: float = 0.95) -> float:
        """Return a two-sided coverage factor using Welch-Satterthwaite dof when available."""

        if not 0 < confidence < 1:
            raise ValueError("confidence must be between 0 and 1.")
        tail_probability = (1.0 + confidence) / 2.0
        dof = self.effective_degrees_of_freedom
        scipy_stats = _scipy_stats()
        if scipy_stats is not None:
            if dof is not None:
                return float(scipy_stats.t.ppf(tail_probability, dof))
            return float(scipy_stats.norm.ppf(tail_probability))
        if math.isclose(confidence, 0.95, rel_tol=0.0, abs_tol=0.01):
            return 2.0
        raise RuntimeError("scipy is required for non-default coverage factors.")

    def expanded_uncertainty(
        self,
        coverage_factor: float | None = None,
        *,
        confidence: float | None = None,
    ) -> float:
        factor = self.coverage_factor_for(confidence) if confidence is not None else coverage_factor
        return self.combined_standard_uncertainty * (factor or self.coverage_factor)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class MeasurementQuantity(BaseModel):
    """Scientific scalar value with units, uncertainty, and budget provenance."""

    model_config = ConfigDict(
        validate_assignment=True, arbitrary_types_allowed=True, extra="forbid"
    )

    nominal: float
    unit: str
    budget: UncertaintyBudget = Field(default_factory=UncertaintyBudget)

    @property
    def u(self) -> float:
        return self.budget.combined_standard_uncertainty

    @property
    def std_dev(self) -> float:
        return self.u

    @property
    def nominal_value(self) -> float:
        return self.nominal

    @property
    def n(self) -> float:
        return self.nominal

    @property
    def s(self) -> float:
        return self.u

    @property
    def relative_u(self) -> float:
        return abs(self.u / self.nominal) if self.nominal else math.inf

    def U(self, k: float = 2.0) -> float:
        return self.budget.expanded_uncertainty(k)

    def to_ufloat(self):
        from uncertainties import ufloat

        return ufloat(self.nominal, self.u)

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["standard_uncertainty"] = self.u
        data["expanded_uncertainty_k2"] = self.U(2.0)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeasurementQuantity:
        data = {
            key: value
            for key, value in data.items()
            if key not in {"standard_uncertainty", "expanded_uncertainty_k2"}
        }
        return cls.model_validate(data)

    def _component_contribution(
        self,
        component: UncertaintyComponent,
        *,
        operand: Literal["left", "right"],
        op: str,
        other: MeasurementQuantity | None,
        output_unit: str,
        component_unit_fallback: str | None = None,
    ) -> float:
        component_unit = component.unit or component_unit_fallback or self.unit
        standard_uncertainty = component.standard_uncertainty
        if _UNIT_REGISTRY is not None:
            try:
                uncertainty_quantity = _pint_quantity(standard_uncertainty, component_unit)
                if other is None or op in {"add", "sub"}:
                    contribution = uncertainty_quantity
                elif op == "mul":
                    multiplier = other if operand == "left" else self
                    contribution = uncertainty_quantity * _pint_quantity(
                        multiplier.nominal, multiplier.unit
                    )
                elif op == "truediv":
                    if operand == "left":
                        other_quantity = _pint_quantity(other.nominal, other.unit)
                        contribution = uncertainty_quantity / other_quantity
                    else:
                        self_quantity = _pint_quantity(self.nominal, self.unit)
                        other_quantity = _pint_quantity(other.nominal, other.unit)
                        contribution = self_quantity * uncertainty_quantity / (other_quantity**2)
                else:
                    raise NotImplementedError(op)
                if output_unit:
                    contribution = contribution.to(output_unit)
                else:
                    try:
                        contribution = contribution.to("")
                    except Exception:
                        pass
                return abs(float(contribution.magnitude))
            except Exception:
                if op in {"add", "sub"}:
                    raise
        if other is None or op in {"add", "sub"}:
            return abs(_convert_units(standard_uncertainty, component_unit, output_unit))
        if op == "mul":
            multiplier = other if operand == "left" else self
            return abs(multiplier.nominal * standard_uncertainty)
        if op == "truediv":
            if operand == "left":
                return abs(standard_uncertainty / other.nominal)
            return abs((self.nominal * standard_uncertainty) / (other.nominal**2))
        raise NotImplementedError(op)

    @staticmethod
    def _propagated_component(
        component: UncertaintyComponent,
        *,
        name: str,
        value: float,
        unit: str,
        op: str,
        operand: str,
    ) -> UncertaintyComponent:
        return UncertaintyComponent(
            name=name,
            value=value,
            unit=unit,
            kind=component.kind,
            distribution=UncertaintyDistribution.STANDARD,
            degrees_of_freedom=component.degrees_of_freedom,
            source=component.source,
            metadata={
                "operation": op,
                "operand": operand,
                "input_component": component.as_dict(),
            },
        )

    def _propagated_components(
        self,
        *,
        op: str,
        output_unit: str,
        other: MeasurementQuantity | None = None,
        scalar_factor: float = 1.0,
    ) -> list[UncertaintyComponent]:
        components: list[UncertaintyComponent] = []
        for component in self.budget.components:
            if other is None:
                contribution = abs(component.standard_uncertainty * scalar_factor)
            else:
                contribution = self._component_contribution(
                    component,
                    operand="left",
                    op=op,
                    other=other,
                    output_unit=output_unit,
                )
            components.append(
                self._propagated_component(
                    component,
                    name=f"left.{component.name}",
                    value=contribution,
                    unit=output_unit,
                    op=op,
                    operand="left",
                )
            )
        if other is not None:
            for component in other.budget.components:
                contribution = self._component_contribution(
                    component,
                    operand="right",
                    op=op,
                    other=other,
                    output_unit=output_unit,
                    component_unit_fallback=other.unit,
                )
                components.append(
                    self._propagated_component(
                        component,
                        name=f"right.{component.name}",
                        value=contribution,
                        unit=output_unit,
                        op=op,
                        operand="right",
                    )
                )
        return components

    def _binary(self, other: Any, op: str) -> MeasurementQuantity:
        if isinstance(other, MeasurementQuantity):
            nominal, unit = _operation_nominal_and_unit(
                self.nominal,
                self.unit,
                other.nominal,
                other.unit,
                op,
            )
            components = self._propagated_components(op=op, output_unit=unit, other=other)
        else:
            scalar = float(other)
            if op == "add":
                nominal, unit, scalar_factor = self.nominal + scalar, self.unit, 1.0
            elif op == "sub":
                nominal, unit, scalar_factor = self.nominal - scalar, self.unit, 1.0
            elif op == "mul":
                nominal, unit, scalar_factor = self.nominal * scalar, self.unit, abs(scalar)
            elif op == "truediv":
                nominal, unit, scalar_factor = self.nominal / scalar, self.unit, abs(1.0 / scalar)
            else:
                raise NotImplementedError(op)
            components = self._propagated_components(
                op=op,
                output_unit=unit,
                scalar_factor=scalar_factor,
            )
        budget = UncertaintyBudget(
            components=components,
            unit=unit,
            method="analytical_propagation",
        )
        return MeasurementQuantity(nominal=nominal, unit=unit, budget=budget)

    def _scalar_left_binary(self, scalar: float, op: str) -> MeasurementQuantity:
        if op == "add":
            return self + scalar
        if op == "sub":
            nominal = scalar - self.nominal
            unit = self.unit
            components = [
                self._propagated_component(
                    component,
                    name=f"right.{component.name}",
                    value=component.standard_uncertainty,
                    unit=unit,
                    op="rsub",
                    operand="right",
                )
                for component in self.budget.components
            ]
        elif op == "mul":
            return self * scalar
        elif op == "truediv":
            nominal = scalar / self.nominal
            unit = _combine_units(None, self.unit, "truediv")
            scale = abs(scalar / (self.nominal**2))
            components = [
                self._propagated_component(
                    component,
                    name=f"right.{component.name}",
                    value=component.standard_uncertainty * scale,
                    unit=unit,
                    op="rtruediv",
                    operand="right",
                )
                for component in self.budget.components
            ]
        else:
            raise NotImplementedError(op)
        budget = UncertaintyBudget(
            components=components,
            unit=unit,
            method="analytical_propagation",
        )
        return MeasurementQuantity(nominal=nominal, unit=unit, budget=budget)

    def __add__(self, other: Any) -> MeasurementQuantity:
        return self._binary(other, "add")

    def __radd__(self, other: Any) -> MeasurementQuantity:
        return self._scalar_left_binary(float(other), "add")

    def __sub__(self, other: Any) -> MeasurementQuantity:
        return self._binary(other, "sub")

    def __rsub__(self, other: Any) -> MeasurementQuantity:
        return self._scalar_left_binary(float(other), "sub")

    def __mul__(self, other: Any) -> MeasurementQuantity:
        return self._binary(other, "mul")

    def __rmul__(self, other: Any) -> MeasurementQuantity:
        return self._scalar_left_binary(float(other), "mul")

    def __truediv__(self, other: Any) -> MeasurementQuantity:
        return self._binary(other, "truediv")

    def __rtruediv__(self, other: Any) -> MeasurementQuantity:
        return self._scalar_left_binary(float(other), "truediv")

    def __float__(self) -> float:
        return float(self.nominal)

    def __str__(self) -> str:
        return f"{self.nominal}+/-{self.u} {self.unit}"


class AccuracySpec(BaseModel):
    """Explicit scientific uncertainty model for simple datasheet limits."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["linear"] = "linear"
    reading_percent: float | None = Field(None, ge=0)
    reading_fraction: float | None = Field(None, ge=0)
    reading_ppm: float | None = Field(None, ge=0)
    range_percent: float | None = Field(None, ge=0)
    range_fraction: float | None = Field(None, ge=0)
    offset: float | None = Field(None, ge=0)
    offset_unit: str | None = None
    counts: float | None = Field(None, ge=0)
    resolution: float | None = Field(None, ge=0)
    distribution: UncertaintyDistribution = UncertaintyDistribution.RECTANGULAR
    coverage_factor: float = Field(1.0, gt=0)
    degrees_of_freedom: float | None = Field(None, gt=0)
    source: str | None = None

    def _component(self, name: str, value: float, unit: str | None) -> UncertaintyComponent:
        return UncertaintyComponent(
            name=name,
            value=abs(value),
            unit=unit,
            distribution=self.distribution,
            coverage_factor=self.coverage_factor,
            degrees_of_freedom=self.degrees_of_freedom,
            source=self.source,
        )

    def evaluate(self, context: UncertaintyContext) -> UncertaintyBudget:
        reading = abs(context.reading)
        unit = _unit_name(context.unit)
        components: list[UncertaintyComponent] = []

        reading_fraction = 0.0
        if self.reading_fraction is not None:
            reading_fraction += self.reading_fraction
        if self.reading_percent is not None:
            reading_fraction += self.reading_percent / 100.0
        if self.reading_ppm is not None:
            reading_fraction += self.reading_ppm / 1_000_000.0
        if reading_fraction:
            components.append(self._component("reading", reading_fraction * reading, unit))

        range_fraction = 0.0
        if self.range_fraction is not None:
            range_fraction += self.range_fraction
        if self.range_percent is not None:
            range_fraction += self.range_percent / 100.0
        if range_fraction:
            if context.range_value is None:
                raise ValueError("range_value is required for range-based uncertainty terms.")
            components.append(
                self._component(
                    "range",
                    range_fraction * abs(context.range_value),
                    _unit_name(context.range_unit or context.unit),
                )
            )

        if self.offset is not None:
            components.append(
                self._component(
                    "offset",
                    _convert_units(self.offset, self.offset_unit, context.unit),
                    unit,
                )
            )

        resolution = self.resolution if self.resolution is not None else context.resolution
        if self.counts is not None:
            if resolution is None:
                raise ValueError("resolution is required when counts are used in an accuracy spec.")
            components.append(self._component("counts", self.counts * resolution, unit))

        return UncertaintyBudget(
            components=components, unit=unit, method="linear", coverage_factor=2.0
        )

    def calculate_std_dev(self, reading_value: float, range_value: float | None = None) -> float:
        """Compatibility helper returning combined standard uncertainty."""

        context = UncertaintyContext(reading=reading_value, range_value=range_value)
        return self.evaluate(context).combined_standard_uncertainty

    def quantity(
        self,
        reading_value: float,
        *,
        unit: str,
        range_value: float | None = None,
        range_unit: str | None = None,
        resolution: float | None = None,
        **metadata: Any,
    ) -> MeasurementQuantity:
        context = UncertaintyContext(
            reading=reading_value,
            unit=unit,
            range_value=range_value,
            range_unit=range_unit,
            resolution=resolution,
            metadata=metadata,
        )
        return MeasurementQuantity(nominal=reading_value, unit=unit, budget=self.evaluate(context))


class BandAccuracySpec(BaseModel):
    """Select an accuracy model based on a scalar context value such as frequency."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["band_table"] = "band_table"
    variable: str = "frequency"
    bands: list[dict[str, Any]]

    def evaluate(self, context: UncertaintyContext) -> UncertaintyBudget:
        value = getattr(context, self.variable, None)
        if value is None:
            raise ValueError(f"{self.variable!r} is required for band-table uncertainty.")
        for band in self.bands:
            lower = band.get("min", -math.inf)
            upper = band.get("max", math.inf)
            if lower <= value <= upper:
                spec_data = {k: v for k, v in band.items() if k not in {"min", "max"}}
                return AccuracySpec(**spec_data).evaluate(context)
        raise ValueError(f"No uncertainty band matched {self.variable}={value!r}.")


_SAFE_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


_EXPRESSION_CONTEXT_VALUES = {
    "reading": "reading",
    "range": "range_value",
    "resolution": "resolution",
    "frequency": "frequency",
    "temperature_C": "temperature_C",
    "humidity_percent": "humidity_percent",
    "nplc": "nplc",
    "bandwidth": "bandwidth",
    "channel": "channel",
    "sample_count": "sample_count",
    "calibration_age_days": "calibration_age_days",
}


class ExpressionAccuracySpec(BaseModel):
    """Evaluate a constrained mathematical expression as an uncertainty limit."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["expression"] = "expression"
    expression: str
    parameters: dict[str, float] = Field(default_factory=dict)
    distribution: UncertaintyDistribution = UncertaintyDistribution.RECTANGULAR
    coverage_factor: float = Field(1.0, gt=0)

    def _eval(self, node: ast.AST, names: dict[str, float]) -> float:
        if isinstance(node, ast.Expression):
            return self._eval(node.body, names)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError(f"Unknown expression variable: {node.id}")
            return float(names[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -self._eval(node.operand, names)
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
            return _SAFE_BINOPS[type(node.op)](
                self._eval(node.left, names), self._eval(node.right, names)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"sqrt", "abs"}
        ):
            fn = math.sqrt if node.func.id == "sqrt" else abs
            return float(fn(*(self._eval(arg, names) for arg in node.args)))
        raise ValueError(f"Unsupported expression node: {ast.dump(node)}")

    def _referenced_names(self) -> set[str]:
        parsed = ast.parse(self.expression, mode="eval")
        return {node.id for node in ast.walk(parsed) if isinstance(node, ast.Name)}

    def evaluate(self, context: UncertaintyContext) -> UncertaintyBudget:
        referenced_names = self._referenced_names()
        names = dict(self.parameters)
        for name, context_field in _EXPRESSION_CONTEXT_VALUES.items():
            context_value = getattr(context, context_field)
            if name in referenced_names and name not in names and context_value is None:
                raise ValueError(f"{name!r} is required for expression uncertainty.")
            if context_value is not None:
                names.setdefault(name, float(context_value))
        value = self._eval(ast.parse(self.expression, mode="eval"), names)
        component = UncertaintyComponent(
            name="expression",
            value=abs(value),
            unit=context.unit,
            distribution=self.distribution,
            coverage_factor=self.coverage_factor,
        )
        return UncertaintyBudget(components=[component], unit=context.unit, method="expression")


class MonteCarloAccuracySpec(BaseModel):
    """Monte Carlo evaluator for independent normal/rectangular components."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["monte_carlo"] = "monte_carlo"
    components: list[
        AccuracySpec | BandAccuracySpec | ExpressionAccuracySpec | RepeatabilityAccuracySpec
    ]
    samples: int = Field(10_000, gt=1)
    seed: int | None = None

    def evaluate(self, context: UncertaintyContext) -> UncertaintyBudget:
        rng = np.random.default_rng(self.seed)
        offsets = np.zeros(self.samples)
        budget_components: list[UncertaintyComponent] = []
        for spec in self.components:
            component_budget = spec.evaluate(context)
            budget_components.extend(component_budget.components)
            for component in component_budget.components:
                limit = component.value
                if component.distribution == UncertaintyDistribution.RECTANGULAR:
                    offsets += rng.uniform(-limit, limit, self.samples)
                elif component.distribution == UncertaintyDistribution.TRIANGULAR:
                    offsets += rng.triangular(-limit, 0.0, limit, self.samples)
                else:
                    offsets += rng.normal(0.0, component.standard_uncertainty, self.samples)
        sample_values = context.reading + offsets
        mc_component = UncertaintyComponent(
            name="monte_carlo",
            value=float(np.std(sample_values, ddof=1)),
            unit=context.unit,
            distribution=UncertaintyDistribution.STANDARD,
            metadata={"input_components": [component.as_dict() for component in budget_components]},
        )
        return UncertaintyBudget(
            components=[mc_component],
            unit=context.unit,
            method="monte_carlo",
            samples=sample_values.tolist(),
        )


class RepeatabilityAccuracySpec(BaseModel):
    """Type A repeatability model from repeated observations."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["repeatability"] = "repeatability"
    observations: list[float] = Field(min_length=2)
    unit: str | None = None
    use_standard_error: bool = True

    def evaluate(self, context: UncertaintyContext) -> UncertaintyBudget:
        values = np.asarray(self.observations, dtype=float)
        sigma = float(np.std(values, ddof=1))
        if self.use_standard_error:
            sigma = sigma / math.sqrt(values.size)
        component = UncertaintyComponent(
            name="repeatability",
            value=sigma,
            unit=self.unit or context.unit,
            kind=UncertaintyKind.TYPE_A,
            distribution=UncertaintyDistribution.STANDARD,
            degrees_of_freedom=float(values.size - 1),
        )
        return UncertaintyBudget(
            components=[component],
            unit=self.unit or context.unit,
            method="repeatability",
        )


LeafAccuracyModel: TypeAlias = (
    AccuracySpec
    | BandAccuracySpec
    | ExpressionAccuracySpec
    | MonteCarloAccuracySpec
    | RepeatabilityAccuracySpec
)


class CompositeBudgetSpec(BaseModel):
    """Combine multiple uncertainty model outputs into one budget."""

    model_config = ConfigDict(
        validate_assignment=True, arbitrary_types_allowed=True, extra="forbid"
    )

    model: Literal["composite"] = "composite"
    components: list[LeafAccuracyModel | CompositeBudgetSpec]

    def evaluate(self, context: UncertaintyContext) -> UncertaintyBudget:
        budget_components: list[UncertaintyComponent] = []
        samples: list[float] | None = None
        for model in self.components:
            budget = model.evaluate(context)
            budget_components.extend(budget.components)
            if budget.samples is not None:
                samples = budget.samples if samples is None else samples + budget.samples
        return UncertaintyBudget(
            components=budget_components,
            unit=context.unit,
            method="composite",
            samples=samples,
        )


AccuracyModel: TypeAlias = LeafAccuracyModel | CompositeBudgetSpec


def evaluate_uncertainty_model(
    model: AccuracyModel, context: UncertaintyContext
) -> UncertaintyBudget:
    """Evaluate any supported uncertainty model into an auditable budget."""

    return model.evaluate(context)


def quantity_from_uncertainty_model(
    model: AccuracyModel,
    context: UncertaintyContext,
) -> MeasurementQuantity:
    """Convert any supported uncertainty model into a MeasurementQuantity."""

    return MeasurementQuantity(
        nominal=context.reading,
        unit=_unit_name(context.unit),
        budget=evaluate_uncertainty_model(model, context),
    )


def standard_uncertainty_from_model(model: AccuracyModel, context: UncertaintyContext) -> float:
    """Return combined standard uncertainty for any supported uncertainty model."""

    return evaluate_uncertainty_model(model, context).combined_standard_uncertainty
