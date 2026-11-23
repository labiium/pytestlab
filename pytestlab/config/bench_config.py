from __future__ import annotations

import math
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
    model_config = ConfigDict(extra="forbid")
    zero_tolerance: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
        validation_alias=AliasChoices("zero_tolerance", "zero_tolerance_v"),
        description="Measured voltage tolerance in volts for quiescence verification",
    )
    settle_tolerance: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
        description="Measured voltage tolerance in volts for bias-setpoint settling",
    )
    model_config = ConfigDict(extra="forbid")

    voltage: dict[str, float] | None = None  # e.g., {"max": 5.5}
    current: dict[str, float] | None = None  # e.g., {"max": 2.2}
    amplitude: dict[str, float] | None = None  # e.g., {"max": 2.0}
    frequency: dict[str, float] | None = None  # e.g., {"max": 1.0e6}

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_limits(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if isinstance(normalized.get("zero_tolerance", normalized.get("zero_tolerance_v")), bool):
            raise ValueError("zero_tolerance must be a finite non-negative voltage")
        if isinstance(normalized.get("settle_tolerance"), bool):
            raise ValueError("settle_tolerance must be a finite non-negative voltage")
        for name in ("voltage", "current", "amplitude", "frequency"):
            bound = normalized.get(name)
            if bound is not None and not isinstance(bound, dict):
                normalized[name] = {"max": bound}
            if normalized.get(name) is not None:
                normalized[name] = cls._validate_bound_map(normalized[name], name=name)
        return normalized

    @staticmethod
    def _validate_bound_map(value: Any, *, name: str) -> dict[str, float] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be a mapping or non-negative numeric maximum")
        allowed = {"min", "max", "max_abs"}
        unknown = set(value) - allowed
        if unknown:
            names = ", ".join(sorted(str(key) for key in unknown))
            raise ValueError(f"{name} contains unsupported limit key(s): {names}")
        result: dict[str, float] = {}
        for key, raw in value.items():
            if isinstance(raw, bool):
                raise ValueError(f"{name}.{key} must be a finite non-negative number")
            try:
                number = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name}.{key} must be a finite non-negative number") from exc
            if (
                not math.isfinite(number)
                or (number < 0 and key == "max_abs")
                or (number < 0 and name not in {"voltage", "current"})
            ):
                raise ValueError(f"{name}.{key} must be a finite non-negative number")
            result[key] = number
        lower = result.get("min")
        upper = result.get("max")
        absolute = result.get("max_abs")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"{name}.min must be less than or equal to {name}.max")
        if absolute is not None and any(
            bound is not None and abs(bound) > absolute for bound in (lower, upper)
        ):
            raise ValueError(f"{name}.max_abs must be at least the configured min/max")
        return result

    @model_validator(mode="after")
    def validate_bounds(self) -> SafetyLimitChannel:
        for name in ("voltage", "current", "amplitude", "frequency"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, self._validate_bound_map(value, name=name))
        return self


class SafetyLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: dict[int, SafetyLimitChannel] | None = None
    bandwidth_limit: float | None = None
    load: dict[str, float] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_load(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        load = normalized.get("load")
        if load is not None and not isinstance(load, dict):
            normalized["load"] = {"max": load}
        if normalized.get("load") is not None:
            normalized["load"] = SafetyLimitChannel._validate_bound_map(
                normalized["load"], name="load"
            )
        return normalized

    @model_validator(mode="after")
    def validate_load(self) -> SafetyLimits:
        self.load = SafetyLimitChannel._validate_bound_map(self.load, name="load")
        if self.bandwidth_limit is not None and (
            isinstance(self.bandwidth_limit, bool)
            or not math.isfinite(float(self.bandwidth_limit))
            or self.bandwidth_limit < 0
        ):
            raise ValueError("bandwidth_limit must be a finite non-negative number")
        return self


class DeviceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_type: Literal["camera"] | None = None
    profile: str | None = None
    file: str | None = None
    description: str | None = None
    role: DeviceRole | None = None
    address: str | None = None
    serial_number: str | None = None
    safety_limits: SafetyLimits | None = None
    backend: dict[str, Any] | None = None
    transport: dict[str, Any] | None = None
    simulate: bool | None = None

    @model_validator(mode="after")
    def check_source(self) -> DeviceEntry:
        if self.device_type is not None:
            if self.profile is not None or self.file is not None:
                raise ValueError("Inline device_type cannot be combined with profile or file.")
            return self
        if (self.profile is None) == (self.file is None):
            raise ValueError("Device entries must define exactly one of 'profile' or 'file'.")
        return self

    @property
    def source(self) -> str:
        return self.profile if self.profile is not None else self.file or ""

    @property
    def source_kind(self) -> Literal["profile", "file", "inline"]:
        return "inline" if self.device_type else ("profile" if self.profile is not None else "file")

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
    # The loaded DMM profile validates this semantic ID (and may provide
    # custom IDs), so the bench schema must not hard-code vendor capabilities.
    function: str = Field(..., min_length=1)


class PowerSupplyReadbackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["power_supply_readback"]
    channel: int = Field(..., ge=1)
    quantity: Literal["voltage", "current"]


class SourceMeasureReadbackTarget(BaseModel):
    """Read one physical source-measure channel without changing its source state."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["source_measure_readback"]
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
    | Annotated[SourceMeasureReadbackTarget, Tag("source_measure_readback")]
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
            allowed = {"range", "resolution", "uncertainty", "nplc"}
        else:
            allowed = set()
        nplc = (self.settings or {}).get("nplc")
        if nplc is not None and (
            isinstance(nplc, bool)
            or not isinstance(nplc, (int, float))
            or not math.isfinite(nplc)
            or nplc < 0
        ):
            raise ValueError("measurement settings.nplc must be finite and non-negative")
        unknown = settings - allowed
        if unknown:
            names = ", ".join(sorted(unknown))
            target_kind = self.execution_target.kind
            raise ValueError(
                f"Unsupported settings for executable measurement target {target_kind}: {names}"
            )
        if "uncertainty" in settings and not isinstance((self.settings or {})["uncertainty"], bool):
            raise ValueError("Measurement uncertainty setting must be a boolean")


class SimCircuitConfig(BaseModel):
    netlist: str | None = None
    twin_package: str | None = None
    wiring: dict[str, str] = Field(default_factory=dict)
    seed: int = 1337
    noise_preset: str = "none"
    noise_seed: int | None = None
    kernel_settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def check_source(self) -> SimCircuitConfig:
        if (self.netlist is None) == (self.twin_package is None):
            raise ValueError("sim_circuit must define exactly one of netlist or twin_package")
        return self


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
    simulation_only: bool = False
    reset_on_open: bool = Field(
        default=False, strict=True, description="Reset supported instruments on normal bench open."
    )
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
