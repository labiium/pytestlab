from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict # Added ConfigDict
from typing import List, Dict, Optional

from .base import Range # Assuming Range might be useful for min/max values
from .instrument_config import InstrumentConfig

class DCALChannel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    description: str = Field(..., description="Channel description or identifier")
    min_current: float = Field(..., ge=0, description="Minimum programmable current for the channel")
    max_current: float = Field(..., gt=0, description="Maximum programmable current for the channel")
    current_resolution: float = Field(..., gt=0, description="Current setting resolution")
    min_voltage: float = Field(..., ge=0, description="Minimum programmable voltage for the channel")
    max_voltage: float = Field(..., gt=0, description="Maximum programmable voltage for the channel")
    voltage_resolution: float = Field(..., gt=0, description="Voltage setting resolution")

class DCALCalibration(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    current_calibration_resolution: float = Field(..., gt=0, description="Resolution for current calibration procedures")
    voltage_calibration_resolution: float = Field(..., gt=0, description="Resolution for voltage calibration procedures")

class DCActiveLoadConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    # device_type is inherited from InstrumentConfig and validated there.
    channels: List[DCALChannel] = Field(..., min_length=1, description="List of DC Active Load channel configurations")
    supported_modes: Dict[str, str] = Field(..., min_length=1, description="Dictionary of supported operating modes (e.g., {'CC': 'Constant Current', 'CV': 'Constant Voltage'})")
    max_current: float = Field(..., gt=0, description="Overall maximum current rating for the instrument")
    max_voltage: float = Field(..., gt=0, description="Overall maximum voltage rating for the instrument")
    max_power: float = Field(..., gt=0, description="Overall maximum power rating for the instrument")
    calibration: Optional[DCALCalibration] = Field(None, description="Calibration-specific parameters, if applicable")
