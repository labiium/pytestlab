"""
Configuration model for Multimeter instruments.

This module defines the configuration structure for digital multimeters,
including SCPI command requirements for various features and capabilities.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

from .accuracy import AccuracySpec
from .instrument_config import InstrumentConfig

# RangeSpec will be defined in this file


class RangeSpec(BaseModel):
    """Specification for a range with accuracy information."""

    model_config = {"arbitrary_types_allowed": True}

    min: float = Field(..., description="Minimum range value")

    max: float = Field(..., description="Maximum range value")

    units: str = Field(..., description="Units for the range values")

    resolution: float | None = Field(None, description="Resolution for this range")

    accuracy: AccuracySpec | None = Field(None, description="Accuracy specification for this range")

    def assert_in_range(self, x: float, name: str = "value") -> float:
        """Assert that a value is within the range."""
        if not (self.min <= x <= self.max):
            from ..errors import InstrumentParameterError

            raise InstrumentParameterError(
                parameter=name,
                value=x,
                valid_range=(self.min, self.max),
                message=f"{name} must be between {self.min} and {self.max}.",
            )
        return x


class DMMFunction(BaseModel):
    """Enumeration of DMM measurement functions."""

    model_config = {"arbitrary_types_allowed": True}

    # DC measurements
    VOLTAGE_DC: str = Field("VOLT:DC", description="DC Voltage measurement")
    CURRENT_DC: str = Field("CURR:DC", description="DC Current measurement")

    # AC measurements
    VOLTAGE_AC: str = Field("VOLT:AC", description="AC Voltage measurement")
    CURRENT_AC: str = Field("CURR:AC", description="AC Current measurement")

    # Resistance measurements
    RESISTANCE: str = Field("RES", description="2-wire Resistance measurement")
    FRESISTANCE: str = Field("FRES", description="4-wire Resistance measurement")

    # Other measurements
    CAPACITANCE: str = Field("CAP", description="Capacitance measurement")
    FREQUENCY: str = Field("FREQ", description="Frequency measurement")
    TEMPERATURE: str = Field("TEMP", description="Temperature measurement")
    DIODE: str = Field("DIOD", description="Diode test")
    CONTINUITY: str = Field("CONT", description="Continuity test")


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
