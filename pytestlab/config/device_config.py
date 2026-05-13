from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class DeviceConfig(BaseModel):
    """Base configuration for any automatable lab device."""

    model_config = ConfigDict(validate_assignment=True, extra="allow")

    manufacturer: str = Field(..., description="Manufacturer of the device")
    model: str = Field(..., description="Model number or name of the device")
    device_type: str = Field(..., description="Device category used for driver resolution")
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

