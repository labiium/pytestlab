from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..config.instrument_config import InstrumentConfig

# --- Nested Models for Detailed Specifications ---


class ProgrammingAccuracySpec(BaseModel):
    """Models the programming accuracy specification for a given range."""

    model_config = ConfigDict(extra="forbid")
    percent_of_setting: float
    offset_A: float | None = None
    offset_V: float | None = None
    offset_W: float | None = None
    offset_S: float | None = None


class ReadbackAccuracySpec(BaseModel):
    """Models the readback accuracy specification for a given range."""

    model_config = ConfigDict(extra="forbid")
    percent_of_reading: float
    offset_A: float | None = None
    offset_V: float | None = None
    offset_W: float | None = None

    def calculate_uncertainty(self, reading: float, unit: str) -> float:
        """Calculates the total uncertainty (1-sigma) for a given reading."""
        uncertainty = (self.percent_of_reading / 100.0) * abs(reading)
        offset_map = {"A": self.offset_A, "V": self.offset_V, "W": self.offset_W}
        offset = offset_map.get(unit)
        if offset is not None:
            uncertainty = uncertainty + offset
        return uncertainty


class ModeRangeSpec(BaseModel):
    """Models a single measurement range with its specifications."""

    model_config = ConfigDict(extra="allow")
    name: str
    max_current_A: float | None = None
    max_voltage_V: float | None = None
    range_ohm: str | None = None
    range_W: str | None = None
    programming_accuracy: ProgrammingAccuracySpec
    readback_accuracy: ReadbackAccuracySpec


class ModeSpec(BaseModel):
    """Models the specifications for a single operating mode (e.g., CC, CV)."""

    model_config = ConfigDict(extra="allow")
    ranges: list[ModeRangeSpec]


class OperatingModesSpec(BaseModel):
    """Container for all operating mode specifications."""

    constant_current_CC: ModeSpec
    constant_voltage_CV: ModeSpec
    constant_resistance_CR: ModeSpec
    constant_power_CP: ModeSpec


# --- Data Acquisition and Feature Config Models ---


class DataloggerConfig(BaseModel):
    """Configuration for the datalogger feature."""

    model_config = ConfigDict(extra="forbid")
    default_period_s: float = Field(default=0.2, description="Default sample period in seconds.")
    default_duration_s: float = Field(
        default=30.0, description="Default logging duration in seconds."
    )


class ScopeConfig(BaseModel):
    """Configuration for the scope (digitizer) feature."""

    model_config = ConfigDict(extra="forbid")
    max_points: int = Field(default=131072, description="Maximum number of acquisition points.")
    default_points: int = Field(default=2440, description="Default number of points.")
    min_interval_s: float = Field(default=5.12e-6, description="Fastest possible sample interval.")


class DataAcquisitionConfig(BaseModel):
    """Container for data acquisition feature configurations."""

    model_config = ConfigDict(extra="forbid")
    datalogger: DataloggerConfig = Field(default_factory=DataloggerConfig)
    scope: ScopeConfig = Field(default_factory=ScopeConfig)


# --- Main Config Model ---


class DCActiveLoadConfig(InstrumentConfig):
    """Pydantic model for DC Active Load configuration, parsed from a device spec YAML."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    device_type: Literal["bench_dc_electronic_load", "dc_active_load"]  # type: ignore[assignment]
    general_specifications: dict[str, Any]
    features: list[dict[str, Any]]
    operating_modes: OperatingModesSpec
    data_acquisition: DataAcquisitionConfig = Field(default_factory=DataAcquisitionConfig)
    protection: dict[str, Any]
    other_characteristics_typical: dict[str, Any]
    environmental: dict[str, Any]
