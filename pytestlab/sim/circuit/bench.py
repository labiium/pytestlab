from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from .plugins import get_plugin


class PSUChannel(BaseModel):
    name: str
    v_max: float
    i_max: float
    r_out_ohm: float = 0.05


class PSU(BaseModel):
    kind: str = "PSU"
    model: str = "GenericPSU"
    channels: list[PSUChannel]
    capabilities: list[str] = Field(default_factory=list)
    scpi_personality: str | None = None


class AWG(BaseModel):
    kind: str = "AWG"
    model: str = "GenericAWG"
    vpp_max: float
    z_out_ohm: float = 50.0
    capabilities: list[str] = Field(default_factory=list)
    scpi_personality: str | None = None


class DMM(BaseModel):
    kind: str = "DMM"
    model: str = "Generic6DMM"
    digits: float = 6.5
    rin_v_ohm: float = 10e6
    burden_ohm: float = 0.1
    line_freq_hz: float = 50.0
    capabilities: list[str] = Field(default_factory=list)
    scpi_personality: str | None = None


class Scope(BaseModel):
    kind: str = "SCOPE"
    model: str = "GenericScope"
    channels: int = 2
    bandwidth_hz: float = 100e6
    sample_rate_sps_max: float = 1e9
    enob: float = 8.0
    rin_ohm: float = 1e6
    cin_f: float = 15e-12
    capabilities: list[str] = Field(default_factory=list)
    scpi_personality: str | None = None


Instrument = PSU | AWG | DMM | Scope


class LimitSet(BaseModel):
    max_node_voltage_v: float = 60.0
    max_branch_current_a: float = 5.0


class BenchLimits(BaseModel):
    hard: LimitSet = LimitSet()
    soft: dict[str, float] = Field(default_factory=dict)


class BenchConfig(BaseModel):
    format_version: str = "1.0"
    bench_id: str
    instruments: dict[str, Instrument]
    limits: BenchLimits = BenchLimits()

    @model_validator(mode="after")
    def ensure_ids(self) -> BenchConfig:
        for inst_id, inst in self.instruments.items():
            if not inst_id:
                raise ValueError("instrument ids must be non-empty")
            if inst.kind not in {"PSU", "AWG", "DMM", "SCOPE"}:
                raise ValueError(f"unsupported instrument kind: {inst.kind}")
        return self

    def list_terminals(self, inst_id: str) -> list[str]:
        inst = self.instruments[inst_id]
        if isinstance(inst, PSU):
            return [f"{inst_id}.{ch.name}.HI" for ch in inst.channels] + [
                f"{inst_id}.{ch.name}.LO" for ch in inst.channels
            ]
        if isinstance(inst, AWG):
            return [f"{inst_id}.HI", f"{inst_id}.LO"]
        if isinstance(inst, DMM):
            return [
                f"{inst_id}.V.HI",
                f"{inst_id}.V.LO",
                f"{inst_id}.I.HI",
                f"{inst_id}.I.LO",
            ]
        if isinstance(inst, Scope):
            return [f"{inst_id}.CH{i}.HI" for i in range(1, inst.channels + 1)] + [
                f"{inst_id}.CH{i}.LO" for i in range(1, inst.channels + 1)
            ]
        plugin = get_plugin(inst.kind)
        if plugin is not None:
            return plugin.list_terminals(inst_id, inst)
        raise ValueError(f"unknown instrument type for {inst_id}")
