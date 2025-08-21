from typing import Literal

from pydantic import ConfigDict
from pydantic import Field

from .instrument_config import InstrumentConfig

# Assuming Range is a Pydantic model, it's in .base
# from .base import Range # Not used in the example provided, but good to keep in mind


class SpectrumAnalyzerConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    device_type: Literal["spectrum_analyzer", "SA"] = "spectrum_analyzer"
    
    # Basic trace grab related fields
    frequency_center: float | None = Field(None, description="Center frequency in Hz")
    frequency_span: float | None = Field(None, description="Frequency span in Hz")
    resolution_bandwidth: float | None = Field(None, description="Resolution bandwidth in Hz (RBW)")
    reference_level: float | None = Field(None, description="Reference level in dBm")
    attenuation: float | None = Field(None, description="Input attenuation in dB")
    # Add other common fields like reference_level, attenuation etc. if desired for basic setup
    # Added reference_level and attenuation as per the comment.