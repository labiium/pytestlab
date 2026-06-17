from __future__ import annotations

from pytestlab.sim.circuit import Session
from pytestlab.sim.circuit.bench import AWG
from pytestlab.sim.circuit.bench import DMM
from pytestlab.sim.circuit.bench import PSU
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.bench import PSUChannel
from pytestlab.sim.circuit.bench import Scope
from pytestlab.sim.circuit.factories import circuit_from_netlist
from pytestlab.sim.circuit.injectors import AwgInjector
from pytestlab.sim.circuit.injectors import DmmInjector
from pytestlab.sim.circuit.injectors import ProbeInjector
from pytestlab.sim.circuit.injectors import PsuInjector
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringConfig
from pytestlab.sim.circuit.wiring import WiringRules


def _session(netlist_path):
    bench = BenchConfig(
        bench_id="injectors",
        instruments={
            "awg1": AWG(vpp_max=10.0),
            "psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=1.0)]),
            "scope1": Scope(channels=1),
            "dmm1": DMM(),
        },
    )
    wiring = WiringConfig(
        connections=[
            Connection(from_="awg1.HI", to="vin"),
            Connection(from_="awg1.LO", to="0"),
            Connection(from_="psu1.CH1.HI", to="vdd"),
            Connection(from_="psu1.CH1.LO", to="0"),
            Connection(from_="scope1.CH1.HI", to="vout"),
            Connection(from_="scope1.CH1.LO", to="0"),
            Connection(from_="dmm1.V.HI", to="vout"),
            Connection(from_="dmm1.V.LO", to="0"),
            Connection(from_="dmm1.I.HI", to="vout"),
            Connection(from_="dmm1.I.LO", to="0"),
        ],
        rules=WiringRules(allow_output_sharing=True),
    )
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": "injectors",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op", "tran", "ac"],
        },
    )
    session = Session(circuit=circuit, bench=bench, wiring=wiring)
    session.awgs["awg1"].set_state(
        waveform="sine", frequency_hz=1_000.0, amplitude_vpp=1.0, enabled=True
    )
    session.psus["psu1"].set_state(
        channel="CH1", voltage_setpoint=5.0, current_limit=0.1, enabled=True
    )
    return session


def test_injectors_emit_expected_minimal_netlist(netlist_path) -> None:
    session = _session(netlist_path)

    awg = AwgInjector().inject(session)
    psu = PsuInjector().inject(session)
    dmm = DmmInjector().inject(session)
    probe = ProbeInjector().inject(session)

    assert any("V_SB_AWG_awg1" in line for line in awg.netlist_lines)
    assert any("I_SB_LIM_psu1_CH1" in line for line in psu.netlist_lines)
    assert any("D_SB_CLAMP_psu1_CH1" in line for line in psu.netlist_lines)
    assert dmm.element_currents["dmm1.I"].startswith("V_SB_DMMI_SENSE_")
    assert any("R_SB_SCOPE_scope1_CH1" in line for line in probe.netlist_lines)
