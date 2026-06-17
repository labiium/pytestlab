from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from uncertainties.core import UFloat

from .experiments.results import MeasurementResult
from .uncertainty import Quantity as MeasurementQuantity
from .uncertainty.specs import AccuracyModel
from .uncertainty.specs import UncertaintyContext
from .uncertainty.specs import evaluate_quantity as evaluate_uncertainty_model


class AccessorySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str | None = None
    retrieved: str | None = None
    notes: str | None = None


class AccessoryCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    operation: Literal["multiply", "divide", "add", "subtract"]
    nominal: float
    unit: str = ""
    uncertainty: AccuracyModel | None = None
    coverage_factor_note: str | None = None
    source: str | None = None
    range_value: float | None = None
    range_unit: str | None = None
    resolution: float | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_ambiguous_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            ambiguous = {
                "tolerance_percent",
                "percent_tolerance",
                "percent_reading",
                "attenuation",
                "attenuation_tolerance_percent",
            } & set(data)
            if ambiguous:
                names = ", ".join(sorted(ambiguous))
                raise ValueError(
                    f"Ambiguous accessory correction field(s) are not allowed: {names}. "
                    "Use nominal plus an explicit AccuracyModel uncertainty block."
                )
        return data


class AccessoryProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accessory_type: str
    manufacturer: str | None = None
    model: str
    description: str | None = None
    review_status: Literal["reviewed", "template", "draft"] = "draft"
    required_parameters: list[str] = Field(default_factory=list)
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)
    compatibility: dict[str, Any] = Field(default_factory=dict)
    sources: list[AccessorySource] = Field(default_factory=list)
    corrections: list[AccessoryCorrection] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_reviewed_sources(self) -> AccessoryProfile:
        if self.review_status == "reviewed" and not self.sources:
            raise ValueError("reviewed accessory presets must include source metadata.")
        return self

    @classmethod
    def from_config(cls, key: str) -> AccessoryProfile:
        """Load a packaged accessory preset by key, never a local path."""

        if Path(key).suffix in {".yaml", ".yml"} or Path(key).is_absolute():
            raise ValueError("AccessoryProfile.from_config() accepts packaged preset keys only.")
        profiles_dir = _accessory_profiles_dir().resolve()
        path = (profiles_dir / key).with_suffix(".yaml").resolve()
        try:
            path.relative_to(profiles_dir)
        except ValueError as exc:
            raise ValueError("AccessoryProfile.from_config() preset keys cannot escape presets.") from exc
        if not path.is_file():
            raise FileNotFoundError(f"Accessory preset '{key}' not found at '{path}'.")
        return cls._load_yaml(path)

    @classmethod
    def from_file(cls, path: str | Path) -> AccessoryProfile:
        """Load a local lab accessory profile from a YAML file."""

        profile_path = Path(path)
        if profile_path.suffix not in {".yaml", ".yml"}:
            raise ValueError("AccessoryProfile.from_file() requires a YAML file path.")
        if not profile_path.is_file():
            raise FileNotFoundError(f"Accessory profile file '{profile_path}' not found.")
        return cls._load_yaml(profile_path)

    @classmethod
    def _load_yaml(cls, path: Path) -> AccessoryProfile:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Accessory profile '{path}' must contain a YAML mapping.")
        return cls.model_validate(data)

    def with_parameters(self, **parameters: float | str | bool) -> AccessoryProfile:
        merged = dict(self.parameters)
        merged.update(parameters)
        profile = self.model_copy(update={"parameters": merged})
        profile.validate_parameters()
        return profile

    def validate_parameters(self) -> None:
        missing = [name for name in self.required_parameters if name not in self.parameters]
        if missing:
            raise ValueError(
                f"Accessory profile {self.display_name} requires parameter(s): "
                + ", ".join(sorted(missing))
            )

    @property
    def display_name(self) -> str:
        prefix = f"{self.manufacturer} " if self.manufacturer else ""
        return f"{prefix}{self.model}".strip()


