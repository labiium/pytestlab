"""Node-name validation: typos must fail loudly, not float silently.

Regression coverage for the silent-floating-node bug where a misspelled SPICE
node name returned ~0 V instead of raising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytestlab.sim.circuit import Port
from pytestlab.sim.circuit import SimSession
from pytestlab.sim.circuit.netlist import extract_nodes
from pytestlab.sim.circuit.spice import _warn_on_ngspice_diagnostics
from pytestlab.sim.circuit.wiring import UnknownNode

TWO_TRANSISTOR = """\
.model QNPN NPN(IS=6.7f BF=255 VAF=74)
RIN vin b1 10k
RBIAS vbias b1 10k
Q1 vcc b1 drive QNPN
RE1 drive 0 22k
Q2 vout b2 0 QNPN
RC2 vcc vout 2.2k
COUT vout 0 20p
.end
"""

MOSFET = """\
.model NMOS NMOS(VTO=1)
M1 vdrain vgate vsource vbody NMOS
RD vdd vdrain 1k
.end
"""

SUBCKT = """\
.subckt OPAMP inp inn out
RINT inp internal 1k
EOUT out 0 inp inn 1e5
.ends
X1 vin fb vout OPAMP
RF vout fb 10k
RG fb 0 10k
.end
"""


def _netlist(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "dut.sp"
    path.write_text(text)
    return path


# --- extractor -------------------------------------------------------------


def test_extract_nodes_captures_transistor_terminals_without_model_names():
    nodes = extract_nodes(TWO_TRANSISTOR)
    assert nodes == {"0", "vin", "b1", "vbias", "drive", "vcc", "b2", "vout"}
    assert "QNPN" not in nodes


def test_extract_nodes_handles_four_terminal_mosfet():
    nodes = extract_nodes(MOSFET)
    assert {"vdrain", "vgate", "vsource", "vbody", "vdd"} <= nodes
    assert "NMOS" not in nodes


def test_extract_nodes_uses_subckt_instance_pins_not_internal_nodes():
    nodes = extract_nodes(SUBCKT)
    # Top-level pins of the X instance and the feedback network are nodes...
    assert {"vin", "fb", "vout"} <= nodes
    # ...but nodes internal to the .subckt body are not reachable wiring targets.
    assert "internal" not in nodes
    assert "OPAMP" not in nodes


def test_extract_nodes_strips_inline_comments():
    # Comment words and the model name must not leak onto a transistor line.
    nodes = extract_nodes("Q1 c b e QMOD ; the comment words\n.end")
    assert nodes == {"0", "c", "b", "e"}
    nodes_dollar = extract_nodes("M1 d g s b NMOS L=1u W=2u $ sized device\n.end")
    assert nodes_dollar == {"0", "d", "g", "s", "b"}


def test_extract_nodes_handles_four_terminal_controlled_sources():
    # VCVS/VCCS expose output and control nodes; the gain is not a node.
    assert extract_nodes("E1 op on cp cn 100\n.end") == {"0", "op", "on", "cp", "cn"}


def test_extract_nodes_resolves_includes(tmp_path):
    (tmp_path / "sub.sp").write_text("R2 vmid vout 1k\nC1 vout 0 1u\n")
    top = tmp_path / "top.sp"
    top.write_text("R1 vin vmid 1k\n.include sub.sp\n.end\n")
    nodes = extract_nodes(top.read_text(), base_dir=tmp_path)
    assert {"vin", "vmid", "vout"} <= nodes  # vout comes from the included file


def test_extract_nodes_without_base_dir_skips_includes_safely():
    # No base_dir means includes can't be resolved; must not raise.
    nodes = extract_nodes("R1 vin vmid 1k\n.include sub.sp\n.end\n")
    assert nodes == {"0", "vin", "vmid"}


# --- validation (the bug) --------------------------------------------------


def test_typo_in_measurement_node_raises_instead_of_floating(tmp_path):
    net = _netlist(tmp_path, TWO_TRANSISTOR)
    with pytest.raises(UnknownNode) as exc:
        SimSession.from_netlist(net).ports(
            vcc=Port.supply("vcc", "0"),
            vout=Port.voltage_measurement("vaut", "0"),  # typo for vout
        )
    assert exc.value.node == "vaut"
    assert exc.value.suggestion == "vout"


def test_typo_in_supply_node_raises(tmp_path):
    net = _netlist(tmp_path, TWO_TRANSISTOR)
    with pytest.raises(UnknownNode):
        SimSession.from_netlist(net).ports(
            vcc=Port.supply("vccc", "0"),  # typo for vcc
        )


def test_typo_in_probe_node_raises(tmp_path):
    net = _netlist(tmp_path, TWO_TRANSISTOR)
    sim = SimSession.from_netlist(net).ports(vcc=Port.supply("vcc", "0"))
    with pytest.raises(UnknownNode):
        sim.probe("vaut")


def test_valid_nodes_do_not_raise(tmp_path):
    net = _netlist(tmp_path, TWO_TRANSISTOR)
    # Should construct cleanly; ground and real nodes both accepted.
    SimSession.from_netlist(net).ports(
        vin=Port.signal("vin", "0"),
        vcc=Port.supply("vcc", "0"),
        vout=Port.voltage_measurement("vout", "0"),
    )


def test_node_validation_is_case_insensitive(tmp_path):
    net = _netlist(tmp_path, TWO_TRANSISTOR)
    # ngspice node names are case-insensitive; VOUT must resolve to vout.
    SimSession.from_netlist(net).ports(
        vout=Port.voltage_measurement("VOUT", "0"),
    )


# --- ngspice diagnostic backstop ------------------------------------------


def test_ngspice_diagnostic_scan_warns_on_floating_node():
    log = "Doing analysis...\nWarning: node vfloat has no DC path to ground\nDone"
    with pytest.warns(RuntimeWarning, match="topology/convergence"):
        _warn_on_ngspice_diagnostics(log)


def test_ngspice_diagnostic_scan_is_quiet_on_clean_log(recwarn):
    _warn_on_ngspice_diagnostics("Doing analysis...\nDone\n")
    assert len(recwarn) == 0
