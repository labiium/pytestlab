from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from .accuracy import AccuracySpec

class InstrumentConfig(BaseModel):
    manufacturer: str
    model: str
    device_type: str # This is used by loader, ensure it's part of the data loaded
    serial_number: str | None = None
    address: str | None = None # Example common field
    measurement_accuracy: Optional[dict[str, AccuracySpec]] = Field(default_factory=dict, description="Measurement accuracy specifications")
    # ... other common fields ...