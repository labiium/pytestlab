from __future__ import annotations

import numpy as np
import pytest

from pytestlab.sim.circuit import EEspiceCliKernel
from pytestlab.sim.circuit import NgspiceKernel
from pytestlab.sim.circuit import Port
from pytestlab.sim.circuit import Session
from pytestlab.sim.circuit import SimbenchScpiBackend
from pytestlab.sim.circuit import SimSession
from pytestlab.sim.circuit import UnsupportedCapability
from pytestlab.sim.circuit import UnsupportedReason
from pytestlab.sim.circuit import get_simulator_capabilities
from pytestlab.sim.circuit import list_simulator_backends
from pytestlab.sim.circuit.bench import DMM
from pytestlab.sim.circuit.bench import PSU
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.bench import PSUChannel
from pytestlab.sim.circuit.factories import circuit_from_netlist
from pytestlab.sim.circuit.simulators import SimulatorCapabilities
from pytestlab.sim.circuit.spice import SpiceResult
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringConfig


class CurrentCapableNoVectorKernel:
    def __init__(self) -> None:
        self.op_calls = 0

    def capabilities(self) -> SimulatorCapabilities:
        return SimulatorCapabilities(
            backend="fake_eespice",
            op=True,
            node_voltages=True,
            source_currents=True,
            element_currents=True,
            raw_netlists=True,
            settings=True,
        )

    def supports(self, request):
        return self.capabilities().supports(request)

    def op(self, session, nodes, *, settings=None, currents=None, params=None):
        self.op_calls += 1
        node_voltages = {node: np.asarray([1.0]) for node in nodes}
        return SpiceResult("op", np.asarray([0.0]), "op", node_voltages, {}, ())

    def dc_sweep(self, session, nodes, sweep, *, settings=None, currents=None, params=None):
        node_voltages = {node: np.asarray([1.0]) for node in nodes}
        return SpiceResult("dc", np.asarray([0.0]), "V", node_voltages, {}, ())

    def ac(self, session, nodes, sweep, *, settings=None, currents=None, params=None):
        node_voltages = {node: np.asarray([1.0 + 0.0j]) for node in nodes}
        return SpiceResult("ac", np.asarray([1.0]), "Hz", node_voltages, {}, ())

    def transient(
        self,
        session,
        nodes,
        *,
        sample_rate,
        record_length,
        settings=None,
        currents=None,
        params=None,
    ):
        scale = np.arange(int(record_length), dtype=float) / float(sample_rate)
        node_voltages = {node: np.zeros_like(scale) for node in nodes}
        return SpiceResult("tran", scale, "s", node_voltages, {}, ())


class NoCurrentKernel(CurrentCapableNoVectorKernel):
    def capabilities(self) -> SimulatorCapabilities:
        return SimulatorCapabilities(
            backend="fake_eespice",
            op=True,
            node_voltages=True,
            raw_netlists=True,
            settings=True,
        )


def _circuit(tmp_path):
    path = tmp_path / "current.cir"
    path.write_text("Current test\nRLOAD vload 0 10\n.end\n")
    return circuit_from_netlist(
        path,
        metadata={
            "title": "current",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op"],
        },
    )


