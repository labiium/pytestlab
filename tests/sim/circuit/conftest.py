from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def netlist_path(tmp_path: Path) -> Path:
    path = tmp_path / "circuit.sp"
    # Defines the supply/load rails (vdd, vload, load) that bench wirings attach
    # instruments to, so node-name validation resolves them as real nodes rather
    # than rejecting them as floating typos.
    path.write_text(
        "V1 vin 0 DC 1\n"
        "R1 vin vout 1000\n"
        "C1 vout 0 1u\n"
        "Rvdd vdd 0 1k\n"
        "Rvload vload 0 1k\n"
        "Rload load 0 1k\n"
        ".end\n"
    )
    return path
