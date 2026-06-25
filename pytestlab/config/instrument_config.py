from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..uncertainty.metrology import CalibrationCertificate
from ..uncertainty.specs import AccuracyModel
from .device_config import DeviceConfig
from .scpi_schema import SCPIParameterSpec as CanonicalSCPIParameterSpec

SCPIParameterSpec = CanonicalSCPIParameterSpec


class SCPICommandSpec(BaseModel):
    """Specification for a single SCPI command."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    template: str | None = Field(None, description="SCPI command template with placeholders")
    sequence: list[str] | None = Field(None, description="Sequence of SCPI commands")

    # Parameter specifications
    parameters: dict[str, CanonicalSCPIParameterSpec] | None = Field(
        None, description="Canonical parameter metadata for this command"
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
    calibration_certificates: list[CalibrationCertificate] = Field(
        default_factory=list,
        description=(
            "Structured calibration certificates used to resolve metrological "
            "traceability for uncertainty atoms. Missing or non-matching entries "
            "leave results explicitly non-report-grade."
        ),
    )
    uncertainty_strict: bool = Field(
        True,
        description=(
            "Raise uncertainty model evaluation errors from drivers. Set false only for "
            "explicit exploratory sessions that prefer nominal-only reads over fail-loud "
            "profile validation."
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
