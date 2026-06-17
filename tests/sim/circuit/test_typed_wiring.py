from __future__ import annotations

import pytest

from pytestlab.sim.circuit import NodeRef
from pytestlab.sim.circuit import TerminalRef
from pytestlab.sim.circuit import WiringBuilder
from pytestlab.sim.circuit import instrument_refs
from pytestlab.sim.circuit.bench import AWG
from pytestlab.sim.circuit.bench import DMM
from pytestlab.sim.circuit.bench import PSU
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.bench import PSUChannel
from pytestlab.sim.circuit.bench import Scope
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringCompiler
from pytestlab.sim.circuit.wiring import WiringConfig


def _bench() -> BenchConfig:
    return BenchConfig(
        bench_id="typed",
        instruments={
            "awg1": AWG(vpp_max=10.0),
            "psu1": PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=1.0)]),
            "scope1": Scope(channels=2),
            "dmm1": DMM(),
        },
    )


def test_node_ref_canonicalization() -> None:
    assert str(NodeRef("vout")) == "vout"
    assert str(NodeRef.ground()) == "0"
    with pytest.raises(ValueError, match="node name"):
        NodeRef("")


def test_terminal_ref_canonicalization() -> None:
    psu = instrument_refs.psu("psu1")
    scope = instrument_refs.scope("scope1")
    dmm = instrument_refs.dmm("dmm1")
    awg = instrument_refs.awg("awg1")

    assert str(psu.ch(1).hi) == "psu1.CH1.HI"
    assert str(psu.ch(1).plus) == "psu1.CH1.HI"
    assert str(psu.ch(1).minus) == "psu1.CH1.LO"
    assert str(scope.ch(2).lo) == "scope1.CH2.LO"
    assert str(dmm.voltage.hi) == "dmm1.V.HI"
    assert str(dmm.current.hi) == "dmm1.I.HI"
    assert str(awg.out.hi) == "awg1.HI"

    with pytest.raises(ValueError, match="instrument id"):
        TerminalRef("", ("HI",))


def test_wiring_builder_to_config_matches_raw_connections() -> None:
    psu = instrument_refs.psu("psu1")
    awg = instrument_refs.awg("awg1")
    dmm = instrument_refs.dmm("dmm1")
    gnd = NodeRef.ground()
    vin = NodeRef("vin")
    vout = NodeRef("vout")
    vdd = NodeRef("vdd")

    typed = (
        WiringBuilder(ground=gnd)
        .connect(psu.ch(1).hi, vdd)
        .connect(psu.ch(1).lo, gnd)
        .connect(awg.out.hi, vin)
        .connect(awg.out.lo, gnd)
        .connect(dmm.voltage.hi, vout)
        .connect(dmm.voltage.lo, gnd)
        .to_config()
    )
    raw = WiringConfig(
        connections=[
            Connection(from_="psu1.CH1.HI", to="vdd"),
            Connection(from_="psu1.CH1.LO", to="0"),
            Connection(from_="awg1.HI", to="vin"),
            Connection(from_="awg1.LO", to="0"),
            Connection(from_="dmm1.V.HI", to="vout"),
            Connection(from_="dmm1.V.LO", to="0"),
        ]
    )

    assert typed == raw
    assert WiringCompiler(_bench(), typed).compile() == WiringCompiler(_bench(), raw).compile()


def test_connection_accepts_terminal_and_node_refs() -> None:
    connection = Connection(from_=instrument_refs.scope("scope1").ch(1).hi, to=NodeRef("vout"))

    assert connection.from_ == "scope1.CH1.HI"
    assert connection.to == "vout"


def test_unknown_terminal_error_suggests_canonical_name() -> None:
    wiring = WiringConfig(
        connections=[
            Connection(from_="psu1.CH1+", to="vdd"),
            Connection(from_="psu1.CH1.LO", to="0"),
        ]
    )

    with pytest.raises(ValueError, match=r"Did you mean psu1[.]CH1[.]HI"):
        WiringCompiler(_bench(), wiring).compile()
