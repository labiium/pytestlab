from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional

from .instrument_config import InstrumentConfig
# Assuming Range might be needed for some parameters, if not, it can be removed.
from .base import Range 

class DMMConfiguration(BaseModel):
    current: List[str] # Or a more specific type if current settings are complex
    voltage: List[str] # Or a more specific type
    resolution: List[str] # Or specific float values

class MultimeterConfig(InstrumentConfig):
    # device_type: str = Field("multimeter", const=True) # Handled by loader
    resolution: float # General resolution, specific might be in DMMConfiguration
    max_voltage: float
    max_resistance: float
    max_current: float
    max_capacitance: float
    max_frequency: float
    configuration: DMMConfiguration
    # channels: Optional[List[int]] = None # If multimeters can have multiple channels like other instruments