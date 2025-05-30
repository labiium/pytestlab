from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional

from .base import Range
from .instrument_config import InstrumentConfig

class Accuracy(BaseModel):
    voltage: float
    current: float

class OutputChannel(BaseModel):
    description: str
    voltage: Range
    current: Range
    accuracy: Accuracy

class PowerSupplyConfig(InstrumentConfig):
    # device_type: str = Field("power_supply", const=True) # Handled by loader
    channels: List[OutputChannel]
    total_power: float
    line_regulation: float
    load_regulation: float
    # programming_accuracy: Optional[Accuracy] = None # If these are separate from per-channel accuracy
    # readback_accuracy: Optional[Accuracy] = None
    # interfaces: Optional[List[str]] = None
    # remote_control: Optional[List[str]] = None
