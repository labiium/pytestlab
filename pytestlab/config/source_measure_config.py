"""Declarative configuration models for source-measure units."""

from __future__ import annotations

import math
import numbers

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from .instrument_config import InstrumentConfig


class SourceMeasureRange(BaseModel):
    """Finite static rating for a source or compliance parameter."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    min: float
    max: float
    units: str
    resolution: float | None = None

    @field_validator("min", "max", "resolution", mode="before")
    @classmethod
    def _reject_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("source-measure range values must be numeric, not bool")
        return value

    @field_validator("min", "max", "resolution")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("source-measure ranges must be finite")
        return value

    @field_validator("max")
    @classmethod
    def _ordered(cls, value: float, info) -> float:
        minimum = info.data.get("min")
        if minimum is not None and value < minimum:
            raise ValueError("range max must be greater than or equal to min")
        return value


class SourceMeasureChannelSpec(BaseModel):
    """Static capabilities for one source-measure channel."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    channel_id: int = Field(..., ge=1)
    description: str
    voltage_range: SourceMeasureRange
    current_range: SourceMeasureRange
    current_limit_range: SourceMeasureRange
    voltage_compliance_range: SourceMeasureRange
    required_scpi_commands: list[str] = Field(default_factory=list)

    @field_validator("channel_id", mode="before")
    @classmethod
    def _strict_channel_id(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, numbers.Integral):
            raise ValueError("channel_id must be an integer")
        return value

    @model_validator(mode="after")
    def _validate_units(self) -> SourceMeasureChannelSpec:
        expected = {
            "voltage_range": "V",
            "voltage_compliance_range": "V",
            "current_range": "A",
            "current_limit_range": "A",
        }
        for field_name, unit in expected.items():
            actual = getattr(self, field_name).units
            if actual != unit:
                raise ValueError(f"{field_name} units must be {unit!r}, got {actual!r}")
        if self.current_limit_range.min < 0:
            raise ValueError("Current-limit ranges must be non-negative magnitudes")
        return self


class SourceMeasureConfig(InstrumentConfig):
    """Profile contract consumed by the generic :class:`SourceMeasure` driver."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)
    device_type: str = "source_measure"
    # Empty means the modular instrument's installed cards are not known yet;
    # actuation remains unavailable until qualified channel data is supplied.
    channels: list[SourceMeasureChannelSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_channel_ids(self) -> SourceMeasureConfig:
        ids = [channel.channel_id for channel in self.channels]
        if len(ids) != len(set(ids)):
            raise ValueError("source-measure channel_id values must be unique")
        return self
