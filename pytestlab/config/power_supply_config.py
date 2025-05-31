"""Pydantic models for Power Supply configuration."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator # Added ConfigDict, model_validator

from pytestlab.config.base import Range # Assuming Range is a Pydantic model
from pytestlab.config.instrument_config import InstrumentConfig
# from ..errors import InstrumentParameterError # For custom validation errors - uncomment if needed


class PowerSupplyChannelConfig(BaseModel):
    """Configuration for a single power supply channel."""
    model_config = ConfigDict(validate_assignment=True, extra='forbid')

    channel_id: int = Field(..., gt=0, description="Channel identifier (e.g., 1, 2)")
    voltage_range: Range = Field(
        ..., description="Programmable voltage range for the channel"
    )
    current_limit_range: Range = Field(
        ..., description="Programmable current limit range for the channel"
    )
    output_enabled_default: bool = Field(
        False, description="Default output state for the channel on initialization"
    )
    # Add other per-channel fields as necessary, e.g.:
    # over_voltage_protection: Optional[float] = Field(None, description="Per-channel Over Voltage Protection setting")
    # over_current_protection: Optional[float] = Field(None, description="Per-channel Over Current Protection setting")


class PowerSupplyConfig(InstrumentConfig):
    """Pydantic model for Power Supply configuration."""
    model_config = ConfigDict(validate_assignment=True, extra='forbid')

    device_type: Literal["power_supply", "PSU"] = Field( # More flexible device_type
        "PSU", description="Device type identifier, must be 'PSU' or 'power_supply'."
    )
    channels: List[PowerSupplyChannelConfig] = Field(
        ..., min_length=1, description="List of power supply channel configurations" # Ensure min_length is appropriate
    )
    over_voltage_protection: Optional[Range] = Field(
        None, description="Global Over Voltage Protection setting for the PSU, if applicable."
    )
    over_current_protection: Optional[Range] = Field(
        None, description="Global Over Current Protection setting for the PSU, if applicable."
    )
    # Add other global PSU settings if any, e.g.:
    # tracking_enabled: Optional[bool] = Field(None, description="Enable/disable channel tracking if supported")

    @model_validator(mode='after')
    def check_channel_ids_unique(self) -> 'PowerSupplyConfig':
        if self.channels:
            ids = [ch.channel_id for ch in self.channels]
            if len(ids) != len(set(ids)):
                raise ValueError("Channel IDs must be unique.")
        return self
