from pydantic import Field, ConfigDict
from typing import Literal, Optional, List
from .instrument_config import InstrumentConfig
# from .base import Range # Not used for now

class VNAConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    device_type: Literal["vna", "VNA", "vector_network_analyzer"] = "vna"
    
    # Basic S-parameter grab related fields
    s_parameters: List[str] = Field(default_factory=lambda: ["S11", "S21"], description="List of S-parameters to measure (e.g., ['S11', 'S21'])")
    start_frequency: Optional[float] = Field(None, description="Start frequency for the sweep in Hz")
    stop_frequency: Optional[float] = Field(None, description="Stop frequency for the sweep in Hz")
    num_points: Optional[int] = Field(None, description="Number of points in the sweep")
    if_bandwidth: Optional[float] = Field(None, description="IF bandwidth in Hz")
    power_level: Optional[float] = Field(None, description="Source power level in dBm")