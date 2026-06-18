from __future__ import annotations

import numpy as np
import pytest

from pytestlab.sim.circuit import Port
from pytestlab.sim.circuit import SimSession
from pytestlab.sim.circuit.results import BodeResult
from pytestlab.sim.circuit.results import SweepResult
from pytestlab.sim.circuit.results import WaveformResult
from pytestlab.sim.circuit.spice import SpiceResult


class FakeKernel:
    def __init__(self) -> None:
        self.ac_calls = 0
        self.tran_calls = 0
        self.op_calls = 0

    def op(self, session, nodes, *, settings=None, currents=None, params=None):
        self.op_calls += 1
        node_voltages = {node: np.asarray([5.0]) for node in nodes}
        source_currents = {"psu1.CH1": np.asarray([-0.02])}
        element_currents = {"dmm1.I": np.asarray([0.001]), "dmm2.I": np.asarray([0.001])}
        return SpiceResult(
            "op",
            np.asarray([0.0]),
            "op",
            node_voltages,
            source_currents,
            (),
            element_currents,
        )

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
        self.tran_calls += 1
        time = np.arange(record_length, dtype=float) / sample_rate
        node_voltages = {node: np.sin(2.0 * np.pi * 1_000.0 * time) for node in nodes}
        return SpiceResult("tran", time, "s", node_voltages, {}, (), metadata={"fake": True})

    def ac(self, session, nodes, sweep, *, settings=None, currents=None, params=None):
        self.ac_calls += 1
        freq = np.asarray([10.0, 100.0, 1_000.0])
        node_voltages = {}
        for node in nodes:
            node_voltages[node] = np.ones_like(freq, dtype=complex)
        if "vout" in node_voltages:
            node_voltages["vout"] = np.asarray([1.0 + 0.0j, 0.5 + 0.0j, 0.1 + 0.0j])
        return SpiceResult(
            "ac", freq, "Hz", node_voltages, {}, (), metadata={"points": sweep.points}
        )

    def dc_sweep(self, session, nodes, sweep, *, settings=None, currents=None, params=None):
        scale = np.arange(sweep.start, sweep.stop + sweep.step / 2.0, sweep.step)
        node_voltages = {node: scale for node in nodes}
        return SpiceResult("dc", scale, "V", node_voltages, {}, ())


def _sim(netlist_path):
    sim = SimSession.from_netlist(netlist_path).ports(
        vin=Port.signal("vin", "0"),
        vout=Port.probe("vout", "0"),
        vdd=Port.supply("vdd", "0"),
        vmeas=Port.measurement("vout", "0"),
        imeas=Port.current_measurement("vout", "0"),
    )
    fake = FakeKernel()
    sim._require_session().kernel = fake
    return sim, fake


def test_awg_waveforms_update_twin_state(netlist_path) -> None:
    sim, _ = _sim(netlist_path)
    awg = sim.awg("vin").sine(freq_hz=1_000.0, amplitude_vpp=2.0, phase_deg=45.0)
    state = awg.session.awgs[awg.instrument_id].state

    assert state.waveform == "sine"
    assert state.enabled is True
    assert state.frequency_hz == 1_000.0
    assert state.phase_deg == 45.0
    assert (
        awg.square(freq_hz=2_000.0, amplitude_vpp=1.0)
        .session.awgs[awg.instrument_id]
        .state.waveform
        == "square"
    )


def test_psu_channel_chain_and_readback(netlist_path) -> None:
    sim, fake = _sim(netlist_path)
    psu = sim.psu("vdd")

    psu.channel(1).set(voltage=5.0, current_limit=0.1).on()
    assert psu.session.psus[psu.instrument_id].state.channels["CH1"].enabled is True
    assert psu.read_voltage() == 5.0
    assert np.isclose(psu.read_current(), 0.02)
    assert fake.op_calls >= 2


def test_scope_capture_and_bode_use_kernel_once(netlist_path) -> None:
    sim, fake = _sim(netlist_path)
    awg = sim.awg("vin").sine(freq_hz=1_000.0, amplitude_vpp=1.0)
    scope = sim.scope("vout").trigger(0.0).coupling("DC").vertical_scale(1.0).run()

    capture = scope.capture(duration=1e-3, sample_rate=10_000.0)
    assert isinstance(capture, WaveformResult)
    assert capture.voltage.shape == (10,)

    bode = scope.bode(source=awg, freq_range=(10.0, 1_000.0), points=3)
    assert isinstance(bode, BodeResult)
    assert fake.ac_calls == 1


