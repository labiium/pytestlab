from pydantic import Field, ConfigDict
from typing import Literal, Optional
from .instrument_config import InstrumentConfig
# Assuming Range is a Pydantic model, it's in .base
# from .base import Range # Not used in the example provided, but good to keep in mind

class SpectrumAnalyzerConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    device_type: Literal["spectrum_analyzer", "SA"] = "spectrum_analyzer"
    
    # Basic trace grab related fields
    frequency_center: Optional[float] = Field(None, description="Center frequency in Hz")
    frequency_span: Optional[float] = Field(None, description="Frequency span in Hz")
    resolution_bandwidth: Optional[float] = Field(None, description="Resolution bandwidth in Hz (RBW)")
    reference_level: Optional[float] = Field(None, description="Reference level in dBm")
    attenuation: Optional[float] = Field(None, description="Input attenuation in dB")
    # Add other common fields like reference_level, attenuation etc. if desired for basic setup
    # Added reference_level and attenuation as per the comment.