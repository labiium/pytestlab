"""Datasheet uncertainty models that mint atoms into a :class:`Quantity`.

The model field schema is preserved from the previous ``config/accuracy.py`` so
existing vendor YAML profiles continue to load unchanged. The behaviour change
is internal: each limit term becomes an :class:`InfluenceQuantity` (atom) with a
stable identity, so contributions from the same physical source (e.g. an
instrument's gain error) correlate across readings.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any
from typing import Literal
from typing import TypeAlias

import numpy as np
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from . import units
from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import Kind
from .atoms import default_registry
from .atoms import divisor_for
from .quantity import Quantity


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
    # Stable identity prefix for atom keys; when set, terms correlate across reads.
    source_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _key(context: UncertaintyContext, term: str) -> str | None:
    if context.source_key is None:
        return None
    return f"{context.source_key}:{term}"


class _Evaluable:
    """Mixin giving every spec a dual-signature ``quantity`` and ``evaluate``.

    ``quantity`` accepts either an :class:`UncertaintyContext` or a bare reading
    value with keyword parameters (the ergonomic form). ``evaluate`` returns the
    derived :class:`UncertaintyBudget`.
    """

    def _build_quantity(self, context: UncertaintyContext, registry: AtomRegistry | None = None) -> Quantity:  # noqa: D401
        raise NotImplementedError

    @staticmethod
    def _coerce_context(
        context_or_reading: "UncertaintyContext | float",
        unit: str,
        range_value: float | None,
        range_unit: str | None,
        resolution: float | None,
        source_key: str | None,
        metadata: dict[str, Any],
    ) -> UncertaintyContext:
        if isinstance(context_or_reading, UncertaintyContext):
            return context_or_reading
        return UncertaintyContext(
            reading=float(context_or_reading),
            unit=unit,
            range_value=range_value,
            range_unit=range_unit,
            resolution=resolution,
            source_key=source_key,
            metadata=metadata,
        )

    def quantity(
        self,
        context_or_reading: "UncertaintyContext | float",
        registry: AtomRegistry | None = None,
        *,
        unit: str = "",
        range_value: float | None = None,
        range_unit: str | None = None,
        resolution: float | None = None,
        source_key: str | None = None,
        **metadata: Any,
    ) -> Quantity:
        context = self._coerce_context(
            context_or_reading, unit, range_value, range_unit, resolution, source_key, metadata
        )
        return self._build_quantity(context, registry)

    def evaluate(self, context: UncertaintyContext, registry: AtomRegistry | None = None):
        """Return the :class:`UncertaintyBudget` derived from this model."""

        return self._build_quantity(context, registry).budget()


class AccuracySpec(_Evaluable, BaseModel):
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
    distribution: Distribution = Distribution.RECTANGULAR
    coverage_factor: float = Field(1.0, gt=0)
    degrees_of_freedom: float | None = Field(None, gt=0)
    source: str | None = None

    def _std(self, limit: float) -> float:
        return abs(limit) / divisor_for(self.distribution, self.coverage_factor)

    def _build_quantity(self, context: UncertaintyContext, registry: AtomRegistry | None = None) -> Quantity:
        reg = registry or default_registry()
        reading = context.reading
        unit = units.unit_name(context.unit)
        grad: dict[str, float] = {}

        def add_atom(term: str, std: float, sensitivity: float, atom_unit: str | None) -> None:
            if std == 0:
                return
            atom = reg.mint(
                nominal=0.0,
                std_uncertainty=std,
                label=term,
                unit=atom_unit,
                distribution=self.distribution,
                degrees_of_freedom=self.degrees_of_freedom,
                kind=Kind.TYPE_B,
                source=self.source,
                key=_key(context, term),
            )
            grad[atom.uid] = grad.get(atom.uid, 0.0) + sensitivity

        # %reading / fraction / ppm -> dimensionless gain atom, sensitivity = reading.
        reading_fraction = 0.0
        if self.reading_fraction is not None:
            reading_fraction += self.reading_fraction
        if self.reading_percent is not None:
            reading_fraction += self.reading_percent / 100.0
        if self.reading_ppm is not None:
            reading_fraction += self.reading_ppm / 1_000_000.0
        if reading_fraction:
            add_atom("gain", self._std(reading_fraction), reading, "")

        # %range -> additive atom in reading units.
        range_fraction = 0.0
        if self.range_fraction is not None:
            range_fraction += self.range_fraction
        if self.range_percent is not None:
            range_fraction += self.range_percent / 100.0
        if range_fraction:
            if context.range_value is None:
                raise ValueError("range_value is required for range-based uncertainty terms.")
            add_atom("range", self._std(range_fraction * abs(context.range_value)), 1.0, unit)

        if self.offset is not None:
            offset_value = units.convert_units(self.offset, self.offset_unit, context.unit)
            add_atom("offset", self._std(offset_value), 1.0, unit)

        resolution = self.resolution if self.resolution is not None else context.resolution
        if self.counts is not None:
            if resolution is None:
                raise ValueError("resolution is required when counts are used in an accuracy spec.")
            add_atom("counts", self._std(self.counts * resolution), 1.0, unit)

        return Quantity(reading, unit, grad, reg)

    def calculate_std_dev(self, reading_value: float, range_value: float | None = None) -> float:
        """Compatibility helper returning combined standard uncertainty."""

        context = UncertaintyContext(reading=reading_value, range_value=range_value)
        return self.quantity(context, AtomRegistry()).u


class BandAccuracySpec(_Evaluable, BaseModel):
    """Select an accuracy model based on a scalar context value such as frequency."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["band_table"] = "band_table"
    variable: str = "frequency"
    bands: list[dict[str, Any]]

    def _build_quantity(self, context: UncertaintyContext, registry: AtomRegistry | None = None) -> Quantity:
        value = getattr(context, self.variable, None)
        if value is None:
            raise ValueError(f"{self.variable!r} is required for band-table uncertainty.")
        for band in self.bands:
            lower = band.get("min", -math.inf)
            upper = band.get("max", math.inf)
            if lower <= value <= upper:
                spec_data = {k: v for k, v in band.items() if k not in {"min", "max"}}
                return AccuracySpec(**spec_data).quantity(context, registry)
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


