from __future__ import annotations

import numpy as np

from pytestlab.sim.circuit import Session
from pytestlab.sim.circuit.bench import AWG
from pytestlab.sim.circuit.bench import PSU
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.bench import PSUChannel
from pytestlab.sim.circuit.bench import Scope
from pytestlab.sim.circuit.factories import circuit_from_netlist
from pytestlab.sim.circuit.scpi import SimbenchScpiBackend
from pytestlab.sim.circuit.spice import _build_augmented_netlist
from pytestlab.sim.circuit.spice import _parse_complex_wrdata
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringConfig
from pytestlab.sim.circuit.wiring import WiringRules


def test_ac_wrdata_complex_preserved() -> None:
    data = np.asarray(
        [
            [10.0, 1.0, 0.0],
            [100.0, 0.5, -0.25],
        ],
        dtype=float,
    )
    scale, series = _parse_complex_wrdata(data, 1)
    assert scale.tolist() == [10.0, 100.0]
    assert np.iscomplexobj(series)
    assert series[:, 0].tolist() == [1.0 + 0.0j, 0.5 - 0.25j]


def test_psu_injects_current_clamp(netlist_path) -> None:
    bench = BenchConfig(
        bench_id="psu",
        instruments={
            "psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=1.0)]),
        },
    )
    wiring = WiringConfig(
        connections=[
            Connection(from_="psu1.CH1.HI", to="vload"),
            Connection(from_="psu1.CH1.LO", to="0"),
        ]
    )
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": "psu",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op"],
        },
    )
    session = Session(circuit=circuit, bench=bench, wiring=wiring)
    session.psus["psu1"].set_state(channel="CH1", voltage_setpoint=12.0, current_limit=0.1)
    session.psus["psu1"].set_state(channel="CH1", enabled=True)

    lines, _, element_currents, _ = _build_augmented_netlist(session)
    text = "\n".join(lines)
    assert "I_SB_LIM_psu1_CH1 0 n_sb_psu_psu1_CH1 DC 0.1" in text
    assert "D_SB_CLAMP_psu1_CH1" in text
    assert "V_SB_SENSE_psu1_CH1" in text
    assert element_currents["psu1.CH1"] == "V_SB_SENSE_psu1_CH1"


def test_scope_default_loading_is_injected(netlist_path) -> None:
    bench = BenchConfig(bench_id="scope", instruments={"scope1": Scope(channels=1)})
    wiring = WiringConfig(
        connections=[
            Connection(from_="scope1.CH1.HI", to="vout"),
            Connection(from_="scope1.CH1.LO", to="0"),
        ]
    )
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": "scope",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op"],
        },
    )
    session = Session(circuit=circuit, bench=bench, wiring=wiring)

    lines, _, _, _ = _build_augmented_netlist(session)
    text = "\n".join(lines)
    assert "R_SB_SCOPE_scope1_CH1 vout 0 1000000" in text
    assert "C_SB_SCOPE_scope1_CH1 vout 0 1.5e-11" in text


def test_scope_digitize_while_stopped(netlist_path) -> None:
    bench = BenchConfig(
        bench_id="scope-stop",
        instruments={
            "awg1": AWG(vpp_max=10.0),
            "scope1": Scope(channels=1),
        },
    )
    wiring = WiringConfig(
        connections=[
            Connection(from_="awg1.HI", to="vin"),
            Connection(from_="awg1.LO", to="0"),
            Connection(from_="scope1.CH1.HI", to="vout"),
            Connection(from_="scope1.CH1.LO", to="0"),
        ],
        rules=WiringRules(allow_output_sharing=True),
    )
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": "scope-stop",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["tran"],
        },
    )
    session = Session(circuit=circuit, bench=bench, wiring=wiring)
    backend = SimbenchScpiBackend(session=session, instrument_id="scope1")

    backend.write("STOP")
    backend.write("DIGITIZE CHANnel1")

    assert "-221" in backend.query("SYST:ERR?")
    assert backend._scope_captures.get("CHANnel1") is None


