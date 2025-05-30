from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

from .base import Range # Assuming Range might be useful for min/max values
from .instrument_config import InstrumentConfig

class DCALChannel(BaseModel):
    description: str
    min_current: float
    max_current: float
    current_resolution: float
    min_voltage: float
    max_voltage: float
    voltage_resolution: float

class DCALCalibration(BaseModel):
    current_calibration_resolution: float
    voltage_calibration_resolution: float

class DCActiveLoadConfig(InstrumentConfig):
    # device_type: str = Field("dc_active_load", const=True) # Handled by loader
    # channels is a list of dictionaries in the original, mapping int to config.
    # Pydantic prefers a list of models, or a dict if keys are meaningful and consistent.
    # If channel numbers (keys) are always sequential and 0-indexed, a List[DCALChannel] is fine.
    # If channel numbers can be arbitrary (e.g., 1, 2, 5), then Dict[int, DCALChannel] is better.
    # For simplicity and common Pydantic patterns, using List[DCALChannel] and assuming
    # the loader or user will ensure the list corresponds to channels in order.
    # If the original structure `channels: [{1: {...}}, {2: {...}}]` must be preserved,
    # this would need a more complex custom type or validator.
    # The prompt implies `channels: list` where each item is a dict with a channel number as key.
    # This is unusual for Pydantic. A list of channel objects is more standard.
    # Let's assume the data will be transformed to a list of DCALChannel objects before validation,
    # or the YAML structure will be `channels: [ {description:...}, {description:...} ]`
    channels: List[DCALChannel]
    supported_modes: Dict[str, str] # e.g., {"CC": "Constant Current"}
    max_current: float
    max_voltage: float
    max_power: float
    calibration: Optional[DCALCalibration] = None
