from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .instrument_config import InstrumentConfig


class ImpedanceReadbackSpec(BaseModel):
    """Finite readback strategies; no profile-controlled acquisition scripts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    encoding: Literal["complex_arrays", "polar_point"]
    checks: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    magnitude_limit_ohm: float = Field(gt=0)


class ImpedanceSweepSpec(BaseModel):
    """Documented sweep transport dialect and static operating bounds."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    dialect: Literal["e4990a", "im3570"]
    min_frequency_hz: float = Field(gt=0)
    max_frequency_hz: float = Field(gt=0)
    max_points: int = Field(ge=2, le=1601)
    max_segments: int | None = Field(default=None, ge=1, le=201)
    max_excitation_v_rms: float | None = Field(default=None, gt=0)


class ImpedanceAnalyzerConfig(InstrumentConfig):
    """Profile for complex impedance measurement data and optional sweep control."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    device_type: Literal["impedance_analyzer"] = "impedance_analyzer"
    readback: ImpedanceReadbackSpec
    sweep: ImpedanceSweepSpec | None = None
