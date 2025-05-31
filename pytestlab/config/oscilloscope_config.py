from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict # Added ConfigDict
from typing import List, Optional

from .base import Range
from .instrument_config import InstrumentConfig # The Pydantic base

class Timebase(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    range: Range = Field(..., description="Timebase range settings")
    horizontal_resolution: float = Field(..., description="Horizontal resolution")

class Channel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    description: str = Field(..., description="Channel description")
    channel_range: Range = Field(..., description="Vertical range of the channel")
    input_coupling: List[str] = Field(..., min_length=1, description="Supported input coupling types (e.g., AC, DC, GND)")
    input_impedance: float = Field(..., description="Input impedance in Ohms")
    probe_attenuation: List[int] = Field(..., min_length=1, description="Supported probe attenuation factors (e.g., 1, 10)")
    timebase: Timebase # Nested Pydantic model

class Trigger(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    types: List[str] = Field(..., min_length=1, description="Supported trigger types (e.g., Edge, Pulse, Runt)")
    modes: List[str] = Field(..., min_length=1, description="Supported trigger modes (e.g., Auto, Normal, Single)")
    slopes: List[str] = Field(..., min_length=1, description="Supported trigger slopes (e.g., Rising, Falling, Either)")

class FFT(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    window_types: List[str] = Field(..., min_length=1, description="Supported FFT window types (e.g., Hanning, Flattop)")
    units: List[str] = Field(..., min_length=1, description="Supported FFT units (e.g., dBV, Vrms)")

class FunctionGenerator(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    waveform_types: List[str] = Field(..., min_length=1, description="Supported waveform types (e.g., Sine, Square)")
    supported_states: List[str] = Field(..., min_length=1, description="Supported states (e.g., ON, OFF)")
    offset: Range = Field(..., description="Offset range")
    frequency: Range = Field(..., description="Frequency range")
    amplitude: Range = Field(..., description="Amplitude range")

class FRAnalysis(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    sweep_points: Range = Field(..., description="Range for number of sweep points")
    load: List[str] = Field(..., min_length=1, description="Supported load impedance values for FRA")
    trace: List[str] = Field(..., min_length=1, description="Supported trace types for FRA (e.g., Gain, Phase)")
    mode: List[str] = Field(..., min_length=1, description="Supported FRA modes (e.g., Bode, Impedance)")

class OscilloscopeConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    # device_type is inherited from InstrumentConfig and validated there.
    trigger: Trigger = Field(..., description="Trigger system configuration")
    channels: List[Channel] = Field(..., min_length=1, description="List of channel configurations")
    bandwidth: float = Field(..., gt=0, description="Analog bandwidth of the oscilloscope in Hz")
    sampling_rate: float = Field(..., gt=0, description="Maximum sampling rate in Samples/sec")
    memory: float = Field(..., gt=0, description="Maximum memory depth (e.g., in points or seconds)")
    waveform_update_rate: float = Field(..., gt=0, description="Waveform update rate in waveforms/sec")
    fft: Optional[FFT] = Field(None, description="FFT capabilities, if available")
    function_generator: Optional[FunctionGenerator] = Field(None, description="Integrated function generator capabilities, if available")
    franalysis: Optional[FRAnalysis] = Field(None, description="Frequency Response Analysis capabilities, if available")
    timebase_settings: Optional[Timebase] = Field(None, description="Global timebase settings, if applicable beyond per-channel")

    # The loader will use the 'device_type' from the YAML to pick this model.