def test_dmm_read_dc_voltage_uses_op(netlist_path) -> None:
    sim, fake = _sim(netlist_path)
    dmm = sim.dmm("vmeas").configure(function="DCV")

    assert np.isclose(dmm.read_dc_voltage(), 5.0, atol=1e-3)
    assert fake.op_calls == 1


def test_dmm_measurement_ports_are_mode_specific(netlist_path) -> None:
    sim, _ = _sim(netlist_path)
    mapping = sim._require_session().mapping

    assert "dmm1.V.HI" in mapping
    assert "dmm1.V.LO" in mapping
    assert "dmm1.I.HI" not in mapping
    assert "dmm1.I.LO" not in mapping

    assert "dmm2.I.HI" in mapping
    assert "dmm2.I.LO" in mapping
    assert "dmm2.V.HI" not in mapping
    assert "dmm2.V.LO" not in mapping

    assert np.isclose(sim.dmm("imeas").read(), 0.001, atol=1e-5)

    with pytest.raises(ValueError, match="voltage-only"):
        sim.dmm("vmeas").read_dc_current()
    with pytest.raises(ValueError, match="current-only"):
        sim.dmm("imeas").read_dc_voltage()
    with pytest.raises(ValueError, match="voltage-only"):
        sim.dmm("vmeas").configure(function="DCI")
    with pytest.raises(ValueError, match="current-only"):
        sim.dmm("imeas").configure(function="DCV")
    with pytest.raises(ValueError, match="voltage-only"):
        sim.dmm("vmeas").configure(function="CURR:DC")
    with pytest.raises(ValueError, match="current-only"):
        sim.dmm("imeas").configure(function="VOLT:DC")
    with pytest.raises(ValueError, match="current-only"):
        sim.dmm("imeas").configure(function="VOLT:AC")


@pytest.mark.parametrize("function", ["ACI", "CURR:AC"])
def test_dmm_ac_current_aliases_reject_without_fallback(netlist_path, function) -> None:
    sim, fake = _sim(netlist_path)

    with pytest.raises(ValueError, match="AC current.*unsupported"):
        sim.dmm("imeas").configure(function=function)
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        sim.dmm("vmeas").configure(function=function)

    dmm = sim.dmm("imeas")
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        dmm.session.dmms[dmm.instrument_id].set_state(function=function)
    dmm.session.dmms[dmm.instrument_id].state.function = "ACI"
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        dmm.read()
    assert fake.op_calls == 0

    voltage_dmm = sim.dmm("vmeas")
    voltage_dmm.session.dmms[voltage_dmm.instrument_id].state.function = "ACI"
    with pytest.raises(ValueError, match="AC current.*unsupported"):
        voltage_dmm.read()
    assert fake.tran_calls == 0


def test_voltage_dmm_read_honors_acv_configuration(netlist_path) -> None:
    sim, fake = _sim(netlist_path)
    dmm = sim.dmm("vmeas").configure(function="ACV")

    value = dmm.read()

    assert value > 0.5
    assert fake.tran_calls == 1


def test_current_measurement_can_be_series_between_non_ground_nodes(netlist_path) -> None:
    sim = SimSession.from_netlist(netlist_path).ports(
        vin=Port.signal("vin", "0"),
        imeas=Port.current_measurement("vin", "load"),
    )

    mapping = sim._require_session().mapping
    assert mapping["dmm1.I.HI"] == "vin"
    assert mapping["dmm1.I.LO"] == "load"


def test_session_sweep_returns_sweep_result(netlist_path) -> None:
    sim, _ = _sim(netlist_path)
    seen = []

    result = sim.sweep(
        param_name="vbias",
        param_unit="V",
        values=[0.0, 1.0, 2.0],
        setup=lambda value: seen.append(value),
        measure=lambda: {"vout": 1.23},
    )

    assert isinstance(result, SweepResult)
    assert seen == [0.0, 1.0, 2.0]
    assert result.to_dataframe().shape == (3, 2)
    assert np.isclose(result["vout"], [1.23, 1.23, 1.23]).all()
