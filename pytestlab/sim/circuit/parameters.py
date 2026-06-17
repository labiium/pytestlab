from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_PARAM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ParameterSpec:
    """Declaration for a calibrated SPICE/model parameter."""

    name: str
    nominal: float
    min_value: float | None = None
    max_value: float | None = None
    unit: str = ""
    description: str = ""
    free: bool = True

    def __post_init__(self) -> None:
        _validate_param_name(self.name)
        nominal = float(self.nominal)
        object.__setattr__(self, "nominal", nominal)
        if self.min_value is not None:
            object.__setattr__(self, "min_value", float(self.min_value))
        if self.max_value is not None:
            object.__setattr__(self, "max_value", float(self.max_value))
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError(f"parameter {self.name!r} has min_value > max_value")
        if self.min_value is not None and nominal < self.min_value:
            raise ValueError(f"parameter {self.name!r} nominal below min_value")
        if self.max_value is not None and nominal > self.max_value:
            raise ValueError(f"parameter {self.name!r} nominal above max_value")

    def clamp(self, value: float) -> float:
        out = float(value)
        if self.min_value is not None:
            out = max(out, self.min_value)
        if self.max_value is not None:
            out = min(out, self.max_value)
        return out

    def validate_value(self, value: float) -> float:
        out = float(value)
        if self.min_value is not None and out < self.min_value:
            raise ValueError(f"parameter {self.name!r}={out} below min_value={self.min_value}")
        if self.max_value is not None and out > self.max_value:
            raise ValueError(f"parameter {self.name!r}={out} above max_value={self.max_value}")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nominal": self.nominal,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "unit": self.unit,
            "description": self.description,
            "free": self.free,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ParameterSpec:
        return cls(
            name=str(data["name"]),
            nominal=float(data["nominal"]),
            min_value=None if data.get("min_value") is None else float(data["min_value"]),
            max_value=None if data.get("max_value") is None else float(data["max_value"]),
            unit=str(data.get("unit", "")),
            description=str(data.get("description", "")),
            free=bool(data.get("free", True)),
        )


@dataclass(frozen=True)
class ParameterSet:
    """Resolved calibrated parameter values plus optional declarations."""

    values: dict[str, float]
    specs: dict[str, ParameterSpec]

    @classmethod
    def from_values(
        cls,
        values: Mapping[str, float] | None = None,
        *,
        specs: Mapping[str, ParameterSpec | Mapping[str, Any]] | None = None,
    ) -> ParameterSet:
        spec_objs: dict[str, ParameterSpec] = {}
        for key, spec in (specs or {}).items():
            obj = spec if isinstance(spec, ParameterSpec) else ParameterSpec.from_dict(spec)
            if obj.name != key:
                obj = ParameterSpec(
                    name=key,
                    nominal=obj.nominal,
                    min_value=obj.min_value,
                    max_value=obj.max_value,
                    unit=obj.unit,
                    description=obj.description,
                    free=obj.free,
                )
            spec_objs[key] = obj
        resolved: dict[str, float] = {name: spec.nominal for name, spec in spec_objs.items()}
        for key, value in (values or {}).items():
            _validate_param_name(str(key))
            resolved[str(key)] = float(value)
        return cls(values=resolved, specs=spec_objs)

    def resolve(self, overrides: Mapping[str, float] | None = None) -> dict[str, float]:
        resolved = dict(self.values)
        for key, value in (overrides or {}).items():
            name = str(key)
            _validate_param_name(name)
            spec = self.specs.get(name)
            resolved[name] = spec.validate_value(value) if spec is not None else float(value)
        return resolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": dict(sorted(self.values.items())),
            "specs": {key: spec.to_dict() for key, spec in sorted(self.specs.items())},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ParameterSet:
        return cls.from_values(data.get("values", {}), specs=data.get("specs", {}))


def normalize_parameter_set(
    params: Mapping[str, float] | ParameterSet | None,
    *,
    specs: Mapping[str, ParameterSpec | Mapping[str, Any]] | None = None,
) -> ParameterSet:
    if isinstance(params, ParameterSet):
        return params
    return ParameterSet.from_values(params, specs=specs)


def parameter_hash(params: Mapping[str, float] | ParameterSet | None) -> str:
    if isinstance(params, ParameterSet):
        payload = params.to_dict()
    else:
        payload = {str(k): float(v) for k, v in sorted((params or {}).items())}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_param_lines(params: Mapping[str, float] | None) -> list[str]:
    lines: list[str] = []
    for key, value in sorted((params or {}).items()):
        _validate_param_name(str(key))
        lines.append(f".param {key}={float(value):.12g}")
    return lines


def _validate_param_name(name: str) -> None:
    if not _PARAM_NAME_RE.match(name):
        raise ValueError(f"invalid parameter name {name!r}; use SPICE-safe identifiers")
