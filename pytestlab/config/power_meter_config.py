from pydantic import Field, ConfigDict
from typing import Literal, Optional
from .instrument_config import InstrumentConfig

class PowerMeterConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    device_type: Literal["power_meter", "PM"] = "power_meter"
    
    # Basic power reading related fields
    frequency_compensation_value: Optional[float] = Field(None, description="Frequency for sensor compensation in Hz")
    averaging_count: Optional[int] = Field(None, description="Number of readings to average for a measurement")
    power_units: Literal["dBm", "W", "mW", "uW"] = Field("dBm", description="Units for power measurement")
    # Potentially add channel specific configurations if the power meter supports multiple sensors/channels
    # For now, keeping it simple as per initial instructions.