"""
Configuration model for Power Supply instruments.

This module defines the configuration structure for programmable power supplies,
including SCPI command requirements for various features and capabilities.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

from .accuracy import AccuracyModel
from .accuracy import AccuracySpec as AccuracySpec
from .instrument_config import InstrumentConfig

# RangeSpec will be defined in this file


class RangeSpec(BaseModel):
    """Specification for a range with accuracy information."""

    model_config = {"arbitrary_types_allowed": True}

    # Support both formats for backward compatibility
    min: float | None = Field(None, description="Minimum range value")
    max: float | None = Field(None, description="Maximum range value")
    min_val: float | None = Field(None, description="Minimum range value (legacy format)")
    max_val: float | None = Field(None, description="Maximum range value (legacy format)")

    units: str | None = Field(None, description="Units for the range values")

    resolution: float | None = Field(None, description="Resolution for this range")

    accuracy: AccuracyModel | None = Field(
        None, description="Accuracy specification for this range"
    )

    def __init__(self, **data):
        super().__init__(**data)
        # Handle legacy min_val/max_val format
        if self.min is None and self.min_val is not None:
            self.min = self.min_val
        if self.max is None and self.max_val is not None:
            self.max = self.max_val

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


class ChannelSpec(BaseModel):
    """Specification for a single power supply channel."""

    model_config = {"arbitrary_types_allowed": True}

    description: str = Field(..., description="Channel description")

    voltage_range: RangeSpec = Field(..., description="Voltage range supported by this channel")

    current_limit_range: RangeSpec = Field(
        ..., description="Current limit range supported by this channel"
    )

    power_limit: float | None = Field(None, description="Maximum power limit in Watts")

    slew_rate_range: RangeSpec | None = Field(None, description="Slew rate range in V/s")

    # SCPI command requirements for channel functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for channel functionality (e.g., ['set_voltage', 'set_current', 'set_slew_rate'])",
    )


class ProtectionSpec(BaseModel):
    """Specification for protection features."""

    model_config = {"arbitrary_types_allowed": True}

    overvoltage_protection: bool = Field(
        False, description="Whether overvoltage protection is available"
    )

    overcurrent_protection: bool = Field(
        False, description="Whether overcurrent protection is available"
    )

    overtemperature_protection: bool = Field(
        False, description="Whether overtemperature protection is available"
    )

    # SCPI command requirements for protection functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for protection functionality (e.g., ['set_ovp_level', 'set_ocp_level'])",
    )


class MeasurementSpec(BaseModel):
    """Specification for measurement capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    voltage_accuracy: AccuracyModel | None = Field(None, description="Voltage measurement accuracy")

    current_accuracy: AccuracyModel | None = Field(None, description="Current measurement accuracy")

    power_accuracy: AccuracyModel | None = Field(None, description="Power measurement accuracy")

    # SCPI command requirements for measurement functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for measurement functionality (e.g., ['measure_voltage', 'measure_current', 'measure_power'])",
    )


class CommunicationSpec(BaseModel):
    """Specification for communication features."""

    model_config = {"arbitrary_types_allowed": True}

    remote_sensing: bool = Field(False, description="Whether remote sensing is supported")

    parallel_operation: bool = Field(False, description="Whether parallel operation is supported")

    series_operation: bool = Field(False, description="Whether series operation is supported")

    # SCPI command requirements for communication functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for communication functionality (e.g., ['set_remote_sensing', 'set_parallel_mode'])",
    )


class PowerSupplyConfig(InstrumentConfig):
    """Configuration for Power Supply instruments."""

    model_config = {"arbitrary_types_allowed": True}
    device_type: str = "power_supply"

    channels: list[ChannelSpec] = Field(..., description="Channel specifications")

    protection: ProtectionSpec | None = Field(None, description="Protection features")

    measurement: MeasurementSpec | None = Field(None, description="Measurement capabilities")

    communication: CommunicationSpec | None = Field(None, description="Communication features")

    # Core SCPI command requirements
    core_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for core functionality (e.g., ['set_output', 'set_display', 'reset'])",
    )

    output_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for output functionality (e.g., ['set_output_state', 'get_output_state'])",
    )

    safety_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for safety functionality (e.g., ['set_voltage_limit', 'set_current_limit'])",
    )
