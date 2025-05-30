from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional

from .base import Range
from .instrument_config import InstrumentConfig

class AWGAccuracy(BaseModel):
    amplitude: float
    frequency: float

class AWGChannelConfig(BaseModel):
    description: str
    frequency: Range
    amplitude: Range
    dc_offset: Range
    accuracy: AWGAccuracy

class ArbitraryWaveformConfig(BaseModel):
    memory: float
    max_length: float
    sampling_rate: Range
    resolution: int

class WaveformsConfig(BaseModel):
    built_in: List[str]
    arbitrary: ArbitraryWaveformConfig

class WaveformGeneratorConfig(InstrumentConfig):
    # device_type: str = Field("waveform_generator", const=True) # Handled by loader
    channels: List[AWGChannelConfig]
    waveforms: WaveformsConfig
