"""`ptl sim install-ngspice`: provision ngspice without ever assuming sudo.

User-space managers (conda/brew/...) may be run with consent; root-requiring
managers (apt-get/dnf/...) are only printed for the user to run themselves.
PyTestLab never invokes sudo or assumes it exists.
"""
from __future__ import annotations

from typer.testing import CliRunner

from pytestlab.cli import app

runner = CliRunner()


def _which_factory(present: set[str]):
    def _which(name: str):
        return f"/usr/bin/{name}" if name in present else None

    return _which


def test_already_installed_is_a_noop(monkeypatch):
    # resolve_ngspice is imported inside cli.py from spice.py, so patch at source.
    monkeypatch.setattr("pytestlab.sim.circuit.spice.resolve_ngspice", lambda cmd: "/usr/bin/ngspice")
    result = runner.invoke(app, ["sim", "install-ngspice"])
    assert result.exit_code == 0


def test_no_package_manager_fails_closed(monkeypatch):
    monkeypatch.setattr("pytestlab.sim.circuit.spice.resolve_ngspice", lambda cmd: None)
    monkeypatch.setattr("pytestlab.sim.circuit._mirror.mirror_asset", lambda: None)
    monkeypatch.setattr("pytestlab.cli.shutil.which", _which_factory(set()))
    result = runner.invoke(app, ["sim", "install-ngspice"])
    assert result.exit_code == 1


def test_root_manager_as_nonroot_is_print_only_even_with_yes(monkeypatch):
    # apt-get needs root; as a non-root user it must NOT be executed, even with
    # --yes, and we must never shell out to sudo.
    monkeypatch.setattr("pytestlab.sim.circuit.spice.resolve_ngspice", lambda cmd: None)
    monkeypatch.setattr("pytestlab.sim.circuit._mirror.mirror_asset", lambda: None)
    monkeypatch.setattr("pytestlab.cli.shutil.which", _which_factory({"apt-get"}))
    monkeypatch.setattr("pytestlab.cli.os.geteuid", lambda: 1000, raising=False)
    ran = {"called": False}
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: ran.__setitem__("called", True)
    )

    result = runner.invoke(app, ["sim", "install-ngspice", "--yes"])
    assert result.exit_code == 1
    assert ran["called"] is False


def test_user_space_manager_runs_with_yes(monkeypatch):
    # brew is sudo-free; with --yes it runs and ngspice then appears.
    monkeypatch.setattr("pytestlab.sim.circuit.spice.resolve_ngspice", lambda cmd: None)
    monkeypatch.setattr("pytestlab.sim.circuit._mirror.mirror_asset", lambda: None)
    state = {"installed": False}

    def _which(name: str):
        if name == "ngspice":
            return "/usr/bin/ngspice" if state["installed"] else None
        return "/opt/brew/bin/brew" if name == "brew" else None

    monkeypatch.setattr("pytestlab.cli.shutil.which", _which)
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: state.__setitem__("installed", True)
    )

    result = runner.invoke(app, ["sim", "install-ngspice", "--yes"])
    assert result.exit_code == 0
    assert state["installed"] is True


def test_root_user_may_run_system_manager(monkeypatch):
    # As root, a system manager (apt-get) may be run directly -- still no sudo.
    monkeypatch.setattr("pytestlab.sim.circuit.spice.resolve_ngspice", lambda cmd: None)
    monkeypatch.setattr("pytestlab.sim.circuit._mirror.mirror_asset", lambda: None)
    state = {"installed": False}

    def _which(name: str):
        if name == "ngspice":
            return "/usr/bin/ngspice" if state["installed"] else None
        return "/usr/bin/apt-get" if name == "apt-get" else None

    captured = {"argv": None}

    def _run(argv, **kwargs):
        captured["argv"] = argv
        state["installed"] = True

    monkeypatch.setattr("pytestlab.cli.shutil.which", _which)
    monkeypatch.setattr("pytestlab.cli.os.geteuid", lambda: 0, raising=False)
    monkeypatch.setattr("subprocess.run", _run)

    result = runner.invoke(app, ["sim", "install-ngspice", "--yes"])
    assert result.exit_code == 0
    assert captured["argv"][0] != "sudo"  # never escalates
