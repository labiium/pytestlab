from __future__ import annotations
from .instrument_config import InstrumentConfig
from typing import Literal

class VirtualInstrumentConfig(InstrumentConfig):
    """Pydantic model for the Virtual Instrument configuration."""
    device_type: Literal["virtual_instrument"] = "virtual_instrument"