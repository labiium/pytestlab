from __future__ import annotations

from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import AliasChoices
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Discriminator
from pydantic import Field
from pydantic import RootModel
from pydantic import Tag
from pydantic import model_validator

from .device_config import DeviceRole


class ExperimentSection(BaseModel):
    title: str
    description: str
    operator: str | None = None
    date: str | None = None
    notes: str | None = None
    database_path: str | None = None


class SafetyLimitChannel(BaseModel):
    voltage: dict[str, float] | None = None  # e.g., {"max": 5.5}
    current: dict[str, float] | None = None  # e.g., {"max": 2.2}
    amplitude: dict[str, float] | None = None  # e.g., {"max": 2.0}
    frequency: dict[str, float] | None = None  # e.g., {"max": 1.0e6}


class SafetyLimits(BaseModel):
    channels: dict[int, SafetyLimitChannel] | None = None
    bandwidth_limit: float | None = None
    load: dict[str, float] | None = None


class DeviceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str | None = None
    file: str | None = None
    description: str | None = None
    role: DeviceRole | None = None
    address: str | None = None
    serial_number: str | None = None
    safety_limits: SafetyLimits | None = None
    backend: dict[str, Any] | None = None
    simulate: bool | None = None

    @model_validator(mode="after")
    def check_source(self) -> DeviceEntry:
        if (self.profile is None) == (self.file is None):
            raise ValueError("Device entries must define exactly one of 'profile' or 'file'.")
        return self

    @property
    def source(self) -> str:
        return self.profile if self.profile is not None else self.file or ""

    @property
    def source_kind(self) -> Literal["profile", "file"]:
        return "profile" if self.profile is not None else "file"

    def profile_is_local_file(self, *, base_path: Path | None = None) -> bool:
        if self.profile is None:
            return False
        candidate = Path(self.profile)
        return candidate.is_absolute() or candidate.suffix in {".yaml", ".yml", ".json"}

    def resolved_source(self, *, base_path: Path | None = None) -> str | Path:
        if self.file is not None:
            path = Path(self.file)
            return base_path / path if not path.is_absolute() and base_path is not None else path
        if self.profile_is_local_file(base_path=base_path):
            path = Path(self.profile or "")
            return base_path / path if not path.is_absolute() and base_path is not None else path
        return self.profile or ""


class InstrumentEntry(DeviceEntry):
    """Bench entry for resources that must resolve to Instrument subclasses."""


class AutomationHooks(BaseModel):
    pre_experiment: list[str] | None = None
    post_experiment: list[str] | None = None


class TraceabilityCalibration(RootModel[dict[str, str]]):
    root: dict[str, str]


class TraceabilityEnvironment(BaseModel):
    temperature: float | None = None
    humidity: float | None = None


class TraceabilityDUT(BaseModel):
    serial_number: str | None = None
    description: str | None = None


class Traceability(BaseModel):
    calibration: dict[str, str] | None = None
    environment: TraceabilityEnvironment | None = None
    dut: TraceabilityDUT | None = None


class AccessoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str | None = None
    file: str | None = None
    serial_number: str | None = None
    parameters: dict[str, float | str | bool] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check_source(self) -> AccessoryEntry:
        if (self.profile is None) == (self.file is None):
            raise ValueError("Accessory entries must define exactly one of 'profile' or 'file'.")
        return self


class RouteConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(default=None, validation_alias=AliasChoices("from", "source"))
    to: str
    path: list[str] = Field(default_factory=list)

    @property
    def from_endpoint(self) -> str:
        return self.source or ""


class RouteEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str | None = None
    description: str | None = None
    connects: list[RouteConnection] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    settling_time_s: float | None = Field(default=None, ge=0)
    exclusive_group: str | None = None

    @model_validator(mode="after")
    def check_connections(self) -> RouteEntry:
        if not self.connects:
            raise ValueError("routes must declare at least one connection in 'connects'.")
        for connection in self.connects:
            if not connection.from_endpoint:
                raise ValueError("route connections must define 'from' and 'to' endpoints.")
        return self


class OscilloscopeChannelTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["oscilloscope_channel"]
    channel: int = Field(..., ge=1)
    measurement: Literal["vpp", "rms_voltage"]


class MultimeterFunctionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["multimeter_function"]
    function: Literal[
        "voltage_dc",
        "voltage_ac",
        "current_dc",
        "current_ac",
        "resistance",
        "resistance_4wire",
        "capacitance",
        "frequency",
        "temperature",
    ]


class PowerSupplyReadbackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["power_supply_readback"]
    channel: int = Field(..., ge=1)
    quantity: Literal["voltage", "current"]


class DCLoadReadbackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dc_load_readback"]
    quantity: Literal["voltage", "current", "power"]


def _measurement_target_discriminator(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("kind")
    return getattr(value, "kind", None)


MeasurementTarget = Annotated[
    Annotated[OscilloscopeChannelTarget, Tag("oscilloscope_channel")]
    | Annotated[MultimeterFunctionTarget, Tag("multimeter_function")]
    | Annotated[PowerSupplyReadbackTarget, Tag("power_supply_readback")]
    | Annotated[DCLoadReadbackTarget, Tag("dc_load_readback")],
    Discriminator(_measurement_target_discriminator),
]


class MeasurementPlanEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    resource: str | None = None
    device: str | None = None
    instrument: str | None = None
    channel: int | None = None
    probe_location: str | None = None
    settings: dict[str, Any] | None = None
    notes: str | None = None
    description: str | None = None
    route: str | None = None
    execution_target: MeasurementTarget | None = Field(
        default=None,
        validation_alias=AliasChoices("target", "execution_target"),
        serialization_alias="target",
    )
    accessories: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_target(self) -> MeasurementPlanEntry:
        targets = [
            value for value in (self.resource, self.device, self.instrument) if value is not None
        ]
        if len(targets) != 1:
            raise ValueError(
                "Measurement plan entries must define exactly one of 'resource', 'device', or 'instrument'."
            )
        if self.resource is None:
            self.resource = self.device if self.device is not None else self.instrument
        if self.execution_target is None and self.accessories:
            raise ValueError("measurement_plan accessories require an executable target block.")
        if self.execution_target is not None and (
            self.channel is not None or self.probe_location is not None
        ):
            raise ValueError(
                "Executable measurement_plan entries must put channel information in "
                "target.channel and accessories in accessories; legacy channel/probe_location "
                "fields cannot coexist with target."
            )
        self._validate_executable_settings()
        return self

    @property
    def target(self) -> str:
        return self.resource or ""

    @property
    def target_alias(self) -> str:
        return self.resource or ""

    def _validate_executable_settings(self) -> None:
        if self.execution_target is None:
            return
        settings = set((self.settings or {}).keys())
        if isinstance(self.execution_target, MultimeterFunctionTarget):
            allowed = {"range", "resolution"}
        else:
            allowed = set()
        unknown = settings - allowed
        if unknown:
            names = ", ".join(sorted(unknown))
            target_kind = self.execution_target.kind
            raise ValueError(
                f"Unsupported settings for executable measurement target "
                f"{target_kind}: {names}"
            )


class SimCircuitConfig(BaseModel):
    netlist: str
    wiring: dict[str, str] = Field(default_factory=dict)
    seed: int = 1337
    noise_preset: str = "none"
    noise_seed: int | None = None
    kernel_settings: dict[str, Any] | None = None


class BenchConfigExtended(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bench_name: str = Field(validation_alias=AliasChoices("name", "bench_name"))
    experiment: ExperimentSection | None = None
    devices: dict[str, DeviceEntry] = Field(default_factory=dict)
    instruments: dict[str, InstrumentEntry] = Field(default_factory=dict)
    accessories: dict[str, AccessoryEntry] = Field(default_factory=dict)
    routes: dict[str, RouteEntry] = Field(default_factory=dict)
    custom_validations: list[str] | None = None
    automation: AutomationHooks | None = None
    traceability: Traceability | None = None
    measurement_plan: list[MeasurementPlanEntry] | None = None
    sim_circuit: SimCircuitConfig | None = None
    version: str | None = None
    last_modified: str | None = None
    changelog: str | None = None

    backend_defaults: dict[str, Any] | None = None
    simulate: bool | None = False
    description: str | None = None
    continue_on_automation_error: bool | None = False
    continue_on_device_error: bool | None = False

    @model_validator(mode="after")
    def check_resources(self) -> BenchConfigExtended:
        if not self.devices and not self.instruments:
            raise ValueError("At least one device or instrument must be defined.")
        duplicate_aliases = set(self.devices) & set(self.instruments)
        if duplicate_aliases:
            duplicates = ", ".join(sorted(duplicate_aliases))
            raise ValueError(
                f"Aliases cannot be defined in both devices and instruments: {duplicates}"
            )
        return self
