"""`ptl sim doctor` preflight: ready when ngspice is present, fails closed when not."""
from __future__ import annotations

import shutil

from typer.testing import CliRunner

from pytestlab.cli import app

runner = CliRunner()


def test_sim_doctor_fails_when_ngspice_missing(monkeypatch):
    monkeypatch.setattr("pytestlab.cli.shutil.which", lambda cmd: None)
    result = runner.invoke(app, ["sim", "doctor"])
    assert result.exit_code == 1


def test_sim_doctor_passes_when_ngspice_present(monkeypatch):
    # Point the lookup at a harmless real binary so the version probe succeeds.
    harmless = shutil.which("true") or "/bin/true"
    monkeypatch.setattr("pytestlab.cli.shutil.which", lambda cmd: harmless)
    result = runner.invoke(app, ["sim", "doctor"])
    assert result.exit_code == 0
