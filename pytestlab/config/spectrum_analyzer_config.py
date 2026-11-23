from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .instrument_config import InstrumentConfig


class SpectrumTraceReadback(BaseModel):
    """Model-specific ASCII trace shape and standard spectrum mode tokens."""

    model_config = ConfigDict(extra="forbid")
    layout: Literal["interleaved_xy", "split_xy"]
    mode_values: tuple[str, ...] = Field(min_length=1)
    max_points: int = Field(gt=0, le=1_000_000)


class SpectrumSingleSweep(BaseModel):
    """How the profile verifies a passive, single, trace-updating measurement."""

    model_config = ConfigDict(extra="forbid")
    sweep_guard: Literal["active_trace_types", "sweep_count"]


class SpectrumRFInput(BaseModel):
    """Validated option identifiers for the bundled internal RF preamp."""

    model_config = ConfigDict(extra="forbid")
    preamp_options: tuple[str, ...] = Field(min_length=1)
    external_frontend_option: str | None = None


class SpectrumAnalyzerConfig(InstrumentConfig):
    """Spectrum-analyzer center/span, bandwidth, level, and attenuation profile."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    device_type: Literal["spectrum_analyzer", "SA"] = "spectrum_analyzer"
    trace_readback: SpectrumTraceReadback | None = None
    single_sweep: SpectrumSingleSweep | None = None
    rf_input: SpectrumRFInput | None = None
    sweep_control: Literal["keysight", "fsw"] | None = None
    trace_setup: bool = False
    markers: Literal["keysight", "fsw"] | None = None

    frequency_center: float | None = Field(None, description="Center frequency in Hz")
    frequency_span: float | None = Field(None, description="Frequency span in Hz")
    resolution_bandwidth: float | None = Field(None, description="Resolution bandwidth in Hz (RBW)")
    reference_level: float | None = Field(None, description="Reference level in dBm")
    attenuation: float | None = Field(None, description="Input attenuation in dB")
