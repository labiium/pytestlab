"""Optional bridge to the dependency-neutral LAMB circuit contracts.

This module is deliberately an integration boundary: PyTestLab keeps owning
its ``WiringConfig``, ``NodeRef``, and ``TerminalRef`` API, while callers that
also install ``lamb-circuit-contracts`` may obtain a neutral ``WiringGraph``.
The package is imported lazily by its distribution name only.  PyTestLab does
not depend on its source tree, a checkout path, or its availability at
runtime; without it, :func:`to_wiring_graph` returns ``None``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from .bench import BenchConfig
    from .wiring import WiringConfig


def to_wiring_graph(wiring: WiringConfig, bench: BenchConfig | None = None) -> Any | None:
    """Convert a PyTestLab wiring config to an optional neutral graph.

    ``bench`` is optional because the existing wiring API can be used without
    a bench.  When supplied, it adds direction metadata for source and sink
    instruments; omission leaves endpoints bidirectional rather than guessing.
    ``None`` means the optional package is not installed.
    """

    try:
        from lamb_circuit_contracts import Connection
        from lamb_circuit_contracts import Endpoint
        from lamb_circuit_contracts import Net
        from lamb_circuit_contracts import Probe
        from lamb_circuit_contracts import WiringGraph
    except ModuleNotFoundError as exc:
        if exc.name != "lamb_circuit_contracts":
            raise
        return None

    terminal_names = {connection.from_ for connection in wiring.connections}
    endpoints = tuple(
        Endpoint(
            id=terminal,
            owner=terminal.split(".", 1)[0],
            direction=_endpoint_direction(terminal, bench),
        )
        for terminal in sorted(terminal_names)
    )
    net_names = {connection.to for connection in wiring.connections}
    nets = tuple(Net(id=net, reference=net == wiring.ground_node) for net in sorted(net_names))
    connections = tuple(
        Connection(endpoint_id=item.from_, net_id=item.to) for item in wiring.connections
    )
    probes = tuple(
        Probe(
            id=key,
            input_endpoint_id=_probe_endpoint(key, terminal_names),
            resistance_ohm=model.rin_ohm,
            capacitance_f=model.cin_f,
            lead_inductance_h=model.lin_h,
            attenuation=model.attenuation,
        )
        for key, model in wiring.probe_models.items()
    )
    return WiringGraph(
        endpoints=endpoints,
        nets=nets,
        connections=connections,
        probes=probes,
    )


def _endpoint_direction(terminal: str, bench: BenchConfig | None) -> str:
    if bench is None:
        return "bidirectional"
    owner = terminal.split(".", 1)[0]
    instrument = bench.instruments.get(owner)
    if instrument is None:
        return "bidirectional"
    if terminal.upper().endswith(".HI") and instrument.kind in {"AWG", "PSU"}:
        return "source"
    if terminal.upper().endswith(".HI") and instrument.kind in {"DMM", "SCOPE"}:
        return "sink"
    return "bidirectional"


def _probe_endpoint(key: str, terminals: set[str]) -> str:
    if key in terminals:
        return key
    for suffix in (".HI", ".LO"):
        candidate = f"{key}{suffix}"
        if candidate in terminals:
            return candidate
    return key
