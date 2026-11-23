from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from .instrument_config import InstrumentConfig

VNA_READBACK_QUERIES = (
    "identify",
    "status_byte",
    "condition",
    "continuous",
    "data_format",
    "sweep_type",
    "frequency_span",
    "frequency_offset",
    "fixture_simulator",
    "points",
    "trace_count",
    "trace_identity",
    "trace_equation",
    "trace_time_transform",
    "trace_axis",
    "trace_data",
)


CMT_READBACK_QUERIES = (
    "identify",
    "trigger_state",
    "continuous",
    "sweep_type",
    "frequency_span",
    "frequency_offset",
    "fixture_simulator",
    "points",
    "trace_count",
    "trace_identity",
    "trace_math",
    "trace_time_transform",
    "trace_gate",
    "trace_conversion",
    "trace_hold",
    "trace_axis",
    "trace_data",
)


class VNAReadbackConfig(BaseModel):
    """Bounded, read-only indexed trace protocol for a held frequency sweep."""

    model_config = ConfigDict(extra="forbid")
    channel: int = Field(default=1, ge=1, le=36)
    minimum_firmware: str = Field(pattern=r"^[A-Z]\.[0-9]+\.[0-9]+$")
    max_traces: int = Field(ge=1, le=16)
    max_points: int = Field(ge=2, le=20_001)


class CMTHeldReadbackConfig(BaseModel):
    """Conservative command and response bounds for the C1209 / S2VNA profile."""

    model_config = ConfigDict(extra="forbid")
    dialect: Literal["cmt_s2vna_socket"]
    channel: int = Field(default=1, ge=1, le=16)
    software_version: Literal["26.2.2"]
    max_traces: int = Field(ge=1, le=16)
    max_points: int = Field(ge=2, le=20_001)


class VNAConfig(InstrumentConfig):
    """Vector-network-analyzer S-parameter sweep and source-level profile."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    device_type: Literal["vna", "VNA", "vector_network_analyzer"] = "vna"

    # Basic S-parameter grab related fields
    s_parameters: list[str] = Field(
        default_factory=list,
        description="Profile-declared list of S-parameters to measure",
    )
    start_frequency: float | None = Field(None, description="Start frequency for the sweep in Hz")
    stop_frequency: float | None = Field(None, description="Stop frequency for the sweep in Hz")
    num_points: int | None = Field(None, description="Number of points in the sweep")
    if_bandwidth: float | None = Field(None, description="IF bandwidth in Hz")
    power_level: float | None = Field(None, description="Source power level in dBm")

    readback: VNAReadbackConfig | CMTHeldReadbackConfig | None = None

    @property
    def supports_sweep_setup(self) -> bool:
        return not isinstance(self.readback, CMTHeldReadbackConfig)

    @model_validator(mode="after")
    def _validate_readback_queries(self) -> "VNAConfig":
        if self.readback is None:
            return self
        operation = self.operation_options.operation("sparameter_data")
        aliases = operation.transport if operation else {}
        queries = (self.scpi.queries or {}) if self.scpi else {}
        cmt = isinstance(self.readback, CMTHeldReadbackConfig)
        if cmt and (self.manufacturer != "Copper Mountain Technologies" or self.model != "C1209"):
            raise ValueError("The CMT held readback dialect is pinned to the C1209.")
        if cmt and (
            self.operation_options.operation("sparameter_sweep_setup") is not None
            or self.operation_options.operation("sparameter_sweep_settings") is not None
        ):
            raise ValueError(
                "The CMT held readback profile does not support sweep setup or settings."
            )
        required = CMT_READBACK_QUERIES if cmt else VNA_READBACK_QUERIES
        missing = [name for name in required if aliases.get(name) not in queries]
        if missing:
            raise ValueError("VNA readback requires query aliases: " + ", ".join(missing))
        return self
