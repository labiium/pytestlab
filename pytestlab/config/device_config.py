from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class DeviceRole(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Declared experiment role for a lab resource."""

    MEASUREMENT = "measurement"
    STIMULUS = "stimulus"
    SOURCE_MEASURE = "source_measure"
    LOAD = "load"
    SWITCHING = "switching"
    CONDITIONING = "conditioning"
    DUT_CONTROL = "dut_control"
    FIXTURE = "fixture"
    SAFETY = "safety"
    IDENTITY = "identity"
    METADATA = "metadata"
    CUSTOM = "custom"


class DeviceConfig(BaseModel):
    """Base configuration for any automatable lab device."""

    model_config = ConfigDict(validate_assignment=True, extra="allow")

    manufacturer: str = Field(..., description="Manufacturer of the device")
    model: str = Field(..., description="Model number or name of the device")
    device_type: str = Field(..., description="Device category used for driver resolution")
    role: DeviceRole = Field(..., description="Experiment role this device serves by default")
    protocol: str | None = Field(
        None, description="Documentary protocol metadata; does not affect backend resolution"
    )
    serial_number: str | None = Field(None, description="Serial number of the device")
    address: str | None = Field(None, description="Connection address for the selected backend")
    driver: str | None = Field(None, description="Optional import path for a custom driver class")
    config_model: str | None = Field(
        None, description="Optional import path for a custom Pydantic config model"
    )
    backend: dict[str, Any] | None = Field(
        None, description="Optional backend specification for direct device profiles"
    )


class GenericDeviceConfig(DeviceConfig):
    """Permissive config model for custom devices without a dedicated schema."""
