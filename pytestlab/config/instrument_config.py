from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..uncertainty.specs import AccuracyModel
from .device_config import DeviceConfig


class SCPIParameterSpec(BaseModel):
    """Specification for a single SCPI command parameter."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    name: str = Field(..., description="Parameter name")
    type: str = Field(..., description="Parameter type (e.g., 'int', 'float', 'str', 'enum')")
    required: bool = Field(True, description="Whether this parameter is required")
    description: str | None = Field(None, description="Parameter description")

    # Validation rules
    min_value: float | int | None = Field(None, description="Minimum allowed value")
    max_value: float | int | None = Field(None, description="Maximum allowed value")
    allowed_values: list[Any] | None = Field(None, description="Allowed values for enum types")

    # Default value
    default: Any = Field(None, description="Default parameter value")

    # Units and formatting
    units: str | None = Field(None, description="Parameter units")
    format: str | None = Field(None, description="Parameter format specification")


class SCPICommandSpec(BaseModel):
    """Specification for a single SCPI command."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    template: str | None = Field(None, description="SCPI command template with placeholders")
    sequence: list[str] | None = Field(None, description="Sequence of SCPI commands")

    # Parameter specifications
    parameters: dict[str, SCPIParameterSpec] | None = Field(
        None, description="Parameter specifications for this command"
    )

    # Legacy fields (kept for backward compatibility)
    defaults: dict[str, Any] | None = Field(None, description="Default parameter values")
    validators: dict[str, Any] | None = Field(None, description="Parameter validation rules")
    enums: dict[str, Any] | None = Field(None, description="Enumeration values for parameters")

    response: dict[str, Any] | None = Field(None, description="Response specification")

    # Command metadata
    description: str | None = Field(None, description="Command description")
    category: str | None = Field(
        None, description="Command category (e.g., 'channel', 'trigger', 'acquisition')"
    )
    feature: str | None = Field(None, description="Feature this command belongs to")


class SCPICommandsQueries(BaseModel):
    """SCPI commands and queries specification."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    commands: dict[str, SCPICommandSpec] | None = Field(None, description="SCPI commands")
    queries: dict[str, SCPICommandSpec] | None = Field(None, description="SCPI queries")


class SCPISection(BaseModel):
    """Complete SCPI section specification."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    commands: dict[str, SCPICommandSpec] | None = Field(None, description="SCPI commands")
    queries: dict[str, SCPICommandSpec] | None = Field(None, description="SCPI queries")
    variants: dict[str, SCPICommandsQueries] | None = Field(
        None, description="SCPI command variants"
    )
    default_variant: str | None = Field(None, description="Default variant name")
    feature_mappings: dict[str, dict[str, list[str]]] | None = Field(
        None,
        description="Declarative feature mapping: { feature_name: { required_scpi: [...], optional_scpi: [...] } }",
    )


class InstrumentConfig(DeviceConfig):
    model_config = ConfigDict(validate_assignment=True, extra="ignore")  # Added model_config

    manufacturer: str = Field(..., description="Manufacturer of the instrument")
    model: str = Field(..., description="Model number of the instrument")
    device_type: str = Field(
        ..., description="Type of the device (e.g., 'PSU', 'Oscilloscope')"
    )  # This is used by loader
    serial_number: str | None = Field(None, description="Serial number of the instrument")
    address: str | None = Field(
        None, description="Instrument connection address (e.g., VISA resource string)"
    )  # Example common field
    measurement_accuracy: dict[str, AccuracyModel] | None = Field(
        default_factory=dict, description="Measurement accuracy specifications"
    )
    uncertainty_strict: bool = Field(
        False,
        description=(
            "Raise uncertainty model evaluation errors from drivers instead of logging and "
            "returning the nominal float for backward compatibility."
        ),
    )
    # further complex yaml
    # ------------------------- NEW  (SCPI) ------------------------------ #
    scpi: SCPISection | None = Field(
        None,
        description=(
            "SCPI section with command specifications, aliases, and feature mappings. "
            "Must contain 'commands:' and/or 'queries:' or a 'variants:' block."
        ),
    )

    scpi_variant: str | None = Field(
        None,
        description=(
            "Name of the variant inside scpi.variants to be used with this "
            "instrument.  Leave empty if not using the multi-variant feature."
        ),
    )
