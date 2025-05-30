from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional

from .base import Range
from .instrument_config import InstrumentConfig # The Pydantic base

class Timebase(BaseModel):
    range: Range
    horizontal_resolution: float

class Channel(BaseModel):
    description: str
    channel_range: Range
    input_coupling: list[str]
    input_impedance: float
    probe_attenuation: list[int]
    timebase: Timebase # Nested Pydantic model

class Trigger(BaseModel):
    types: list[str]
    modes: list[str]
    slopes: list[str]

class FFT(BaseModel):
    window_types: list[str]
    units: list[str]

class FunctionGenerator(BaseModel):
    waveform_types: list[str]
    supported_states: list[str]
    offset: Range
    frequency: Range
    amplitude: Range

class FRAnalysis(BaseModel):
    sweep_points: Range
    load: list[str]
    trace: list[str]
    mode: list[str]

class OscilloscopeConfig(InstrumentConfig):
    # device_type: str = Field("oscilloscope", const=True) # Handled by loader using device_type from data
    trigger: Trigger
    channels: list[Channel]
    bandwidth: float
    sampling_rate: float
    memory: float # Assuming memory is a float, e.g., points or seconds
    waveform_update_rate: float
    fft: Optional[FFT] = None
    function_generator: Optional[FunctionGenerator] = None
    franalysis: Optional[FRAnalysis] = None
    timebase_settings: Optional[Timebase] = None # Added based on example, adjust if not needed

    # Ensure device_type is present for the loader, but it's inherited from InstrumentConfig
    # The loader will use the 'device_type' from the YAML to pick this model.