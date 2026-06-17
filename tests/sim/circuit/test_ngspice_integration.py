from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from pytestlab.sim.circuit import Port
from pytestlab.sim.circuit import Session
from pytestlab.sim.circuit import SimSession
from pytestlab.sim.circuit.bench import AWG
from pytestlab.sim.circuit.bench import DMM
from pytestlab.sim.circuit.bench import PSU
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.bench import PSUChannel
from pytestlab.sim.circuit.bench import Scope
from pytestlab.sim.circuit.factories import circuit_from_netlist
from pytestlab.sim.circuit.spice import AcSweepSpec
from pytestlab.sim.circuit.spice import simulate_ac
from pytestlab.sim.circuit.spice import simulate_op
from pytestlab.sim.circuit.spice import simulate_transient
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringConfig
from pytestlab.sim.circuit.wiring import WiringRules

pytestmark = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice not installed")


def _circuit(path: Path):
    return circuit_from_netlist(
        path,
        metadata={
            "title": path.stem,
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op", "ac", "tran"],
        },
    )


def _scope_session(path: Path) -> Session:
    bench = BenchConfig(bench_id="scope", instruments={"scope1": Scope(channels=1)})
    wiring = WiringConfig(
        connections=[
            Connection(from_="scope1.CH1.HI", to="vout"),
            Connection(from_="scope1.CH1.LO", to="0"),
        ]
    )
    return Session(circuit=_circuit(path), bench=bench, wiring=wiring, seed=1)


def test_ngspice_op_ac_tran_paths(tmp_path: Path) -> None:
    op = tmp_path / "op.cir"
    op.write_text("RC OP\nV1 vin 0 DC 1\nR1 vin vout 1000\nR2 vout 0 1000\n.end\n")
    op_result = simulate_op(_scope_session(op), ["vout"])
    assert float(np.mean(op_result.node_voltages["vout"])) == pytest.approx(0.49975, abs=1e-5)

    ac = tmp_path / "ac.cir"
    ac.write_text("RC AC\nV1 vin 0 DC 0 AC 1\nR1 vin vout 1000\nC1 vout 0 1u\n.end\n")
    ac_result = simulate_ac(
        _scope_session(ac),
        ["vout"],
        AcSweepSpec(points=5, start_hz=10, stop_hz=100_000),
    )
    assert np.iscomplexobj(ac_result.node_voltages["vout"])
    assert abs(ac_result.node_voltages["vout"][-1]) < abs(ac_result.node_voltages["vout"][0])

    tran = tmp_path / "tran.cir"
    tran.write_text(
        "RC TRAN\nV1 vin 0 PULSE(0 1 0 1u 1u 1m 2m)\nR1 vin vout 1000\nC1 vout 0 1u\n.end\n"
    )
    tran_result = simulate_transient(
        _scope_session(tran),
        ["vout"],
        sample_rate=10_000,
        record_length=20,
    )
    assert tran_result.node_voltages["vout"].size == 20
    assert float(tran_result.node_voltages["vout"][-1]) > 0.0


