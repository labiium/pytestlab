from pydantic import BaseModel, ConfigDict
from typing import List, Dict, Optional
from enum import Enum

class HealthStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"

class HealthReport(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    status: HealthStatus = HealthStatus.UNKNOWN
    instrument_idn: Optional[str] = None
    errors: List[str] = []
    warnings: List[str] = []
    supported_features: Dict[str, bool] = {}
    backend_status: Optional[str] = None # e.g., "Simulated", "VISA Connected", "Lamb Connected"
    # Can add more fields like firmware_version, serial_number from IDN