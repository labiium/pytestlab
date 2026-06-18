from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

_SPICE_SUFFIXES: dict[str, float] = {
    "T": 1e12,
    "G": 1e9,
    "MEG": 1e6,
    "K": 1e3,
    "M": 1e-3,
    "U": 1e-6,
    "N": 1e-9,
    "P": 1e-12,
    "F": 1e-15,
}


class DistSpec(BaseModel):
    type: Literal["uniform", "normal", "lognormal"]
    mean: float | None = None
    sigma: float | None = None
    low: float | None = None
    high: float | None = None

    @model_validator(mode="after")
    def _validate_dist(self) -> DistSpec:
        if self.type == "uniform":
            if self.low is None or self.high is None:
                raise ValueError("uniform dist requires low/high")
        elif self.type in {"normal", "lognormal"}:
            if self.mean is None or self.sigma is None:
                raise ValueError("normal/lognormal dist requires mean/sigma")
        return self

    def sample(self, rng: random.Random) -> float:
        if self.type == "uniform":
            assert self.low is not None and self.high is not None
            return rng.uniform(float(self.low), float(self.high))
        if self.type == "normal":
            assert self.mean is not None and self.sigma is not None
            return rng.normalvariate(float(self.mean), float(self.sigma))
        if self.type == "lognormal":
            assert self.mean is not None and self.sigma is not None
            return rng.lognormvariate(float(self.mean), float(self.sigma))
        raise ValueError(f"unknown distribution {self.type}")


class VariationSpec(BaseModel):
    target: str
    kind: Literal["value_scale"] = "value_scale"
    dist: DistSpec


class FaultSpec(BaseModel):
    target: str
    kind: Literal["open", "short", "value", "swap_nodes", "intermittent"]
    value: float | None = None
    open_ohm: float = 1e12
    short_ohm: float = 1e-6
    on_time_s: float | None = None
    off_time_s: float | None = None
    period_s: float | None = None
    duty_cycle: float = 0.5


class VariationConfig(BaseModel):
    variations: list[VariationSpec] = Field(default_factory=list)
    faults: list[FaultSpec] = Field(default_factory=list)
    seed: int = 1337


@dataclass
class NetlistMutationResult:
    text: str
    metadata: dict[str, Any]


def apply_variations_and_faults(text: str, config: VariationConfig | None) -> NetlistMutationResult:
    if config is None:
        return NetlistMutationResult(text=text, metadata={})

    rng = random.Random(int(config.seed))
    variations_by_target: dict[str, list[VariationSpec]] = {}
    for variation in config.variations:
        variations_by_target.setdefault(variation.target.upper(), []).append(variation)

    faults_by_target: dict[str, list[FaultSpec]] = {}
    for fault in config.faults:
        faults_by_target.setdefault(fault.target.upper(), []).append(fault)

    metadata: dict[str, Any] = {"variations": [], "faults": []}
    out_lines: list[str] = []

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("*") or stripped.startswith("."):
            out_lines.append(raw)
            continue

        parts = stripped.split()
        if not parts:
            out_lines.append(raw)
            continue

        name = parts[0]
        target_key = name.upper()
        working_parts = list(parts)
        applied = False

        for variation in variations_by_target.get(target_key, []):
            if variation.kind != "value_scale":
                continue
            value_idx = _find_value_token_index(working_parts)
            if value_idx is None:
                raise ValueError(f"unable to locate value token for {name}")
            base_value = _parse_spice_value(working_parts[value_idx])
            factor = variation.dist.sample(rng)
            new_value = base_value * float(factor)
            working_parts[value_idx] = _format_spice_value(new_value)
            metadata["variations"].append(
                {
                    "target": name,
                    "kind": variation.kind,
                    "factor": factor,
                    "value": new_value,
                }
            )
            applied = True

        fault_specs = faults_by_target.get(target_key, [])
        if fault_specs:
            for fault in fault_specs:
                result = _apply_fault(working_parts, fault)
                metadata["faults"].append(
                    {
                        "target": name,
                        "kind": fault.kind,
                    }
                )
                out_lines.append(_comment_out(raw, reason=fault.kind))
                if result is not None:
                    out_lines.append(result)
                applied = True
                break
            else:
                out_lines.append(" ".join(working_parts))
            continue

        if applied:
            out_lines.append(" ".join(working_parts))
        else:
            out_lines.append(raw)

    return NetlistMutationResult(text="\n".join(out_lines), metadata=metadata)


