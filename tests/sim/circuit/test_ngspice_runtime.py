"""The ngspice binary is a system dependency, not a pip dependency.

A missing binary must fail with actionable install guidance (system package
managers + the Docker image), since `pip install pytestlab[circuit]` cannot
provide ngspice itself.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from pytestlab.sim.circuit.spice import NgspiceNotFound
from pytestlab.sim.circuit.spice import NgspiceRunError
from pytestlab.sim.circuit.spice import _ngspice_not_found
from pytestlab.sim.circuit.spice import _run_ngspice
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


def test_ngspice_available_reports_missing_binary(tmp_path, monkeypatch):
    # Bogus command name, and an empty HOME so no managed install is discovered.
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ngspice_available("ngspice-definitely-not-installed-xyz") is False


def test_explicit_resource_limit_setup_failure_is_observable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    def fake_run(*args, preexec_fn=None, **kwargs):
        assert preexec_fn is not None
        preexec_fn()
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    def fail_setrlimit(kind, limits):
        raise OSError("rlimit refused")

    fake_resource = SimpleNamespace(
        RLIMIT_AS=1,
        RLIMIT_CPU=2,
        setrlimit=fail_setrlimit,
    )
    monkeypatch.setitem(sys.modules, "resource", fake_resource)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(NgspiceRunError, match="resource limit.*rlimit refused"):
        _run_ngspice(
            ["R1 in 0 1k", ".end"],
            tmp_path,
            "ngspice",
            tmp_path,
            max_memory_mb=64,
        )
