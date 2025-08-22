from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .accuracy import AccuracySpec


class InstrumentConfig(BaseModel):
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
    measurement_accuracy: dict[str, AccuracySpec] | None = Field(
        default_factory=dict, description="Measurement accuracy specifications"
    )
    # further complex yaml
    # ------------------------- NEW  (SCPI) ------------------------------ #
    scpi: dict[str, Any] | None = Field(
        default_factory=dict,
        description=(
            "Raw SCPI section copied verbatim from the YAML profile.  "
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
