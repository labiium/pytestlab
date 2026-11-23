from __future__ import annotations

import math
from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from .config import BaseConfig


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


class DeviceConfig(BaseConfig):
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
    transport: dict[str, Any] = Field(
        default_factory=dict, description="Profile message timing and framing requirements"
    )

    backend: dict[str, Any] | None = Field(
        None, description="Optional backend specification for direct device profiles"
    )

    @model_validator(mode="before")
    @classmethod
    def reject_removed_pacing(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            for settings in (value, value.get("motion"), value.get("switch")):
                if isinstance(settings, Mapping) and "command_pacing_s" in settings:
                    raise ValueError(
                        "command_pacing_s was removed; use transport.min_command_interval_s"
                    )
        return value

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, value: dict[str, Any]) -> dict[str, Any]:
        numeric = {"min_command_interval_s", "query_delay_s"}
        allowed = numeric | {
            "read_termination",
            "write_termination",
            "message_io",
            "success_token",
            "success_prefix",
            "success_pattern",
        }
        if set(value) - allowed:
            raise ValueError(f"Unknown transport settings: {sorted(set(value) - allowed)}")
        for key in numeric & set(value):
            item = value[key]
            if (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
                or item < 0
            ):
                raise ValueError(f"transport.{key} must be finite and non-negative")
        if (
            "read_termination" in value
            and value["read_termination"] is not None
            and not isinstance(value["read_termination"], str)
        ):
            raise ValueError("transport.read_termination must be a string or null")
        message_io = value.get("message_io", {})
        if not isinstance(message_io, Mapping):
            raise ValueError("transport.message_io must be a mapping")
        unknown = set(message_io) - {"read_termination", "write_termination"}
        if unknown:
            raise ValueError(f"Unknown transport.message_io settings: {sorted(unknown)}")
        for location, settings in (("transport", value), ("transport.message_io", message_io)):
            item = settings.get("write_termination")
            if item is not None and (
                not isinstance(item, str) or item not in ("", "\n", "\r", "\r\n")
            ):
                raise ValueError(
                    f"{location}.write_termination must be null, empty, LF, CR, or CRLF"
                )
        return value


class GenericDeviceConfig(DeviceConfig):
    """Permissive config model for custom devices without a dedicated schema."""
