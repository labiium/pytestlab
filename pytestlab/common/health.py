from enum import Enum

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

__all__ = ["HealthReport", "HealthStatus"]


class HealthStatus(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Overall health state reported by a device or instrument."""

    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class HealthReport(BaseModel):
    """Structured identity, error, feature, and backend health snapshot."""

    model_config = ConfigDict(validate_assignment=True)
    status: HealthStatus = HealthStatus.UNKNOWN
    instrument_idn: str | None = None
    errors: list[str] = []
    warnings: list[str] = []
    supported_features: dict[str, bool] = {}
    backend_status: str | None = None  # e.g., "Simulated", "VISA Connected", "Lamb Connected"
    status_byte: int | None = None
    status_flags: dict[str, bool] = Field(default_factory=dict)
    # Can add more fields like firmware_version, serial_number from IDN