def test_ngspice_psu_current_limit(tmp_path: Path) -> None:
    netlist = tmp_path / "psu.cir"
    netlist.write_text("PSU load\nRLOAD vload 0 1\n.end\n")
    bench = BenchConfig(
        bench_id="psu",
        instruments={"psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=5.0)])},
    )
    wiring = WiringConfig(
        connections=[
            Connection(from_="psu1.CH1.HI", to="vload"),
            Connection(from_="psu1.CH1.LO", to="0"),
        ]
    )
    session = Session(circuit=_circuit(netlist), bench=bench, wiring=wiring, seed=1)
    session.psus["psu1"].set_state(channel="CH1", voltage_setpoint=12.0, current_limit=0.1)
    session.psus["psu1"].set_state(channel="CH1", enabled=True)

    result = simulate_op(session, ["vload"], currents=["psu1.CH1"])

    assert float(np.mean(result.node_voltages["vload"])) == pytest.approx(0.1, abs=0.005)
    assert abs(float(np.mean(result.source_currents["psu1.CH1"]))) == pytest.approx(
        0.1,
        abs=0.005,
    )


@pytest.mark.parametrize(
    ("load_ohm", "expected_v", "expected_i"),
    [
        (1_000.0, 12.0, 0.012),
        (120.0, 12.0, 0.1),
        (1.0, 0.1, 0.1),
    ],
)
def test_ngspice_psu_cv_cc_load_sweep(
    tmp_path: Path,
    load_ohm: float,
    expected_v: float,
    expected_i: float,
) -> None:
    netlist = tmp_path / "psu_sweep.cir"
    netlist.write_text(f"PSU sweep\nRLOAD vload 0 {load_ohm:.12g}\n.end\n")
    bench = BenchConfig(
        bench_id="psu",
        instruments={"psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=5.0)])},
    )
    wiring = WiringConfig(
        connections=[
            Connection(from_="psu1.CH1.HI", to="vload"),
            Connection(from_="psu1.CH1.LO", to="0"),
        ]
    )
    session = Session(circuit=_circuit(netlist), bench=bench, wiring=wiring, seed=1)
    session.psus["psu1"].set_state(channel="CH1", voltage_setpoint=12.0, current_limit=0.1)
    session.psus["psu1"].set_state(channel="CH1", enabled=True)

    result = simulate_op(session, ["vload"], currents=["psu1.CH1"])

    voltage = float(np.mean(result.node_voltages["vload"]))
    delivered_current = -float(np.mean(result.source_currents["psu1.CH1"]))
    assert voltage == pytest.approx(expected_v, abs=0.01)
    assert delivered_current == pytest.approx(expected_i, abs=0.003)


def test_ngspice_dmm_current_readback(tmp_path: Path) -> None:
    netlist = tmp_path / "dmm_current.cir"
    netlist.write_text("DMM current\nV1 vin 0 DC 1\nRLOAD load 0 1000\n.end\n")
    bench = BenchConfig(bench_id="dmm", instruments={"dmm1": DMM(burden_ohm=0.1)})
    wiring = WiringConfig(
        connections=[
            Connection(from_="dmm1.I.HI", to="vin"),
            Connection(from_="dmm1.I.LO", to="load"),
            Connection(from_="dmm1.V.HI", to="load"),
            Connection(from_="dmm1.V.LO", to="0"),
        ],
        rules=WiringRules(forbid_multiple_ground_nodes=False),
    )
    session = Session(circuit=_circuit(netlist), bench=bench, wiring=wiring, seed=1)

    result = simulate_op(session, ["vin", "load"], currents=["dmm1.I"])

    current = float(np.mean(result.element_currents["dmm1.I"]))
    assert current == pytest.approx(1.0 / 1000.1, rel=0.002)
    assert float(np.mean(result.node_voltages["load"])) == pytest.approx(
        current * 1000.0,
        rel=0.002,
    )


def test_ngspice_sim_session_current_measurement_readback(tmp_path: Path) -> None:
    netlist = tmp_path / "sim_session_dmm_current.cir"
    netlist.write_text("DMM public current\nV1 vin 0 DC 1\nRLOAD load 0 1000\n.end\n")

    with SimSession.from_netlist(netlist, seed=7).ports(
        imeas=Port.current_measurement("vin", "load"),
        ref=Port.probe("0", "0"),
    ) as sim:
        current = sim.dmm("imeas").read_dc_current()

    assert current == pytest.approx(1.0 / 1000.1, rel=0.01)


def test_ngspice_awg_sine_and_pulse_sources(tmp_path: Path) -> None:
    netlist = tmp_path / "awg.cir"
    netlist.write_text("AWG source\nRLOAD vin 0 1000\n.end\n")
    bench = BenchConfig(bench_id="awg", instruments={"awg1": AWG(vpp_max=10.0)})
    wiring = WiringConfig(
        connections=[
            Connection(from_="awg1.HI", to="vin"),
            Connection(from_="awg1.LO", to="0"),
        ]
    )
    session = Session(circuit=_circuit(netlist), bench=bench, wiring=wiring, seed=1)

    session.awgs["awg1"].set_state(
        waveform="sine",
        frequency_hz=1_000.0,
        amplitude_vpp=2.0,
        offset_v=0.0,
        enabled=True,
    )
    sine = simulate_transient(session, ["vin"], sample_rate=20_000, record_length=40)
    sine_v = sine.node_voltages["vin"]
    assert sine_v.max() > 0.85
    assert sine_v.min() < -0.85

    session.awgs["awg1"].set_state(
        waveform="pulse",
        frequency_hz=1_000.0,
        amplitude_vpp=2.0,
        offset_v=1.0,
        duty_cycle=0.5,
        enabled=True,
    )
    pulse = simulate_transient(session, ["vin"], sample_rate=20_000, record_length=40)
    pulse_v = pulse.node_voltages["vin"]
    assert pulse_v.max() > 1.7
    assert pulse_v.min() < 0.3


def test_two_transistor_inverter_transfer_curve_with_dmm_and_psu(tmp_path: Path) -> None:
    netlist = tmp_path / "two_transistor_inverter.sp"
    netlist.write_text(
        """Two transistor CMOS inverter
.model NMOS NMOS(Level=1 VTO=1.0 KP=200u LAMBDA=0.02)
.model PMOS PMOS(Level=1 VTO=-1.0 KP=100u LAMBDA=0.02)
M1 vout vin 0 0 NMOS L=1u W=10u
M2 vout vin vdd vdd PMOS L=1u W=20u
RLOAD vout 0 1Meg
.end
"""
    )

    with SimSession.from_netlist(netlist, seed=42).ports(
        vin=Port.signal("vin", "0"),
        vdd=Port.supply("vdd", "0"),
        vout=Port.voltage_measurement("vout", "0"),
    ) as sim:
        awg = sim.awg("vin")
        psu = sim.psu("vdd", voltage=5.0, current_limit=0.05).on()
        dmm = sim.dmm("vout")

        sweep = sim.sweep(
            param_name="vin",
            param_unit="V",
            values=np.linspace(0.0, 5.0, 11),
            setup=lambda value: awg.dc(level=value),
            measure=lambda: {
                "vout": dmm.read_dc_voltage(),
                "idd": psu.read_current(),
            },
        )

    vout = np.asarray(sweep["vout"], dtype=float)
    idd = np.asarray(sweep["idd"], dtype=float)

    assert vout[0] > 4.0
    assert vout[-1] < 1.0
    assert np.any(np.diff(vout) < -0.5)
    assert np.isfinite(vout).all()
    assert np.isfinite(idd).all()
    assert idd[5] > idd[0] * 100.0
