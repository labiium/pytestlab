from __future__ import annotations

from typing import Literal

from pydantic import BaseModel  # Added ConfigDict
from pydantic import ConfigDict  # Added ConfigDict
from pydantic import Field  # Added ConfigDict

from .base import Range
from .instrument_config import InstrumentConfig  # The Pydantic base


class Timebase(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    range: Range = Field(..., description="Timebase range settings")
    horizontal_resolution: float = Field(..., description="Horizontal resolution")


class Channel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    description: str = Field(..., description="Channel description")
    channel_range: Range = Field(..., description="Vertical range of the channel")
    input_coupling: list[str] = Field(
        ..., min_length=1, description="Supported input coupling types (e.g., AC, DC, GND)"
    )
    input_impedance: float = Field(..., description="Input impedance in Ohms")
    probe_attenuation: list[int] = Field(
        ..., min_length=1, description="Supported probe attenuation factors (e.g., 1, 10)"
    )
    timebase: Timebase  # Nested Pydantic model


class Trigger(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    types: list[str] = Field(
        ..., min_length=1, description="Supported trigger types (e.g., Edge, Pulse, Runt)"
    )
    modes: list[str] = Field(
        ..., min_length=1, description="Supported trigger modes (e.g., Auto, Normal, Single)"
    )
    slopes: list[str] = Field(
        ..., min_length=1, description="Supported trigger slopes (e.g., Rising, Falling, Either)"
    )


class FFT(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    window_types: list[str] = Field(
        ..., min_length=1, description="Supported FFT window types (e.g., Hanning, Flattop)"
    )
    units: list[str] = Field(..., min_length=1, description="Supported FFT units (e.g., dBV, Vrms)")

    # SCPI command requirements for FFT functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for FFT functionality (e.g., ['fft_display', 'fft_source'])",
    )


class FunctionGenerator(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    waveform_types: list[str] = Field(
        ..., min_length=1, description="Supported waveform types (e.g., Sine, Square)"
    )
    supported_states: list[str] = Field(
        ..., min_length=1, description="Supported states (e.g., ON, OFF)"
    )
    offset: Range = Field(..., description="Offset range")
    frequency: Range = Field(..., description="Frequency range")
    amplitude: Range = Field(..., description="Amplitude range")

    # SCPI command requirements for function generator functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for function generator functionality (e.g., ['wgen_output', 'wgen_set_func'])",
    )


class FRAnalysis(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    sweep_points: Range = Field(..., description="Range for number of sweep points")
    load: list[str] = Field(
        ..., min_length=1, description="Supported load impedance values for FRA"
    )
    trace: list[str] = Field(
        ..., min_length=1, description="Supported trace types for FRA (e.g., Gain, Phase)"
    )
    mode: list[str] = Field(
        ..., min_length=1, description="Supported FRA modes (e.g., Bode, Impedance)"
    )

    # SCPI command requirements for FRA functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for FRA functionality (e.g., ['fran_enable', 'fran_fetch'])",
    )


class OscilloscopeConfig(InstrumentConfig):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    device_type: Literal["oscilloscope"] = Field(
        "oscilloscope", description="Type of the device (oscilloscope)"
    )
    # device_type is inherited from InstrumentConfig and validated there.
    trigger: Trigger = Field(..., description="Trigger system configuration")
    channels: list[Channel] = Field(..., min_length=1, description="List of channel configurations")
    bandwidth: float = Field(..., gt=0, description="Analog bandwidth of the oscilloscope in Hz")
    sampling_rate: float = Field(..., gt=0, description="Maximum sampling rate in Samples/sec")
    memory: float = Field(
        ..., gt=0, description="Maximum memory depth (e.g., in points or seconds)"
    )
    waveform_update_rate: float = Field(
        ..., gt=0, description="Waveform update rate in waveforms/sec"
    )
    fft: FFT | None = Field(None, description="FFT capabilities, if available")
    function_generator: FunctionGenerator | None = Field(
        None, description="Integrated function generator capabilities, if available"
    )
    franalysis: FRAnalysis | None = Field(
        None, description="Frequency Response Analysis capabilities, if available"
    )
    timebase_settings: Timebase | None = Field(
        None, description="Global timebase settings, if applicable beyond per-channel"
    )

    # Core oscilloscope functionality SCPI requirements
    core_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for core oscilloscope functionality (e.g., ['acquire_points', 'set_channel_axis'])",
    )

    # Channel-specific SCPI requirements
    channel_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for channel operations (e.g., ['channel_display', 'probe_set'])",
    )

    # Trigger-specific SCPI requirements
    trigger_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for trigger operations (e.g., ['configure_trigger', 'trigger_level'])",
    )

    # Acquisition-specific SCPI requirements
    acquisition_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for acquisition operations (e.g., ['acq_set_type', 'digitize'])",
    )

    # Waveform-specific SCPI requirements
    waveform_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for waveform operations (e.g., ['wave_data', 'wave_preamble'])",
    )

    # The loader will use the 'device_type' from the YAML to pick this model.
