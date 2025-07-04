from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from typing import List, Dict, Optional, Any, Literal, Union

from ..config.instrument_config import InstrumentConfig

# --- Nested Models for Detailed Specifications ---


class ProgrammingAccuracySpec(BaseModel):
    """Models the programming accuracy specification for a given range."""
    model_config = ConfigDict(extra='forbid')
    percent_of_setting: float
    offset_A: Optional[float] = None
    offset_V: Optional[float] = None
    offset_W: Optional[float] = None
    offset_S: Optional[float] = None


class ReadbackAccuracySpec(BaseModel):
    """Models the readback accuracy specification for a given range."""
    model_config = ConfigDict(extra='forbid')
    percent_of_reading: float
    offset_A: Optional[float] = None
    offset_V: Optional[float] = None
    offset_W: Optional[float] = None

    def calculate_uncertainty(self, reading: float, unit: str) -> float:
        """Calculates the total uncertainty (1-sigma) for a given reading."""
        uncertainty = (self.percent_of_reading / 100.0) * abs(reading)
        offset_map = {'A': self.offset_A, 'V': self.offset_V, 'W': self.offset_W}
        if unit in offset_map and offset_map.get(unit) is not None:
            uncertainty += offset_map[unit]
        return uncertainty


class ModeRangeSpec(BaseModel):
    """Models a single measurement range with its specifications."""
    model_config = ConfigDict(extra='allow')
    name: str
    max_current_A: Optional[float] = None
    max_voltage_V: Optional[float] = None
    range_ohm: Optional[str] = None
    range_W: Optional[str] = None
    programming_accuracy: ProgrammingAccuracySpec
    readback_accuracy: ReadbackAccuracySpec


class ModeSpec(BaseModel):
    """Models the specifications for a single operating mode (e.g., CC, CV)."""
    model_config = ConfigDict(extra='allow')
    ranges: List[ModeRangeSpec]


class OperatingModesSpec(BaseModel):
    """Container for all operating mode specifications."""
    constant_current_CC: ModeSpec
    constant_voltage_CV: ModeSpec
    constant_resistance_CR: ModeSpec
    constant_power_CP: ModeSpec

# --- Main Config Model ---


class DCActiveLoadConfig(InstrumentConfig):
    """Pydantic model for DC Active Load configuration, parsed from a device spec YAML."""
    model_config = ConfigDict(validate_assignment=True, extra='forbid')

    device_type: Literal["bench_dc_electronic_load", "dc_active_load"]
    general_specifications: Dict[str, Any]
    features: List[Dict[str, Any]]
    operating_modes: OperatingModesSpec
    protection: Dict[str, Any]
    other_characteristics_typical: Dict[str, Any]
    environmental: Dict[str, Any]
