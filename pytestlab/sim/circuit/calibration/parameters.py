from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict
from dataclasses import dataclass

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ParameterDeclaration:
    name: str
    initial: float
    lower: float
    upper: float
    unit: str
    frozen: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not _IDENT_RE.match(self.name):
            raise ValueError(f"invalid SPICE parameter name: {self.name!r}")
        if not self.unit:
            raise ValueError("parameter unit is required")
        if self.lower > self.upper:
            raise ValueError("parameter lower bound must be <= upper bound")
        if not self.lower <= self.initial <= self.upper:
            raise ValueError("parameter initial value must be within bounds")

    def clamp(self, value: float) -> float:
        return min(self.upper, max(self.lower, float(value)))


@dataclass(frozen=True)
class ParameterSet:
    declarations: tuple[ParameterDeclaration, ...]
    values: dict[str, float]

    @classmethod
    def from_declarations(cls, declarations: Iterable[ParameterDeclaration]) -> ParameterSet:
        decls = tuple(declarations)
        _ensure_unique(decls)
        return cls(decls, {decl.name: float(decl.initial) for decl in decls})

    def free_declarations(self) -> tuple[ParameterDeclaration, ...]:
        return tuple(decl for decl in self.declarations if not decl.frozen)

    def bounded_values(self, values: dict[str, float] | None = None) -> dict[str, float]:
        source = dict(self.values)
        if values:
            source.update(values)
        bounded = {}
        by_name = {decl.name: decl for decl in self.declarations}
        for name, value in source.items():
            decl = by_name.get(name)
            bounded[name] = decl.clamp(value) if decl else float(value)
        return bounded

    def with_values(self, values: dict[str, float]) -> ParameterSet:
        return ParameterSet(self.declarations, self.bounded_values(values))

    def render_param_lines(self, values: dict[str, float] | None = None) -> list[str]:
        resolved = self.bounded_values(values)
        return [f".param {name}={resolved[name]:.12g}" for name in sorted(resolved)]

    def parameter_hash(self, values: dict[str, float] | None = None) -> str:
        resolved = self.bounded_values(values)
        raw = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()

    def manifest_payload(self, values: dict[str, float] | None = None) -> dict[str, object]:
        resolved = self.bounded_values(values)
        return {
            "parameters": [asdict(decl) | {"value": resolved[decl.name]} for decl in self.declarations],
            "parameter_hash": self.parameter_hash(resolved),
        }


def render_param_block(values: dict[str, float]) -> str:
    lines = []
    for name, value in sorted(values.items()):
        if not _IDENT_RE.match(name):
            raise ValueError(f"invalid SPICE parameter name: {name!r}")
        lines.append(f".param {name}={float(value):.12g}")
    return "\n".join(lines)


def netlist_hash(netlist_text: str, values: dict[str, float] | None = None) -> str:
    rendered = netlist_text
    if values:
        rendered = rendered + "\n" + render_param_block(values)
    return "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()


def _ensure_unique(declarations: tuple[ParameterDeclaration, ...]) -> None:
    names = [decl.name for decl in declarations]
    if len(set(names)) != len(names):
        raise ValueError("parameter names must be unique")
