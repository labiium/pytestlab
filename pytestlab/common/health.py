from enum import Enum

from pydantic import BaseModel
from pydantic import ConfigDict


class HealthStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class HealthReport(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    status: HealthStatus = HealthStatus.UNKNOWN
    instrument_idn: str | None = None
    errors: list[str] = []
    warnings: list[str] = []
    supported_features: dict[str, bool] = {}
    backend_status: str | None = None  # e.g., "Simulated", "VISA Connected", "Lamb Connected"
    # Can add more fields like firmware_version, serial_number from IDN