def test_simbench_scpi_accepts_full_and_short_dmm_mnemonics(netlist_path) -> None:
    from pytestlab.sim.circuit.bench import DMM

    bench = BenchConfig(bench_id="dmm-scpi", instruments={"dmm1": DMM()})
    wiring = WiringConfig(
        connections=[
            Connection(from_="dmm1.V.HI", to="vload"),
            Connection(from_="dmm1.V.LO", to="0"),
        ]
    )
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": "dmm-scpi",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op"],
        },
    )
    session = Session(circuit=circuit, bench=bench, wiring=wiring)
    backend = SimbenchScpiBackend(session=session, instrument_id="dmm1")

    backend.write(":SENSe:VOLTage:DC:RANGe:AUTO ON")
    backend.write(":SENS:VOLT:DC:RANG:AUTO OFF")
    backend.write(":SENSe:VOLTage:DC:RESolution 6")
    backend.write(":SENS:VOLT:DC:RES 5")
    assert backend.query(":CONFigure:VOLTage:DC?").startswith("DCV")
    assert backend.query(":CONF:VOLT:DC?").startswith("DCV")
    assert float(backend.query(":MEASure:VOLTage:DC?")) == float(backend.query(":MEAS:VOLT:DC?"))


def test_simbench_scpi_accepts_full_and_short_psu_awg_scope_mnemonics(netlist_path) -> None:
    bench = BenchConfig(
        bench_id="mixed-scpi",
        instruments={
            "psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=1.0)]),
            "awg1": AWG(vpp_max=10.0),
            "scope1": Scope(channels=1),
        },
    )
    wiring = WiringConfig(
        connections=[
            Connection(from_="psu1.CH1.HI", to="vdd"),
            Connection(from_="psu1.CH1.LO", to="0"),
            Connection(from_="awg1.HI", to="vin"),
            Connection(from_="awg1.LO", to="0"),
            Connection(from_="scope1.CH1.HI", to="vout"),
            Connection(from_="scope1.CH1.LO", to="0"),
        ],
        rules=WiringRules(allow_output_sharing=True),
    )
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": "mixed-scpi",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op", "tran"],
        },
    )
    session = Session(circuit=circuit, bench=bench, wiring=wiring)

    psu = SimbenchScpiBackend(session=session, instrument_id="psu1")
    psu.write(":INSTrument:NSELect 1")
    psu.write(":VOLTage 2.5")
    psu.write(":CURRent:LEVel 0.1")
    psu.write(":OUTPut:STATe ON")
    assert psu.query(":OUTP:STAT?") == "1"
    assert psu.query(":OUTPut:STATe?") == "1"

    awg = SimbenchScpiBackend(session=session, instrument_id="awg1")
    awg.write(":SOURce1:FUNCtion SINusoid")
    awg.write(":SOURce1:FREQuency 1000")
    awg.write(":SOURce1:VOLTage:OFFSet 0.25")
    awg.write(":OUTPut1:STATe ON")
    assert awg.query(":SOUR1:FUNC?") == "sine"
    assert awg.query(":SOURce1:FREQuency?") == "1000"
    assert awg.query(":SOUR1:VOLT:OFFS?") == "0.25"
    assert awg.query(":OUTPut1:STATe?") == "1"

    scope = SimbenchScpiBackend(session=session, instrument_id="scope1")
    scope.write(":TIMebase:SCALe 0.001")
    scope.write(":TIM:POS 0.0001")
    scope.write(":ACQuire:SRATe:ANALog MAX")
    scope.write(":TRIGger:EDGE:SOURce CHANnel1")
    scope.write(":TRIGger:EDGE:LEVel CHANnel1,0.5")
    scope.write(":CHANnel1:SCALe 2")
    scope.write(":CHAN1:OFFSet 0.1")
    scope.write(":CHANnel1:COUPling DC")
    scope.write(":WAVeform:SOURce CHANnel1")
    assert scope._scope_selected_source == "CHANnel1"
    assert scope.query(":TIMebase:SCALe?") == "0.001"
    assert scope.query(":TIM:POSition?") == "0.0001"
    assert scope.query(":WAVeform:POINts?").isdigit()
