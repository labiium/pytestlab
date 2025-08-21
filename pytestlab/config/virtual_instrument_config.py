from __future__ import annotations

from typing import Literal

from .instrument_config import InstrumentConfig


class VirtualInstrumentConfig(InstrumentConfig):
    """Pydantic model for the Virtual Instrument configuration."""
    device_type: Literal["virtual_instrument"] = "virtual_instrument"