class BoundAccessory(BaseModel):
    """A profile bound to a bench.yaml accessory alias and provenance."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    profile: AccessoryProfile
    profile_key: str | None = None
    profile_file: str | None = None
    serial_number: str | None = None
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)
    notes: str | None = None

    @classmethod
    def from_profile(cls, profile: AccessoryProfile, *, alias: str | None = None) -> BoundAccessory:
        return cls(alias=alias or profile.display_name, profile=profile)

    def validate_parameters(self) -> None:
        self.profile.validate_parameters()

    @property
    def display_name(self) -> str:
        return self.profile.display_name

    @property
    def accessory_type(self) -> str:
        return self.profile.accessory_type

    @property
    def corrections(self) -> list[AccessoryCorrection]:
        return self.profile.corrections

    @property
    def review_status(self) -> str:
        return self.profile.review_status

    @property
    def sources(self) -> list[AccessorySource]:
        return self.profile.sources

    def envelope_metadata(self) -> dict[str, Any]:
        source_kind = "profile" if self.profile_key is not None else "file" if self.profile_file else None
        return {
            "alias": self.alias,
            "display_name": self.display_name,
            "accessory_type": self.accessory_type,
            "profile_key": self.profile_key,
            "profile_file": self.profile_file,
            "profile_source": source_kind,
            "serial_number": self.serial_number,
            "parameters": dict(self.parameters),
            "notes": self.notes,
            "review_status": self.profile.review_status,
            "sources": [source.model_dump(mode="json") for source in self.profile.sources],
        }


class ChainStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accessory: str
    correction: str
    operation: str
    nominal: float
    unit: str
    source: str | None = None


def accessory_correction_quantity(
    correction: AccessoryCorrection,
    *,
    accessory: AccessoryProfile | BoundAccessory,
    registry=None,
) -> MeasurementQuantity:
    """Convert an accessory correction into a :class:`Quantity`.

    The correction's uncertainty atoms get a stable identity per accessory and
    correction name, so reusing the same physical accessory correlates correctly.
    """

    if correction.uncertainty is None:
        return MeasurementQuantity.constant(correction.nominal, correction.unit, registry)
    context = UncertaintyContext(
        reading=correction.nominal,
        unit=correction.unit,
        range_value=correction.range_value,
        range_unit=correction.range_unit,
        resolution=correction.resolution,
        source_key=f"accessory:{accessory.display_name}:{correction.name}",
        metadata={"accessory": accessory.display_name, "correction": correction.name},
    )
    return evaluate_uncertainty_model(correction.uncertainty, context, registry)


class MeasurementChain:
    """Explicit accessory correction chain using MeasurementQuantity arithmetic."""

    def __init__(self, accessories: list[AccessoryProfile | BoundAccessory]):
        self.accessories = [
            accessory
            if isinstance(accessory, BoundAccessory)
            else BoundAccessory.from_profile(accessory)
            for accessory in accessories
        ]
        for accessory in self.accessories:
            accessory.validate_parameters()

    def apply(self, result: Any) -> Any:
        if isinstance(result, MeasurementResult):
            quantity, instrument_budget_missing = self._quantity_from_value(
                result.values, unit=result.units
            )
            corrected = self._apply_quantity(quantity)
            envelope = dict(getattr(result, "envelope", {}) or {})
            envelope["measurement_chain"] = self.envelope(
                instrument_budget_missing=instrument_budget_missing
            )
            return MeasurementResult(
                values=corrected,
                instrument=result.instrument,
                units=corrected.unit or result.units,
                measurement_type=result.measurement_type,
                timestamp=result.timestamp,
                envelope=envelope,
                sampling_rate=getattr(result, "sampling_rate", None),
            )

        quantity, _instrument_budget_missing = self._quantity_from_value(result, unit="")
        return self._apply_quantity(quantity)

    def describe(self, *, name: str | None = None, physical_path: list[str] | None = None) -> str:
        lines: list[str] = []
        if name:
            lines.append(name)
        if physical_path:
            lines.append(f"  Physical path: {' -> '.join(physical_path)}")
        for accessory in self.accessories:
            lines.append(f"  Accessory: {accessory.display_name} ({accessory.accessory_type})")
            for correction in accessory.corrections:
                lines.append(
                    f"    Correction: {correction.operation} by {correction.nominal:g} "
                    f"{correction.unit}".rstrip()
                )
                if correction.coverage_factor_note:
                    lines.append(f"    Coverage: {correction.coverage_factor_note}")
        return "\n".join(lines)

    def envelope(self, *, instrument_budget_missing: bool) -> dict[str, Any]:
        return {
            "version": 1,
            "instrument_budget_status": (
                "missing_float_fallback" if instrument_budget_missing else "included"
            ),
            "instrument_budget_note": (
                "instrument contributed no uncertainty budget"
                if instrument_budget_missing
                else "instrument uncertainty budget preserved"
            ),
            "steps": [step.model_dump(mode="json") for step in self.steps()],
            "accessories": [
                accessory.envelope_metadata()
                for accessory in self.accessories
            ],
        }

    def steps(self) -> list[ChainStep]:
        steps: list[ChainStep] = []
        for accessory in self.accessories:
            for correction in accessory.corrections:
                steps.append(
                    ChainStep(
                        accessory=accessory.display_name,
                        correction=correction.name,
                        operation=correction.operation,
                        nominal=correction.nominal,
                        unit=correction.unit,
                        source=correction.source,
                    )
                )
        return steps

    def _apply_quantity(self, quantity: MeasurementQuantity) -> MeasurementQuantity:
        corrected = quantity
        for accessory in self.accessories:
            for correction in accessory.corrections:
                operand = accessory_correction_quantity(
                    correction, accessory=accessory, registry=corrected.registry
                )
                if correction.operation == "multiply":
                    corrected = corrected * operand
                elif correction.operation == "divide":
                    corrected = corrected / operand
                elif correction.operation == "add":
                    corrected = corrected + operand
                elif correction.operation == "subtract":
                    corrected = corrected - operand
                else:  # pragma: no cover - pydantic enforces this
                    raise NotImplementedError(correction.operation)
        return corrected

    def _quantity_from_value(self, value: Any, *, unit: str) -> tuple[MeasurementQuantity, bool]:
        if isinstance(value, MeasurementQuantity):
            return value, False
        if isinstance(value, UFloat):
            from .uncertainty import default_registry

            reg = default_registry()
            atom = reg.mint(
                nominal=float(value.nominal_value),
                std_uncertainty=float(value.std_dev),
                label="legacy_ufloat",
                unit=unit,
                source="legacy_ufloat",
            )
            return MeasurementQuantity.from_atom(atom, reg), False
        if isinstance(value, np.ndarray):
            raise TypeError("MeasurementChain.apply() is scalar-only in v1; arrays are unsupported.")
        try:
            nominal = float(value)
        except Exception as exc:
            raise TypeError(f"MeasurementChain.apply() cannot handle value type {type(value)!r}.") from exc
        return MeasurementQuantity.constant(nominal, unit), True


def _accessory_profiles_dir() -> Path:
    return Path(__file__).parent / "profiles" / "accessories"
