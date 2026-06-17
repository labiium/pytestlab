"""The ngspice binary is a system dependency, not a pip dependency.

A missing binary must fail with actionable install guidance (system package
managers + the Docker image), since `pip install pytestlab[circuit]` cannot
provide ngspice itself.
"""
from __future__ import annotations

from pytestlab.sim.circuit.spice import NgspiceNotFound
from pytestlab.sim.circuit.spice import _ngspice_not_found
from pytestlab.sim.circuit.spice import ngspice_available


def test_ngspice_not_found_message_lists_real_install_paths():
    err = _ngspice_not_found("ngspice")
    assert isinstance(err, NgspiceNotFound)
    text = str(err)
    # Names the binary, that the extra cannot supply it, and concrete options.
    assert "ngspice command not found" in text
    assert "pytestlab[circuit]" in text
    for hint in ("apt-get install ngspice", "brew install ngspice", "conda", "docker"):
        assert hint in text.lower()


def test_ngspice_available_reports_missing_binary():
    # A clearly bogus command name is never on PATH.
    assert ngspice_available("ngspice-definitely-not-installed-xyz") is False
