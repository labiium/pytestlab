"""Phase 2: typed-first node namespace via Netlist.

A Netlist hands out validated NodeRefs, so node typos fail at the line you
write them rather than at simulation time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytestlab.sim.circuit import Netlist
from pytestlab.sim.circuit import NodeRef
from pytestlab.sim.circuit import Port
from pytestlab.sim.circuit import SimSession
from pytestlab.sim.circuit import UnknownNode

NETLIST_TEXT = """\
.model QNPN NPN(IS=6.7f BF=255 VAF=74)
RIN vin b1 10k
Q1 vcc b1 drive QNPN
RE1 drive 0 22k
Q2 vout b2 0 QNPN
RC2 vcc vout 2.2k
.end
"""


@pytest.fixture()
def netlist_file(tmp_path: Path) -> Path:
    path = tmp_path / "amp.sp"
    path.write_text(NETLIST_TEXT)
    return path


def test_netlist_exposes_node_set(netlist_file):
    net = Netlist.from_file(netlist_file)
    assert net.nodes == {"0", "vin", "b1", "vcc", "drive", "vout", "b2"}
    assert net.source == netlist_file


def test_node_returns_noderef_for_real_node(netlist_file):
    net = Netlist.from_file(netlist_file)
    ref = net.node("vout")
    assert isinstance(ref, NodeRef)
    assert str(ref) == "vout"


def test_node_typo_raises_unknown_node_with_suggestion(netlist_file):
    net = Netlist.from_file(netlist_file)
    with pytest.raises(UnknownNode) as exc:
        net.node("vaut")
    assert exc.value.suggestion == "vout"


def test_attribute_access_returns_validated_ref(netlist_file):
    net = Netlist.from_file(netlist_file)
    assert str(net.vout) == "vout"


def test_attribute_access_typo_raises_attribute_error(netlist_file):
    net = Netlist.from_file(netlist_file)
    with pytest.raises(AttributeError):
        net.vaut  # noqa: B018 - exercising __getattr__


def test_membership_and_case_insensitivity(netlist_file):
    net = Netlist.from_file(netlist_file)
    assert "vout" in net
    assert "VOUT" in net
    assert "nope" not in net
    assert str(net.node("VOUT")) == "vout"


def test_ground_is_always_available(netlist_file):
    net = Netlist.from_file(netlist_file)
    assert str(net.node("0")) == "0"
    assert str(net.ground()) == "0"


def test_ports_accept_noderefs(netlist_file):
    net = Netlist.from_file(netlist_file)
    port = Port.voltage_measurement(net.vout, net.ground())
    assert port.hi_node == "vout"
    assert port.lo_node == "0"


def test_from_netlist_accepts_netlist_object(netlist_file):
    net = Netlist.from_file(netlist_file)
    sim = SimSession.from_netlist(net).ports(
        vin=Port.signal(net.vin),
        vcc=Port.supply(net.vcc),
        vout=Port.voltage_measurement(net.vout),
    )
    assert sim.netlist_path == netlist_file


def test_from_netlist_requires_source_for_sourceless_netlist():
    net = Netlist(NETLIST_TEXT)  # no source file
    with pytest.raises(ValueError, match="no source file"):
        SimSession.from_netlist(net)


def test_netlist_resolves_included_nodes(tmp_path):
    (tmp_path / "rail.sp").write_text("RL vout 0 1k\n")
    top = tmp_path / "top.sp"
    top.write_text("R1 vin vout 1k\n.include rail.sp\n.end\n")
    net = Netlist.from_file(top)
    # A node defined only in the included file resolves as a valid reference.
    assert "vout" in net
    assert str(net.vout) == "vout"


def test_included_node_is_validated_through_session(tmp_path):
    (tmp_path / "rail.sp").write_text("RL vout 0 1k\n")
    top = tmp_path / "top.sp"
    top.write_text("R1 vin vout 1k\n.include rail.sp\n.end\n")
    # Valid included node builds cleanly; a typo of it still raises.
    SimSession.from_netlist(top).ports(vout=Port.voltage_measurement("vout", "0"))
    with pytest.raises(UnknownNode):
        SimSession.from_netlist(top).ports(vout=Port.voltage_measurement("voot", "0"))
