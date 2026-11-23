from __future__ import annotations

import pytest

from pytestlab.sim.circuit.bench import AWG
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringConfig


def _wiring() -> WiringConfig:
    return WiringConfig(
        connections=[
            Connection(from_="awg1.HI", to="signal"),
            Connection(from_="awg1.LO", to="0"),
        ],
        probe_models={"awg1.HI": {"rin_ohm": 50.0}},
    )


def test_optional_bridge_is_a_noop_when_neutral_package_is_absent(monkeypatch):
    import pytestlab.sim.circuit.shared_contracts as shared_contracts

    monkeypatch.setitem(__import__("sys").modules, "lamb_circuit_contracts", None)
    assert shared_contracts.to_wiring_graph(_wiring()) is None


def test_wiring_config_converts_to_neutral_graph_when_installed():
    contracts = pytest.importorskip("lamb_circuit_contracts")
    bench = BenchConfig(bench_id="shared", instruments={"awg1": AWG(vpp_max=5.0)})

    graph = _wiring().to_wiring_graph(bench=bench)

    assert isinstance(graph, contracts.WiringGraph)
    assert [(endpoint.id, endpoint.direction) for endpoint in graph.endpoints] == [
        ("awg1.HI", "source"),
        ("awg1.LO", "bidirectional"),
    ]
    assert [(item.endpoint_id, item.net_id) for item in graph.connections] == [
        ("awg1.HI", "signal"),
        ("awg1.LO", "0"),
    ]
    assert graph.nets[0].id == "0"
    assert graph.nets[0].reference is True
    assert graph.probes[0].input_endpoint_id == "awg1.HI"
