from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict # Added ConfigDict
from typing import List, Optional, Literal

from .base import Range
from .instrument_config import InstrumentConfig

class AWGAccuracy(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    amplitude: float = Field(..., description="Amplitude accuracy specification (e.g., percentage or absolute value)")
    frequency: float = Field(..., description="Frequency accuracy specification (e.g., ppm or Hz)")

class AWGChannelConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    description: str = Field(..., description="Channel description or identifier")
    frequency: Range = Field(..., description="Programmable frequency range for the channel")
    amplitude: Range = Field(..., description="Programmable amplitude range for the channel")
    dc_offset: Range = Field(..., description="Programmable DC offset range for the channel")
    accuracy: AWGAccuracy = Field(..., description="Accuracy specifications for this channel")

class ArbitraryWaveformConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    memory: float = Field(..., description="Arbitrary waveform memory size (e.g., in points or bytes)")
    max_length: float = Field(..., description="Maximum length of a single arbitrary waveform segment (in points)")
    sampling_rate: Range = Field(..., description="Programmable sampling rate range for arbitrary waveforms")
    resolution: int = Field(..., gt=0, description="Vertical resolution for arbitrary waveforms in bits")

class WaveformsConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    built_in: List[str] = Field(..., min_length=1, description="List of available built-in waveform shapes (e.g., SINE, SQUARE)")
    arbitrary: ArbitraryWaveformConfig = Field(..., description="Configuration for arbitrary waveform capabilities")

class WaveformGeneratorConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    # device_type is inherited from InstrumentConfig and validated there.
    device_type: Literal["AWG", "waveform_generator"] = Field("waveform_generator", description="Type of the device (e.g., 'AWG', 'waveform_generator')")
    channels: List[AWGChannelConfig] = Field(..., min_length=1, description="List of waveform generator channel configurations")
    waveforms: WaveformsConfig = Field(..., description="Waveform capabilities configuration")
