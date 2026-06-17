"""
Configuration model for Waveform Generator instruments.

This module defines the configuration structure for arbitrary waveform generators,
including SCPI command requirements for various features and capabilities.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from ..uncertainty.specs import AccuracyModel
from ..uncertainty.specs import AccuracySpec as AccuracySpec
from .instrument_config import InstrumentConfig

# RangeSpec will be defined in this file


class RangeSpec(BaseModel):
    """Specification for a range with accuracy information."""

    model_config = {"arbitrary_types_allowed": True}

    # Support both formats for backward compatibility
    min: float | None = Field(None, description="Minimum range value")
    max: float | None = Field(None, description="Maximum range value")
    min_val: float | None = Field(None, description="Minimum range value (legacy format)")
    max_val: float | None = Field(None, description="Maximum range value (legacy format)")

    units: str | None = Field(None, description="Units for the range values")

    resolution: float | None = Field(None, description="Resolution for this range")

    accuracy: AccuracyModel | None = Field(
        None, description="Accuracy specification for this range"
    )

    def __init__(self, **data):
        super().__init__(**data)
        # Handle legacy min_val/max_val format
        if self.min is None and self.min_val is not None:
            self.min = self.min_val
        if self.max is None and self.max_val is not None:
            self.max = self.max_val

    def assert_in_range(self, x: float, name: str = "value") -> float:
        """Assert that a value is within the range."""
        min_v = self.min
        max_v = self.max
        if min_v is None or max_v is None:
            return x
        if not (min_v <= x <= max_v):
            from ..errors import InstrumentParameterError

            raise InstrumentParameterError(
                parameter=name,
                value=x,
                valid_range=(self.min, self.max),
                message=f"{name} must be between {self.min} and {self.max}.",
            )
        return x


class WaveformSpec(BaseModel):
    """Specification for waveform generation capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    built_in: list[str] = Field(
        default_factory=list,
        description="List of built-in waveform types supported by the instrument",
    )

    arbitrary: ArbitraryWaveformSpec | None = Field(
        None, description="Arbitrary waveform generation specifications"
    )

    # SCPI command requirements for waveform functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for waveform generation (e.g., ['set_function', 'set_frequency', 'set_amplitude'])",
    )


class ArbitraryWaveformSpec(BaseModel):
    """Specification for arbitrary waveform capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    max_length: int | None = Field(
        None, description="Maximum number of points for arbitrary waveforms"
    )

    sampling_rate: RangeSpec | None = Field(None, description="Supported sampling rate range")

    memory_size: int | None = Field(None, description="Total memory size in points")

    # SCPI command requirements for arbitrary waveform functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for arbitrary waveform functionality (e.g., ['select_arbitrary_waveform', 'set_arbitrary_waveform_sample_rate'])",
    )


class ChannelSpec(BaseModel):
    """Specification for a single channel."""

    model_config = {"arbitrary_types_allowed": True}

    description: str = Field(..., description="Channel description")

    frequency_range: RangeSpec = Field(..., description="Frequency range supported by this channel")

    amplitude_range: RangeSpec = Field(..., description="Amplitude range supported by this channel")

    offset_range: RangeSpec = Field(..., description="Offset range supported by this channel")

    phase_range: RangeSpec | None = Field(None, description="Phase range supported by this channel")

    # SCPI command requirements for channel functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for channel functionality (e.g., ['set_function', 'set_frequency', 'set_amplitude'])",
    )


class ModulationSpec(BaseModel):
    """Specification for modulation capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    am_depth_range: RangeSpec | None = Field(None, description="AM depth range in percentage")

    fm_deviation_range: RangeSpec | None = Field(None, description="FM deviation range in Hz")

    # SCPI command requirements for modulation functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for modulation functionality (e.g., ['enable_modulation', 'set_am_depth', 'set_fm_deviation'])",
    )


class SweepSpec(BaseModel):
    """Specification for frequency sweep capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    time_range: RangeSpec | None = Field(None, description="Sweep time range in seconds")

    frequency_range: RangeSpec | None = Field(None, description="Sweep frequency range in Hz")

    # SCPI command requirements for sweep functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for sweep functionality (e.g., ['enable_sweep', 'set_sweep_time', 'set_sweep_start_frequency'])",
    )


class BurstSpec(BaseModel):
    """Specification for burst mode capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    cycles_range: RangeSpec | None = Field(None, description="Burst cycles range")

    period_range: RangeSpec | None = Field(None, description="Burst period range in seconds")

    # SCPI command requirements for burst functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for burst functionality (e.g., ['enable_burst', 'set_burst_mode', 'set_burst_cycles'])",
    )


class TriggerSpec(BaseModel):
    """Specification for trigger capabilities."""

    model_config = {"arbitrary_types_allowed": True}

    sources: list[str] | None = Field(None, description="Available trigger sources")

    slopes: list[str] | None = Field(None, description="Available trigger slopes")

    # SCPI command requirements for trigger functionality
    required_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for trigger functionality (e.g., ['set_trigger_source', 'set_trigger_slope', 'trigger_now'])",
    )


class WaveformGeneratorConfig(InstrumentConfig):
    """Configuration for Waveform Generator instruments."""

    model_config = {"arbitrary_types_allowed": True}

    device_type: Literal["waveform_generator"] = Field(
        "waveform_generator", description="Type of the device (waveform_generator)"
    )

    channels: list[ChannelSpec] = Field(..., description="Channel specifications")

    waveforms: WaveformSpec = Field(..., description="Waveform generation capabilities")

    modulation: ModulationSpec | None = Field(None, description="Modulation capabilities")

    sweep: SweepSpec | None = Field(None, description="Frequency sweep capabilities")

    burst: BurstSpec | None = Field(None, description="Burst mode capabilities")

    trigger: TriggerSpec | None = Field(None, description="Trigger capabilities")

    # Core SCPI command requirements
    core_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for core functionality (e.g., ['set_output_state', 'set_voltage_unit', 'set_load_impedance'])",
    )

    output_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for output functionality (e.g., ['set_output_polarity', 'set_sync_output_state'])",
    )

    sync_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for synchronization functionality (e.g., ['set_sync_output_mode', 'set_sync_output_polarity'])",
    )

    memory_scpi_commands: list[str] = Field(
        default_factory=list,
        description="Required SCPI command aliases for memory management (e.g., ['list_directory', 'delete_file_or_folder'])",
    )