def _apply_fault(parts: list[str], fault: FaultSpec) -> str | None:
    if fault.kind == "swap_nodes":
        if len(parts) < 3:
            raise ValueError("swap_nodes fault requires at least two nodes")
        parts[1], parts[2] = parts[2], parts[1]
        return " ".join(parts)

    if fault.kind == "value":
        value_idx = _find_value_token_index(parts)
        if value_idx is None:
            raise ValueError(f"unable to locate value token for {parts[0]}")
        if fault.value is None:
            raise ValueError("value fault requires a value")
        parts[value_idx] = _format_spice_value(float(fault.value))
        return " ".join(parts)

    if fault.kind in {"open", "short", "intermittent"}:
        if len(parts) < 3:
            raise ValueError("fault requires at least two nodes")
        n1, n2 = parts[1], parts[2]
        ident = _sanitize_identifier(parts[0])
        if fault.kind == "open":
            return f"R_SB_OPEN_{ident} {n1} {n2} {_format_spice_value(fault.open_ohm)}"
        if fault.kind == "short":
            return f"R_SB_SHORT_{ident} {n1} {n2} {_format_spice_value(fault.short_ohm)}"
        expr = _intermittent_expression(fault)
        return f"R_SB_INT_{ident} {n1} {n2} R={expr}"

    raise ValueError(f"unknown fault kind {fault.kind}")


def _intermittent_expression(fault: FaultSpec) -> str:
    open_val = float(fault.open_ohm)
    short_val = float(fault.short_ohm)
    if fault.period_s and fault.duty_cycle:
        period = float(fault.period_s)
        duty = max(0.0, min(1.0, float(fault.duty_cycle)))
        on_time = duty * period
        return f"(time % {period:.12g}) < {on_time:.12g} ? {short_val:.12g} : {open_val:.12g}"
    if fault.on_time_s is not None or fault.off_time_s is not None:
        on_time = float(fault.on_time_s or 0.0)
        off_time = float(fault.off_time_s or on_time)
        return (
            f"(time >= {on_time:.12g} && time <= {off_time:.12g}) ? "
            f"{short_val:.12g} : {open_val:.12g}"
        )
    return f"{open_val:.12g}"


def _find_value_token_index(parts: list[str]) -> int | None:
    for idx in range(len(parts) - 1, 0, -1):
        if _looks_like_number(parts[idx]):
            return idx
    return None


def _looks_like_number(token: str) -> bool:
    return bool(re.match(r"^[+-]?[0-9.]+([eE][+-]?[0-9]+)?[a-zA-Z]*$", token.strip()))


def _parse_spice_value(token: str) -> float:
    value = token.strip()
    match = re.match(r"^([+-]?[0-9.]+(?:[eE][+-]?[0-9]+)?)([a-zA-Z]+)?$", value)
    if not match:
        raise ValueError(f"unsupported value token {token!r}")
    number = float(match.group(1))
    suffix = match.group(2)
    if not suffix:
        return number
    suffix = suffix.upper()
    if suffix in _SPICE_SUFFIXES:
        return number * _SPICE_SUFFIXES[suffix]
    return number


def _format_spice_value(value: float) -> str:
    return f"{value:.12g}"


def _sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value)
    return cleaned or "x"


def _comment_out(line: str, *, reason: str) -> str:
    return f"* SIMBENCH_FAULT({reason}) {line}"
