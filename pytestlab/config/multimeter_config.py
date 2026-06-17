"""
Configuration model for Multimeter instruments.

This module defines the configuration structure for digital multimeters,
including SCPI command requirements for various features and capabilities.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel
from pydantic import Field

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


class DMMFunction(Enum):
    """Enumeration of DMM measurement functions."""

    # DC measurements
    VOLTAGE_DC = "VOLT:DC"
    CURRENT_DC = "CURR:DC"

    # AC measurements
    VOLTAGE_AC = "VOLT:AC"
    CURRENT_AC = "CURR:AC"

    # Resistance measurements
    RESISTANCE = "RES"
    FRESISTANCE = "FRES"

    # Other measurements
    CAPACITANCE = "CAP"
    FREQUENCY = "FREQ"
    TEMPERATURE = "TEMP"
    DIODE = "DIOD"
    CONTINUITY = "CONT"


class FunctionSpec(BaseModel):
    """Specification for a measurement function."""

    model_config = {"arbitrary_types_allowed": True}

    ranges: list[RangeSpec] = Field(
        default_factory=list, description="Available ranges for this function"
    )

    # SCPI command requirements for this function
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for this function (e.g., ['set_function', 'set_range', 'set_resolution'])",
    )


class MeasurementFunctionsSpec(BaseModel):
    """Specification for all measurement functions."""

    model_config = {"arbitrary_types_allowed": True}

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

    # SCPI command requirements for function switching
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for function switching (e.g., ['set_function', 'set_range'])",
    )


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
        description="Required SCPI command aliases for measurement functionality (e.g., ['configure', 'initiate', 'fetch', 'read'])",
    )

    configuration_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for configuration functionality (e.g., ['set_range', 'set_resolution', 'set_integration_time'])",
    )

    status_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for status functionality (e.g., ['get_status', 'get_errors', 'get_operation_complete'])",
    )
