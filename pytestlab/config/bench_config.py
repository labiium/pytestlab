from __future__ import annotations

from typing import Any

from pydantic import AliasChoices
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import RootModel
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
    profile: str
    role: DeviceRole | None = None
    address: str | None = None
    serial_number: str | None = None
    safety_limits: SafetyLimits | None = None
    backend: dict[str, Any] | None = None
    simulate: bool | None = None


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


class MeasurementPlanEntry(BaseModel):
    name: str
    resource: str | None = None
    device: str | None = None
    instrument: str | None = None
    channel: int | None = None
    probe_location: str | None = None
    settings: dict[str, Any] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check_target(self) -> MeasurementPlanEntry:
        targets = [value for value in (self.resource, self.device, self.instrument) if value is not None]
        if len(targets) != 1:
            raise ValueError(
                "Measurement plan entries must define exactly one of 'resource', 'device', or 'instrument'."
            )
        if self.resource is None:
            self.resource = self.device if self.device is not None else self.instrument
        return self

    @property
    def target(self) -> str:
        return self.resource or ""


class BenchConfigExtended(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bench_name: str = Field(validation_alias=AliasChoices("name", "bench_name"))
    experiment: ExperimentSection | None = None
    devices: dict[str, DeviceEntry] = Field(default_factory=dict)
    instruments: dict[str, InstrumentEntry] = Field(default_factory=dict)
    custom_validations: list[str] | None = None
    automation: AutomationHooks | None = None
    traceability: Traceability | None = None
    measurement_plan: list[MeasurementPlanEntry] | None = None
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
            raise ValueError(f"Aliases cannot be defined in both devices and instruments: {duplicates}")
        return self
