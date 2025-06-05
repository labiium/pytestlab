from __future__ import annotations
from typing import Optional, Dict, List, Any, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator, RootModel

class ExperimentSection(BaseModel):
    title: str
    description: str
    operator: Optional[str] = None
    date: Optional[str] = None
    notes: Optional[str] = None

class SafetyLimitChannel(BaseModel):
    voltage: Optional[Dict[str, float]] = None  # e.g., {"max": 5.5}
    current: Optional[Dict[str, float]] = None  # e.g., {"max": 2.2}

class SafetyLimits(BaseModel):
    channels: Optional[Dict[int, SafetyLimitChannel]] = None
    bandwidth_limit: Optional[float] = None

class InstrumentEntry(BaseModel):
    profile: str
    address: Optional[str] = None
    safety_limits: Optional[SafetyLimits] = None
    backend: Optional[Dict[str, Any]] = None
    simulate: Optional[bool] = None

class AutomationHooks(BaseModel):
    pre_experiment: Optional[List[str]] = None
    post_experiment: Optional[List[str]] = None

class TraceabilityCalibration(RootModel[Dict[str, str]]):
    root: Dict[str, str]

class TraceabilityEnvironment(BaseModel):
    temperature: Optional[float] = None
    humidity: Optional[float] = None

class TraceabilityDUT(BaseModel):
    serial_number: Optional[str] = None
    description: Optional[str] = None

class Traceability(BaseModel):
    calibration: Optional[Dict[str, str]] = None
    environment: Optional[TraceabilityEnvironment] = None
    dut: Optional[TraceabilityDUT] = None

class MeasurementPlanEntry(BaseModel):
    name: str
    instrument: str
    channel: Optional[int] = None
    probe_location: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

class BenchConfigExtended(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bench_name: str
    experiment: Optional[ExperimentSection] = None
    instruments: Dict[str, InstrumentEntry]
    custom_validations: Optional[List[str]] = None
    automation: Optional[AutomationHooks] = None
    traceability: Optional[Traceability] = None
    measurement_plan: Optional[List[MeasurementPlanEntry]] = None
    version: Optional[str] = None
    last_modified: Optional[str] = None
    changelog: Optional[str] = None

    backend_defaults: Optional[Dict[str, Any]] = None
    simulate: Optional[bool] = False
    description: Optional[str] = None

    @model_validator(mode="after")
    def check_instruments(self) -> "BenchConfigExtended":
        if not self.instruments:
            raise ValueError("At least one instrument must be defined in 'instruments'.")
        return self