from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any


class AnalysisKind(str, Enum):
    OP = "op"
    DC = "dc"
    AC = "ac"
    TRANSIENT = "tran"


@dataclass(frozen=True)
class RequiredFeatures:
    node_voltages: bool = True
    source_currents: bool = False
    element_currents: bool = False
    complex_ac: bool = False
    settings: bool = False
    behavioral_sources: bool = False
    psu_current_limit: bool = False
    raw_netlist: bool = True
    structured_sources: bool = False


@dataclass(frozen=True)
class SimulationRequest:
    analysis: AnalysisKind
    nodes: tuple[str, ...] = ()
    source_currents: tuple[str, ...] = ()
    element_currents: tuple[str, ...] = ()
    params: dict[str, float] | None = None
    settings: Any | None = None
    required: RequiredFeatures = field(default_factory=RequiredFeatures)
    metadata: dict[str, Any] = field(default_factory=dict)


def op_request(
    *,
    nodes: list[str] | tuple[str, ...] = (),
    source_currents: list[str] | tuple[str, ...] = (),
    element_currents: list[str] | tuple[str, ...] = (),
    settings: Any | None = None,
    required: RequiredFeatures | None = None,
) -> SimulationRequest:
    if required is None:
        required = RequiredFeatures(
            source_currents=bool(source_currents),
            element_currents=bool(element_currents),
            settings=settings is not None,
        )
    return SimulationRequest(
        analysis=AnalysisKind.OP,
        nodes=tuple(nodes),
        source_currents=tuple(source_currents),
        element_currents=tuple(element_currents),
        settings=settings,
        required=required,
    )
