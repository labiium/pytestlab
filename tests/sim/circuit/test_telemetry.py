from __future__ import annotations

import json

import numpy as np
import pytest

from pytestlab.sim.circuit.bench import DMM
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.factories import circuit_from_netlist
from pytestlab.sim.circuit.session import Session
from pytestlab.sim.circuit.spice import SpiceResult
from pytestlab.sim.circuit.store import ArtifactStore
from pytestlab.sim.circuit.telemetry import Telemetry
from pytestlab.sim.circuit.telemetry import TelemetryKernel
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringConfig


class FakeKernel:
    def op(self, session, nodes, **kwargs):
        return SpiceResult(
            analysis="op",
            scale=np.asarray([0.0]),
            scale_unit="op",
            node_voltages={node: np.asarray([1.25]) for node in nodes},
            source_currents={},
            sources=(),
            metadata={"engine": "fake", "base_netlist_hash": "sha256:test"},
        )


class FailingKernel:
    def op(self, session, nodes, **kwargs):
        raise RuntimeError("simulation exploded")


def _session(netlist_path, telemetry: Telemetry, kernel) -> Session:
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": "telemetry",
            "author": "pytestlab",
            "license": "UNLICENSED",
            "intended_analyses": ["op"],
        },
    )
    return Session(
        circuit=circuit,
        bench=BenchConfig(bench_id="telemetry", instruments={"dmm1": DMM()}),
        wiring=WiringConfig(
            connections=[
                Connection(from_="dmm1.V.HI", to="vout"),
                Connection(from_="dmm1.V.LO", to="0"),
            ]
        ),
        kernel=kernel,
        telemetry=telemetry,
    )


def test_session_kernel_records_structural_simulation_evidence(netlist_path, tmp_path) -> None:
    telemetry = Telemetry(ArtifactStore(tmp_path))
    session = _session(netlist_path, telemetry, FakeKernel())

    result = session.kernel.op(session, ["vout"])

    events = telemetry.events()
    assert result.node_voltages["vout"].tolist() == [1.25]
    assert [event["event"] for event in events] == [
        "simulation.started",
        "simulation.completed",
    ]
    completed = events[-1]["payload"]
    assert completed["analysis"] == "op"
    assert completed["engine"] == "fake"
    assert completed["requested_nodes"] == ["vout"]
    assert completed["returned_nodes"] == ["vout"]
    assert completed["sample_count"] == 1
    assert completed["status"] == "pass"
    assert completed["duration_s"] >= 0
    summary = telemetry.metrics.summary("simulation.op")
    assert summary is not None
    assert summary.count == 1


def test_telemetry_records_failure_and_preserves_exception(netlist_path, tmp_path) -> None:
    telemetry = Telemetry(ArtifactStore(tmp_path))
    session = _session(netlist_path, telemetry, FailingKernel())

    with pytest.raises(RuntimeError, match="simulation exploded"):
        session.kernel.op(session, ["vout"])

    events = telemetry.events()
    assert [event["event"] for event in events] == [
        "simulation.started",
        "simulation.failed",
    ]
    assert events[-1]["payload"]["error_type"] == "RuntimeError"


def test_telemetry_kernel_delegates_capability_methods(tmp_path) -> None:
    class CapableKernel(FakeKernel):
        def capabilities(self):
            return {"op": True}

    wrapped = TelemetryKernel(CapableKernel(), Telemetry(ArtifactStore(tmp_path)))

    assert wrapped.capabilities() == {"op": True}


def test_artifact_store_round_trips_typed_payloads(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    text_artifact = store.put_text("runs", "ngspice output")
    json_artifact = store.put_json("runs", {"status": "pass"})

    assert store.get_text("runs", text_artifact.content_hash) == "ngspice output"
    assert store.get_json("runs", json_artifact.content_hash) == {"status": "pass"}


def test_local_telemetry_writes_json_without_an_otel_provider(tmp_path) -> None:
    telemetry = Telemetry(ArtifactStore(tmp_path))

    telemetry.emit("simulation.note", {"message": "local only"})

    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    assert event["payload"] == {"message": "local only"}
