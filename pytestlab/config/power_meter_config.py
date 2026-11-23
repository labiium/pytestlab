from typing import Literal

from pydantic import ConfigDict
from pydantic import Field

from .instrument_config import InstrumentConfig


class PowerMeterConfig(InstrumentConfig):
    """Power-meter compensation, averaging, and measurement-unit profile."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    device_type: Literal["power_meter", "PM"] = "power_meter"

    power_condition_bits: dict[int, str] = Field(
        default_factory=dict, description="Diagnostic labels for non-clearing power condition bits"
    )
    calibration_condition_bits: dict[int, str] = Field(
        default_factory=dict, description="Diagnostic labels for non-clearing calibration bits"
    )

    # Basic power reading related fields
    frequency_compensation_value: float | None = Field(
        None, description="Frequency for sensor compensation in Hz"
    )
    averaging_count: int | None = Field(
        None, description="Number of readings to average for a measurement"
    )
    power_units: Literal["dBm", "W", "mW", "uW"] = Field(
        "dBm", description="Units for power measurement"
    )
    # Potentially add channel specific configurations if the power meter supports multiple sensors/channels
    # For now, keeping it simple as per initial instructions.
