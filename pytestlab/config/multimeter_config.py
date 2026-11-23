"""
Configuration model for Multimeter instruments.

This module defines the configuration structure for digital multimeters,
including SCPI command requirements for various features and capabilities.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from ..uncertainty.specs import AccuracyModel
from ..uncertainty.specs import AccuracySpec as AccuracySpec
from .instrument_config import InstrumentConfig

# RangeSpec will be defined in this file


class RangeSpec(BaseModel):
    """Specification for a range with accuracy information."""

    model_config = {"arbitrary_types_allowed": True}

    # Support the actual profile structure
    nominal_V: float | None = Field(None, description="Nominal voltage range value")
    nominal_A: float | None = Field(None, description="Nominal current range value")
    nominal_ohm: float | None = Field(None, description="Nominal resistance range value")
    nominal_F: float | None = Field(None, description="Nominal capacitance range value")

    # Legacy support for generic min/max fields
    min: float | None = Field(None, description="Minimum range value")
    max: float | None = Field(None, description="Maximum range value")
    min_val: float | None = Field(None, description="Minimum range value (legacy format)")
    max_val: float | None = Field(None, description="Maximum range value (legacy format)")

    units: str | None = Field(None, description="Units for the range values")

    resolution: float | None = Field(None, description="Resolution for this range")

    accuracy: AccuracyModel | None = Field(
        None, description="Accuracy specification for this range"
    )
    typical_accuracy: AccuracyModel | None = Field(
        None, description="Typical accuracy when provided instead of 'accuracy'"
    )
    accuracy_45Hz_10kHz: AccuracyModel | None = Field(
        None, description="AC accuracy specification for 45 Hz to 10 kHz"
    )
    accuracy_45Hz_1kHz: AccuracyModel | None = Field(
        None, description="AC accuracy specification for 45 Hz to 1 kHz"
    )

    # Additional fields that might be present in profiles
    test_current_A: float | None = Field(
        None, description="Test current for resistance measurements"
    )
    temp_coeff_per_C: dict[str, float] | None = Field(
        None, description="Temperature coefficient per degree Celsius"
    )

    def __init__(self, **data):
        super().__init__(**data)
        # Handle legacy min_val/max_val format
        if self.min is None and self.min_val is not None:
            self.min = self.min_val
        if self.max is None and self.max_val is not None:
            self.max = self.max_val
        # Normalize alternate accuracy fields into 'accuracy'
        if self.accuracy is None:
            if getattr(self, "typical_accuracy", None) is not None:
                self.accuracy = self.typical_accuracy
            elif getattr(self, "accuracy_45Hz_10kHz", None) is not None:
                self.accuracy = self.accuracy_45Hz_10kHz
            elif getattr(self, "accuracy_45Hz_1kHz", None) is not None:
                self.accuracy = self.accuracy_45Hz_1kHz

    def assert_in_range(self, x: float, name: str = "value") -> float:
        """Assert that a value is within the range."""
        min_v = self.min
        max_v = self.max
        if min_v is None or max_v is None:
            return x
        if not (min_v <= x <= max_v):
            from ..errors import InstrumentParameterError

            raise InstrumentParameterError(
                parameter=name,
                value=x,
                valid_range=(self.min, self.max),
                message=f"{name} must be between {self.min} and {self.max}.",
            )
        return x


class MeasurementFunctionTransport(BaseModel):
    """Private profile mapping used by the driver for one measurement function."""

    model_config = ConfigDict(extra="forbid")

    function_token: str = Field(
        ..., description="Instrument transport value used for this function"
    )
    response_tokens: list[str] = Field(
        default_factory=list,
        description="Additional profile-declared tokens that identify this function in readback",
    )
    measure_alias: str = Field(
        ...,
        description=(
            "Private SCPI query alias for this function. Use a no-argument alias "
            "for functions that do not accept generic range/resolution settings."
        ),
    )


class FunctionSpec(BaseModel):
    """Profile capability and uncertainty specification for one function.

    ``id`` is the YAML mapping key (for example ``dc_voltage``). ``transport``
    contains the instrument-specific value; it deliberately does not live in
    the public semantic enum.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    label: str | None = Field(None, description="Human-readable function label")
    description: str | None = Field(None, description="What this function measures")
    aliases: list[str] = Field(
        default_factory=list, description="User-facing aliases accepted for this function"
    )
    unit: str | None = Field(None, description="Canonical result unit")
    transport: MeasurementFunctionTransport | None = Field(
        None, description="Profile-specific transport mapping"
    )

    ranges: list[RangeSpec] = Field(
        default_factory=list, description="Available ranges with accuracy information"
    )

    # SCPI command requirements for this function
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for this function (typically ['measure'])",
    )