def _session_with_psu(tmp_path) -> Session:
    bench = BenchConfig(
        bench_id="psu",
        instruments={"psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=1.0)])},
    )
    wiring = WiringConfig(
        connections=[
            Connection(from_="psu1.CH1.HI", to="vload"),
            Connection(from_="psu1.CH1.LO", to="0"),
        ]
    )
    session = Session(circuit=_circuit(tmp_path), bench=bench, wiring=wiring)
    session.psus["psu1"].set_state(channel="CH1", voltage_setpoint=5.0, current_limit=0.1)
    session.psus["psu1"].set_state(channel="CH1", enabled=True)
    return session


def _session_with_dmm(tmp_path) -> Session:
    bench = BenchConfig(bench_id="dmm", instruments={"dmm1": DMM()})
    wiring = WiringConfig(
        connections=[
            Connection(from_="dmm1.I.HI", to="vload"),
            Connection(from_="dmm1.I.LO", to="0"),
        ]
    )
    return Session(circuit=_circuit(tmp_path), bench=bench, wiring=wiring)


def _session_with_voltage_dmm(tmp_path) -> Session:
    bench = BenchConfig(bench_id="dmm", instruments={"dmm1": DMM()})
    wiring = WiringConfig(
        connections=[
            Connection(from_="dmm1.V.HI", to="vload"),
            Connection(from_="dmm1.V.LO", to="0"),
        ]
    )
    return Session(circuit=_circuit(tmp_path), bench=bench, wiring=wiring)


def _sim_with_session(tmp_path, session: Session, port_name: str, inst_id: str, port: Port):
    sim = SimSession.from_netlist(tmp_path / "unused.cir")
    sim._session = session
    sim._instrument_for_port = {port_name: inst_id}
    sim._ports = {port_name: port}
    return sim


def _dmm_state_snapshot(session: Session) -> dict[str, object]:
    return dict(session.dmms["dmm1"].get_state().__dict__)


def test_backend_discovery_and_defaults(netlist_path) -> None:
    assert list_simulator_backends() == ("ngspice", "eespice")
    assert get_simulator_capabilities("ngspice").source_currents is True
    assert get_simulator_capabilities("eespice").source_currents is False

    session = _session_with_psu(netlist_path.parent)
    assert isinstance(session.kernel, NgspiceKernel)

    sim = SimSession.from_netlist(netlist_path).ports(vdd=Port.supply("vload", "0"))
    assert isinstance(sim._require_session().kernel, NgspiceKernel)


def test_eespice_kernel_is_opt_in_and_reason_coded(tmp_path) -> None:
    session = Session(
        circuit=_circuit(tmp_path),
        bench=BenchConfig(
            bench_id="psu",
            instruments={"psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=1.0)])},
        ),
        wiring=WiringConfig(
            connections=[
                Connection(from_="psu1.CH1.HI", to="vload"),
                Connection(from_="psu1.CH1.LO", to="0"),
            ]
        ),
        spice_engine="eespice",
    )
    assert isinstance(session.kernel, EEspiceCliKernel)
    with pytest.raises(UnsupportedCapability) as excinfo:
        session.kernel.op(session, ["vload"], settings=session.kernel_settings)
    assert excinfo.value.backend == "eespice"
    assert UnsupportedReason.OUTPUT_VECTOR_UNPROVEN in excinfo.value.reasons


def test_sim_psu_read_current_rejects_unsupported_current_vectors(tmp_path) -> None:
    session = _session_with_psu(tmp_path)
    fake = NoCurrentKernel()
    session.kernel = fake
    sim = _sim_with_session(tmp_path, session, "vdd", "psu1", Port.supply("vload", "0"))

    with pytest.raises(UnsupportedCapability) as excinfo:
        sim.psu("vdd").read_current()

    assert UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED in excinfo.value.reasons
    assert fake.op_calls == 0


def test_sim_dmm_read_current_rejects_unsupported_current_vectors(tmp_path) -> None:
    session = _session_with_dmm(tmp_path)
    fake = NoCurrentKernel()
    session.kernel = fake
    sim = _sim_with_session(
        tmp_path,
        session,
        "imeas",
        "dmm1",
        Port.current_measurement("vload", "0"),
    )

    with pytest.raises(UnsupportedCapability) as excinfo:
        sim.dmm("imeas").read_dc_current()

    assert UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED in excinfo.value.reasons
    assert fake.op_calls == 0


def test_scpi_current_queries_reject_unsupported_current_vectors(tmp_path) -> None:
    psu_session = _session_with_psu(tmp_path)
    psu_session.kernel = NoCurrentKernel()
    psu_backend = SimbenchScpiBackend(session=psu_session, instrument_id="psu1")
    with pytest.raises(UnsupportedCapability) as psu_exc:
        psu_backend.query("MEAS:CURR?")
    assert UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED in psu_exc.value.reasons

    dmm_session = _session_with_dmm(tmp_path)
    dmm_session.kernel = NoCurrentKernel()
    dmm_backend = SimbenchScpiBackend(session=dmm_session, instrument_id="dmm1")
    dmm_backend.write('SENS:FUNC "DCI"')
    with pytest.raises(UnsupportedCapability) as dmm_exc:
        dmm_backend.query("READ?")
    assert UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED in dmm_exc.value.reasons


@pytest.mark.parametrize("function", ['"ACI"', '"CURR:AC"'])
def test_dmm_ac_current_rejects_direct_and_scpi_without_voltage_fallback(
    tmp_path,
    function: str,
) -> None:
    session = _session_with_dmm(tmp_path)
    session.kernel = CurrentCapableNoVectorKernel()
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        session.dmms["dmm1"].set_state(function=function)
    session.dmms["dmm1"].state.function = "ACI"
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        session.read_dmm("dmm1", 1.23)
    assert session.kernel.op_calls == 0

    dmm_backend = SimbenchScpiBackend(session=session, instrument_id="dmm1")
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        dmm_backend.write(f"SENS:FUNC {function}")
    session.dmms["dmm1"].state.function = "ACI"
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        dmm_backend.query("READ?")
    assert session.kernel.op_calls == 0
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        dmm_backend.query("MEAS?")
    assert session.kernel.op_calls == 0


@pytest.mark.parametrize("command", ["MEAS:CURR:AC?", "MEAS:ACI?"])
def test_dmm_one_shot_ac_current_rejects_without_voltage_fallback(
    tmp_path,
    command: str,
) -> None:
    session = _session_with_dmm(tmp_path)
    session.kernel = CurrentCapableNoVectorKernel()
    dmm_backend = SimbenchScpiBackend(session=session, instrument_id="dmm1")

    with pytest.raises(ValueError, match="AC current.*unsupported"):
        dmm_backend.query(command)
    assert session.dmms["dmm1"].state.function == "DCV"
    assert session.kernel.op_calls == 0


@pytest.mark.parametrize("command", ["CONF:CURR:AC", "CONF:ACI"])
def test_dmm_config_ac_current_rejects_without_config_fallback(
    tmp_path,
    command: str,
) -> None:
    session = _session_with_dmm(tmp_path)
    session.kernel = CurrentCapableNoVectorKernel()
    dmm_backend = SimbenchScpiBackend(session=session, instrument_id="dmm1")
    before_state = _dmm_state_snapshot(session)

    with pytest.raises(ValueError, match="AC current.*unsupported"):
        dmm_backend.query(command)

    assert _dmm_state_snapshot(session) == before_state
    assert session.kernel.op_calls == 0


def test_dmm_one_shot_dc_current_uses_requested_function_and_restores_state(
    tmp_path,
) -> None:
    session = _session_with_dmm(tmp_path)
    session.kernel = CurrentCapableNoVectorKernel()
    dmm_backend = SimbenchScpiBackend(session=session, instrument_id="dmm1")
    before_state = _dmm_state_snapshot(session)

    with pytest.raises(UnsupportedCapability) as excinfo:
        dmm_backend.query("MEAS:CURR:DC?")

    assert UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED in excinfo.value.reasons
    assert _dmm_state_snapshot(session) == before_state
    assert session.kernel.op_calls == 1


def test_dmm_one_shot_dc_current_requires_current_terminals(tmp_path) -> None:
    session = _session_with_voltage_dmm(tmp_path)
    session.kernel = CurrentCapableNoVectorKernel()
    dmm_backend = SimbenchScpiBackend(session=session, instrument_id="dmm1")
    before_state = _dmm_state_snapshot(session)

    with pytest.raises(ValueError, match="current terminals are not wired"):
        dmm_backend.query("MEAS:CURR:DC?")

    assert _dmm_state_snapshot(session) == before_state
    assert session.kernel.op_calls == 0


def test_capability_aware_missing_vectors_are_contract_failures(tmp_path) -> None:
    psu_session = _session_with_psu(tmp_path)
    psu_fake = CurrentCapableNoVectorKernel()
    psu_session.kernel = psu_fake
    sim = _sim_with_session(
        tmp_path,
        psu_session,
        "vdd",
        "psu1",
        Port.supply("vload", "0"),
    )

    with pytest.raises(UnsupportedCapability) as psu_exc:
        sim.psu("vdd").read_current()
    assert UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED in psu_exc.value.reasons
    assert "psu1.CH1" in psu_exc.value.details[0]
    assert psu_fake.op_calls == 1

    dmm_session = _session_with_dmm(tmp_path)
    dmm_fake = CurrentCapableNoVectorKernel()
    dmm_session.kernel = dmm_fake
    dmm_backend = SimbenchScpiBackend(session=dmm_session, instrument_id="dmm1")
    dmm_backend.write('SENS:FUNC "DCI"')
    with pytest.raises(UnsupportedCapability) as dmm_exc:
        dmm_backend.query("READ?")
    assert UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED in dmm_exc.value.reasons
    assert "dmm1.I" in dmm_exc.value.details[0]
    assert dmm_fake.op_calls == 1


def test_eespice_structured_source_spacing() -> None:
    from pytestlab.sim.circuit.simulators.dialects import space_source_functions

    assert space_source_functions("SIN(0 1 1k)") == "SIN (0 1 1k)"
    assert space_source_functions("PULSE(0 1 0 1n)") == "PULSE (0 1 0 1n)"
