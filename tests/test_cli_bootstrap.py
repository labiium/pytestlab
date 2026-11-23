from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text

import pytestlab.cli as cli


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str], capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(cli.sys, "argv", argv)
    try:
        result = cli.main()
    except SystemExit as exc:
        result = exc.code
    captured = capsys.readouterr()
    return result, captured


def test_entrypoint_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    result, captured = _run_main(monkeypatch, ["ptl", "--help"], capsys)
    assert result == 0
    assert "Usage: ptl" in captured.out
    assert "Commands:" in captured.out


def test_legacy_entrypoint_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    result, captured = _run_main(monkeypatch, ["pytestlab", "--help"], capsys)
    assert result == 0
    assert "Usage: pytestlab" in captured.out


def test_console_script_aliases_are_registered():
    import tomllib

    with Path("pyproject.toml").open("rb") as handle:
        scripts = tomllib.load(handle)["project"]["scripts"]

    assert scripts["ptl"] == "pytestlab.cli:main"
    assert scripts["pytestlab"] == "pytestlab.cli:main"


def test_entrypoint_version(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    result, captured = _run_main(monkeypatch, ["ptl", "--version"], capsys)
    assert result == 0
    assert "PyTestLab version" in captured.out


def test_entrypoint_profile_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    result, captured = _run_main(monkeypatch, ["ptl", "profile", "list"], capsys)
    assert result == 0
    assert "Available Profiles" in captured.out
    assert "keysight/EDU34450A" in captured.out


def test_entrypoint_profile_show(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    result, captured = _run_main(
        monkeypatch,
        ["ptl", "profile", "show", "keysight/EDU34450A"],
        capsys,
    )
    assert result == 0
    assert "Profile: keysight/EDU34450A" in captured.out
    assert "device_type: multimeter" in captured.out


def test_entrypoint_profile_show_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    profile_path = Path("pytestlab/profiles/keysight/EDU34450A.yaml")
    result, captured = _run_main(
        monkeypatch,
        ["ptl", "profile", "show", str(profile_path)],
        capsys,
    )
    assert result == 0
    assert f"Profile: {profile_path}" in captured.out
    assert "manufacturer: keysight" in captured.out


def test_entrypoint_profile_schema(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    result, captured = _run_main(
        monkeypatch,
        ["ptl", "profile", "schema", "oscilloscope"],
        capsys,
    )
    assert result == 0
    assert "Schema for oscilloscope:" in captured.out
    assert '"$defs"' in captured.out


def test_entrypoint_list_profiles(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    result, captured = _run_main(monkeypatch, ["ptl", "list", "profiles"], capsys)
    assert result == 0
    assert "Available instrument profiles:" in captured.out
    assert "keysight/EDU34450A" in captured.out


def test_entrypoint_bench_validate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    result, captured = _run_main(
        monkeypatch,
        ["ptl", "bench", "validate", "examples/bench.yaml"],
        capsys,
    )
    assert result == 0
    assert "Bench configuration 'examples/bench.yaml' is valid." in captured.out
    assert "Profile 'keysight/EDU34450A'" in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        ["ptl", "list", "benches"],
        ["ptl", "instrument", "idn", "keysight/EDU34450A", "--simulate"],
        ["ptl", "replay", "--help"],
        ["ptl", "sim-profile", "diff", "keysight/EDU34450A"],
        ["ptl", "profile", "list", "--help"],
        ["ptl", "profile", "list", "--profile-dir", "/tmp"],
        ["ptl", "profile", "show", "--help"],
        ["ptl", "profile", "schema", "--help"],
        ["ptl", "profile", "schema", "oscilloscope", "--output", "/tmp/schema.json"],
        ["ptl", "bench", "validate", "--help"],
    ],
)
def test_entrypoint_fallback_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
):
    called: list[list[str]] = []

    def fake_main():
        called.append(list(cli.sys.argv))
        print("fallback-called")
        return 0

    import pytestlab.cli_typer as cli_typer

    monkeypatch.setattr(cli_typer, "main", fake_main)
    result, captured = _run_main(monkeypatch, argv, capsys)

    assert result == 0
    assert called == [argv]
    assert "fallback-called" in captured.out


@pytest.mark.parametrize(
    ("route", "arguments", "flag"),
    [
        (
            ("replay", "record"),
            ["read.py", "--bench", "bench.yaml", "--output", "out.yaml"],
            "--bench",
        ),
        (("replay", "run"), ["read.py", "--session", "out.yaml"], "--session"),
        (
            ("sim-profile", "record"),
            ["keysight/34470A", "--address", "GPIB0::1::INSTR"],
            "--simulate",
        ),
    ],
)
@pytest.mark.parametrize("full_command", [False, True])
def test_record_and_replay_entrypoint_help_never_opens_devices(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    route: tuple[str, str],
    arguments: list[str],
    flag: str,
    full_command: bool,
):
    def forbidden(*args, **kwargs):
        pytest.fail("help must not open a bench or construct a device")

    monkeypatch.setattr("pytestlab.bench.Bench.open", forbidden)
    monkeypatch.setattr("pytestlab.devices.AutoDevice.from_config", forbidden)
    argv = ["ptl", *route, *(arguments if full_command else []), "--help"]
    result, captured = _run_main(monkeypatch, argv, capsys)
    assert result == 0
    help_text = Text.from_ansi(captured.out).plain
    assert "Usage:" in help_text
    assert f"{' '.join(route)} [OPTIONS]" in help_text
    assert flag in help_text


def test_cli_module_attribute_bridge():
    assert cli.app is not None
    assert cli.replay_record is not None
    assert cli.replay_run is not None
