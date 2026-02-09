from __future__ import annotations

from typing import Any

from pydantic import AliasChoices
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import RootModel
from pydantic import model_validator


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


class SafetyLimits(BaseModel):
    channels: dict[int, SafetyLimitChannel] | None = None
    bandwidth_limit: float | None = None


class InstrumentEntry(BaseModel):
    profile: str
    address: str | None = None
    serial_number: str | None = None  # <-- Added for bench.yaml support
    safety_limits: SafetyLimits | None = None
    backend: dict[str, Any] | None = None
    simulate: bool | None = None


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
    instrument: str
    channel: int | None = None
    probe_location: str | None = None
    settings: dict[str, Any] | None = None
    notes: str | None = None


class BenchConfigExtended(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bench_name: str = Field(validation_alias=AliasChoices("name", "bench_name"))
    experiment: ExperimentSection | None = None
    instruments: dict[str, InstrumentEntry]
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
    continue_on_instrument_error: bool | None = False

    @model_validator(mode="after")
    def check_instruments(self) -> BenchConfigExtended:
        if not self.instruments:
            raise ValueError("At least one instrument must be defined in 'instruments'.")
        return self
