"""
Configuration model for DC Active Load instruments.

This module defines the configuration structure for DC electronic loads,
including SCPI command requirements for various features and capabilities.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

from .accuracy import AccuracySpec
from .instrument_config import InstrumentConfig

# RangeSpec is defined in this file


class RangeSpec(BaseModel):
    """Specification for a range with accuracy information."""

    model_config = {"arbitrary_types_allowed": True}

    nominal: float = Field(..., description="Nominal range value")

    max_current_A: float | None = Field(None, description="Maximum current in Amperes")

    max_voltage_V: float | None = Field(None, description="Maximum voltage in Volts")

    max_power_W: float | None = Field(None, description="Maximum power in Watts")

    readback_accuracy: ReadbackAccuracySpec | None = Field(
        None, description="Readback accuracy specification"
    )

    def assert_in_range(self, x: float, name: str = "value") -> float:
        """Assert that a value is within the range."""
        # For DC active load, we use nominal as the reference point
        # This is a simplified check - in practice, you might want more sophisticated validation
        if self.max_current_A is not None and x > self.max_current_A:
            from ..errors import InstrumentParameterError

            raise InstrumentParameterError(
                parameter=name,
                value=x,
                valid_range=(0, self.max_current_A),
                message=f"{name} must be between 0 and {self.max_current_A}.",
            )
        return x


class ReadbackAccuracySpec(BaseModel):
    """Specification for readback accuracy."""

    model_config = {"arbitrary_types_allowed": True}

    voltage_accuracy: AccuracySpec | None = Field(None, description="Voltage readback accuracy")

    current_accuracy: AccuracySpec | None = Field(None, description="Current readback accuracy")

    power_accuracy: AccuracySpec | None = Field(None, description="Power readback accuracy")


class ModeSpec(BaseModel):
    """Specification for an operating mode."""

    model_config = {"arbitrary_types_allowed": True}

    ranges: list[RangeSpec] = Field(
        default_factory=list, description="Available ranges for this mode"
    )

    # SCPI command requirements for this mode
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for this mode (e.g., ['set_mode', 'set_load'])",
    )


class OperatingModesSpec(BaseModel):
    """Specification for all operating modes."""

    model_config = {"arbitrary_types_allowed": True}

    constant_current_CC: ModeSpec | None = Field(
        None, description="Constant Current mode specifications"
    )

    constant_voltage_CV: ModeSpec | None = Field(
        None, description="Constant Voltage mode specifications"
    )

    constant_power_CP: ModeSpec | None = Field(
        None, description="Constant Power mode specifications"
    )

    constant_resistance_CR: ModeSpec | None = Field(
        None, description="Constant Resistance mode specifications"
    )

    # SCPI command requirements for mode switching
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for mode switching (e.g., ['set_mode', 'set_load'])",
    )


class TransientSpec(BaseModel):
    """Specification for transient capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    supported_modes: list[str] | None = Field(
        None,
        description="Supported transient modes (e.g., ['CONTinuous', 'PULSe', 'TOGGle', 'LIST'])",
    )

    time_range: RangeSpec | None = Field(None, description="Transient time range")

    # SCPI command requirements for transient functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for transient functionality (e.g., ['transient_set_mode', 'transient_set_level', 'transient_start'])",
    )


class BatteryTestSpec(BaseModel):
    """Specification for battery testing capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    voltage_cutoff_range: RangeSpec | None = Field(None, description="Voltage cutoff range")

    capacity_cutoff_range: RangeSpec | None = Field(None, description="Capacity cutoff range in Ah")

    timer_cutoff_range: RangeSpec | None = Field(None, description="Timer cutoff range in seconds")

    # SCPI command requirements for battery testing
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for battery testing (e.g., ['battery_enable', 'battery_cutoff_voltage', 'battery_cutoff_capacity'])",
    )


class DataAcquisitionSpec(BaseModel):
    """Specification for data acquisition capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    scope_points: int | None = Field(None, description="Number of scope data points")

    datalogger_points: int | None = Field(None, description="Number of datalogger points")

    # SCPI command requirements for data acquisition
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for data acquisition (e.g., ['fetch_array', 'fetch_datalogger'])",
    )


class DCActiveLoadConfig(InstrumentConfig):
    """Configuration for DC Active Load instruments."""

    model_config = {"arbitrary_types_allowed": True}

    operating_modes: OperatingModesSpec = Field(..., description="Operating mode specifications")

    transient: TransientSpec | None = Field(None, description="Transient capabilities")

    battery_test: BatteryTestSpec | None = Field(None, description="Battery testing capabilities")

    data_acquisition: DataAcquisitionSpec | None = Field(
        None, description="Data acquisition capabilities"
    )

    # Core SCPI command requirements
    core_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for core functionality (e.g., ['set_input_state', 'get_input_state'])",
    )

    input_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for input functionality (e.g., ['set_input_state', 'input_short_state'])",
    )

    slew_rate_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for slew rate functionality (e.g., ['mode_set_slew', 'mode_set_range'])",
    )

    measurement_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for measurement functionality (e.g., ['measure', 'mode_get_range'])",
    )