class MeasurementFunctionsSpec(BaseModel):
    """Profile-declared measurement capabilities for a multimeter."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    dc_voltage: FunctionSpec | None = Field(
        None, description="DC Voltage measurement specifications"
    )

    ac_voltage: FunctionSpec | None = Field(
        None, description="AC Voltage measurement specifications"
    )

    dc_current: FunctionSpec | None = Field(
        None, description="DC Current measurement specifications"
    )

    ac_current: FunctionSpec | None = Field(
        None, description="AC Current measurement specifications"
    )

    resistance: FunctionSpec | None = Field(
        None, description="2-wire Resistance measurement specifications"
    )

    resistance_4wire: FunctionSpec | None = Field(
        None, description="4-wire Resistance measurement specifications"
    )

    capacitance: FunctionSpec | None = Field(
        None, description="Capacitance measurement specifications"
    )

    frequency: FunctionSpec | None = Field(None, description="Frequency measurement specifications")

    temperature: FunctionSpec | None = Field(
        None, description="Temperature measurement specifications"
    )

    diode: FunctionSpec | None = Field(None, description="Diode-test specifications")

    continuity: FunctionSpec | None = Field(None, description="Continuity-test specifications")

    @model_validator(mode="after")
    def _coerce_custom_function_specs(self) -> MeasurementFunctionsSpec:
        """Parse custom functions and reject ambiguous semantic IDs or aliases."""

        extras = self.model_extra or {}
        for name, value in extras.items():
            if isinstance(value, dict):
                extras[name] = FunctionSpec.model_validate(value)
        seen: dict[str, str] = {}
        for function_id, spec in self.function_specs():
            for alias in (function_id, *spec.aliases):
                normalized = _normalise_function_key(alias)
                previous = seen.get(normalized)
                if previous is not None and previous != function_id:
                    raise ValueError(
                        f"ambiguous measurement function alias {alias!r} for "
                        f"{previous!r} and {function_id!r}"
                    )
                seen[normalized] = function_id
        return self

    # SCPI command requirements for function switching
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for measurement operations (typically ['measure'])",
    )

    def function_specs(self) -> list[tuple[str, FunctionSpec]]:
        """Return all declared function specs, including custom YAML keys."""

        specs: list[tuple[str, FunctionSpec]] = []
        for name in type(self).model_fields:
            if name == "required_scpi_commands":
                continue
            value = getattr(self, name, None)
            if isinstance(value, FunctionSpec):
                specs.append((name, value))
        for name, value in (self.model_extra or {}).items():
            if isinstance(value, FunctionSpec):
                specs.append((name, value))
        return specs

    def function_spec(self, function_id: str) -> FunctionSpec | None:
        """Return one function specification by its YAML key."""

        wanted = _normalise_function_key(str(function_id))
        for name, spec in self.function_specs():
            if _normalise_function_key(name) == wanted:
                return spec
        return None

    def function_for_transport_token(self, token: str) -> tuple[str, FunctionSpec] | None:
        """Resolve a device-reported function token to its semantic profile entry.

        The device token is deliberately interpreted only through the profile.  A
        driver must not infer measurement families from vendor-specific prefixes.
        """

        wanted = token.strip().upper()
        for function_id, spec in self.function_specs():
            transport = spec.transport
            if transport is not None:
                tokens = (transport.function_token, *transport.response_tokens)
                if any(candidate.strip().upper() == wanted for candidate in tokens):
                    return function_id, spec
        return None


def _normalise_function_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class TriggerSpec(BaseModel):
    """Specification for trigger capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    sources: list[str] | None = Field(
        None, description="Available trigger sources (e.g., ['IMM', 'EXT', 'BUS'])"
    )

    delays: RangeSpec | None = Field(None, description="Trigger delay range")

    # SCPI command requirements for trigger functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for trigger functionality (e.g., ['set_trigger_source', 'set_trigger_delay'])",
    )


class SamplingSpec(BaseModel):
    """Specification for sampling capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    sample_rate: RangeSpec | None = Field(None, description="Sample rate range")

    buffer_size: int | None = Field(None, description="Buffer size for continuous sampling")

    # SCPI command requirements for sampling functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for sampling functionality (e.g., ['set_sample_rate', 'set_buffer_size'])",
    )


class CalibrationSpec(BaseModel):
    """Specification for calibration capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    self_calibration: bool = Field(False, description="Whether self-calibration is supported")

    external_calibration: bool = Field(
        False, description="Whether external calibration is supported"
    )

    calibration_interval: int | None = Field(
        None, description="Recommended calibration interval in days"
    )

    # SCPI command requirements for calibration functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for calibration functionality (e.g., ['calibrate', 'calibration_status'])",
    )


class MultimeterConfig(InstrumentConfig):
    """Configuration for Multimeter instruments."""

    model_config = {"arbitrary_types_allowed": True}
    device_type: str = "multimeter"

    measurement_functions: MeasurementFunctionsSpec | None = Field(
        None, description="Measurement function specifications"
    )

    trigger: TriggerSpec | None = Field(None, description="Trigger capabilities")

    sampling: SamplingSpec | None = Field(None, description="Sampling capabilities")

    calibration: CalibrationSpec | None = Field(None, description="Calibration capabilities")

    # Core SCPI command requirements
    core_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for core functionality (e.g., ['identify', 'reset', 'clear'])",
    )

    measurement_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for measurement functionality (typically ['measure'])",
    )

    configuration_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Optional low-level configuration aliases; measurement selection is handled by measure()",
    )

    status_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for status functionality (e.g., ['get_status', 'get_errors', 'get_operation_complete'])",
    )