class ExpressionAccuracySpec(_Evaluable, BaseModel):
    """Evaluate a constrained mathematical expression as an uncertainty limit."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["expression"] = "expression"
    expression: str
    parameters: dict[str, float] = Field(default_factory=dict)
    distribution: Distribution = Distribution.RECTANGULAR
    coverage_factor: float = Field(1.0, gt=0)

    def _eval(self, node: ast.AST, names: dict[str, float]) -> float:
        if isinstance(node, ast.Expression):
            return self._eval(node.body, names)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
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

    def _build_quantity(self, context: UncertaintyContext, registry: AtomRegistry | None = None) -> Quantity:
        reg = registry or default_registry()
        referenced = self._referenced_names()
        names = dict(self.parameters)
        for name, ctx_field in _EXPRESSION_CONTEXT_VALUES.items():
            ctx_value = getattr(context, ctx_field)
            if name in referenced and name not in names and ctx_value is None:
                raise ValueError(f"{name!r} is required for expression uncertainty.")
            if ctx_value is not None:
                names.setdefault(name, float(ctx_value))
        limit = self._eval(ast.parse(self.expression, mode="eval"), names)
        std = abs(limit) / divisor_for(self.distribution, self.coverage_factor)
        unit = units.unit_name(context.unit)
        grad: dict[str, float] = {}
        if std:
            atom = reg.mint(
                nominal=0.0,
                std_uncertainty=std,
                label="expression",
                unit=unit,
                distribution=self.distribution,
                kind=Kind.TYPE_B,
                key=_key(context, "expression"),
            )
            grad[atom.uid] = 1.0
        return Quantity(context.reading, unit, grad, reg)


class RepeatabilityAccuracySpec(_Evaluable, BaseModel):
    """Type A repeatability model from repeated observations."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["repeatability"] = "repeatability"
    observations: list[float] = Field(min_length=2)
    unit: str | None = None
    use_standard_error: bool = True

    def _build_quantity(self, context: UncertaintyContext, registry: AtomRegistry | None = None) -> Quantity:
        reg = registry or default_registry()
        values = np.asarray(self.observations, dtype=float)
        sigma = float(np.std(values, ddof=1))
        if self.use_standard_error:
            sigma = sigma / math.sqrt(values.size)
        unit = units.unit_name(self.unit or context.unit)
        grad: dict[str, float] = {}
        if sigma:
            atom = reg.mint(
                nominal=0.0,
                std_uncertainty=sigma,
                label="repeatability",
                unit=unit,
                distribution=Distribution.STANDARD,
                degrees_of_freedom=float(values.size - 1),
                kind=Kind.TYPE_A,
                key=_key(context, "repeatability"),
            )
            grad[atom.uid] = 1.0
        return Quantity(context.reading, unit, grad, reg)


class MonteCarloAccuracySpec(_Evaluable, BaseModel):
    """Container of components evaluated jointly by the Monte Carlo engine.

    Analytically (``quantity``) it behaves like a composite of its components.
    The Monte Carlo evaluation lives in :mod:`pytestlab.uncertainty.montecarlo`.
    """

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    model: Literal["monte_carlo"] = "monte_carlo"
    components: list[
        "AccuracySpec | BandAccuracySpec | ExpressionAccuracySpec | RepeatabilityAccuracySpec"
    ]
    samples: int = Field(1_000_000, gt=1)
    seed: int | None = None

    def _build_quantity(self, context: UncertaintyContext, registry: AtomRegistry | None = None) -> Quantity:
        return CompositeBudgetSpec(components=list(self.components)).quantity(context, registry)


LeafAccuracyModel: TypeAlias = (
    AccuracySpec
    | BandAccuracySpec
    | ExpressionAccuracySpec
    | MonteCarloAccuracySpec
    | RepeatabilityAccuracySpec
)


class CompositeBudgetSpec(_Evaluable, BaseModel):
    """Combine multiple uncertainty model outputs into one quantity."""

    model_config = ConfigDict(
        validate_assignment=True, arbitrary_types_allowed=True, extra="forbid"
    )

    model: Literal["composite"] = "composite"
    components: list["LeafAccuracyModel | CompositeBudgetSpec"]

    def _build_quantity(self, context: UncertaintyContext, registry: AtomRegistry | None = None) -> Quantity:
        reg = registry or default_registry()
        merged: dict[str, float] = {}
        unit = units.unit_name(context.unit)
        for model in self.components:
            q = model.quantity(context, reg)
            unit = q.unit or unit
            for uid, g in q.grad.items():
                merged[uid] = merged.get(uid, 0.0) + g
        return Quantity(context.reading, unit, merged, reg)


AccuracyModel: TypeAlias = LeafAccuracyModel | CompositeBudgetSpec

MonteCarloAccuracySpec.model_rebuild()
CompositeBudgetSpec.model_rebuild()


def evaluate_quantity(
    model: AccuracyModel, context: UncertaintyContext, registry: AtomRegistry | None = None
) -> Quantity:
    """Evaluate any supported uncertainty model into a :class:`Quantity`."""

    return model.quantity(context, registry)


def standard_uncertainty_from_model(
    model: AccuracyModel, context: UncertaintyContext
) -> float:
    """Return the combined standard uncertainty for any supported model."""

    return model.quantity(context, AtomRegistry()).u
