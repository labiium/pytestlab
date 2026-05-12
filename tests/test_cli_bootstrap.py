from __future__ import annotations

from pathlib import Path

import pytest

import pytestlab.cli as cli


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str], capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(cli.sys, "argv", argv)
    result = cli.main()
    captured = capsys.readouterr()
    return result, captured


def test_entrypoint_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    result, captured = _run_main(monkeypatch, ["ptl", "--help"], capsys)
    assert result == 0
    assert "Usage: ptl" in captured.out
    assert "Commands:" in captured.out


def test_legacy_entrypoint_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
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


def test_entrypoint_profile_list(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    result, captured = _run_main(monkeypatch, ["ptl", "profile", "list"], capsys)
    assert result == 0
    assert "Available Profiles" in captured.out
    assert "keysight/EDU34450A" in captured.out


def test_entrypoint_profile_show(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
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


def test_entrypoint_profile_schema(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    result, captured = _run_main(
        monkeypatch,
        ["ptl", "profile", "schema", "oscilloscope"],
        capsys,
    )
    assert result == 0
    assert "Schema for oscilloscope:" in captured.out
    assert '"$defs"' in captured.out


def test_entrypoint_list_profiles(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    result, captured = _run_main(monkeypatch, ["ptl", "list", "profiles"], capsys)
    assert result == 0
    assert "Available instrument profiles:" in captured.out
    assert "keysight/EDU34450A" in captured.out


def test_entrypoint_bench_validate(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
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


def test_cli_module_attribute_bridge():
    assert cli.app is not None
    assert cli.replay_record is not None
    assert cli.replay_run is not None
