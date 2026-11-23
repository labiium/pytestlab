from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pytestlab import bench as bench_module
from pytestlab.bench import Bench
from pytestlab.cli_typer import app
from pytestlab.devices import factory
from pytestlab.devices import providers
from pytestlab.devices import registry


def _forbid(*_args, **_kwargs):
    pytest.fail("live or extension factory/provider/hook was reached")


@pytest.fixture
def offline_tripwires(monkeypatch):
    monkeypatch.setattr(bench_module, "prepare_backend_resources", _forbid)
    monkeypatch.setattr(bench_module.Bench, "_run_automation_hook", _forbid)
    monkeypatch.setattr(registry, "load_entry_points", _forbid)
    monkeypatch.setitem(registry._backends, "sim", _forbid)
    monkeypatch.setitem(registry._device_drivers, "multimeter", _forbid)
    monkeypatch.setitem(providers._providers, "lamb", _forbid)
    monkeypatch.setattr(factory, "get_backend_factory", _forbid)
    monkeypatch.setattr(factory.AutoDevice, "get_config_from_cdn", _forbid)


def _inputs(tmp_path, *, body=None):
    config_dir = tmp_path / "bench_inputs"
    config_dir.mkdir()
    source = Path(__file__).resolve().parents[1] / "pytestlab/profiles/keysight/EDU34450A.yaml"
    raw = yaml.safe_load(source.read_text())
    raw["backend"] = {"type": "lamb", "url": "http://fixture.invalid:8080"}
    (config_dir / "meter.yaml").write_text(yaml.safe_dump(raw))
    descriptor = config_dir / "bench.yaml"
    config = {
        "name": "Fixture bench",
        "simulate": False,
        "instruments": {
            "legacy": {
                "file": "meter.yaml",
                "simulate": False,
                "address": "USB::BENCH-FIXTURE",
                "backend": {"type": "lamb", "url": "http://fixture.invalid:8080"},
            }
        },
        "devices": {
            "device": {
                "profile": "keysight/EDU34450A",
                "simulate": False,
                "backend": {"type": "visa"},
            }
        },
    }
    if body:
        body(config, config_dir)
    descriptor.write_text(yaml.safe_dump(config))
    script = tmp_path / "measurement.py"
    script.write_text(
        "def main(bench):\n"
        "    assert bench.legacy.is_simulated\n"
        "    assert bench.device.is_simulated\n"
        "    return {'ran': True}\n"
    )
    return descriptor, script


def test_run_forces_both_legacy_and_current_entries(tmp_path, monkeypatch, offline_tripwires):
    descriptor, script = _inputs(tmp_path)
    cwd = tmp_path / "independent_working_dir"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    output = tmp_path / "result.yaml"
    result = CliRunner().invoke(
        app, ["run", str(script), "--bench", str(descriptor), "--simulate", "--output", str(output)]
    )
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert yaml.safe_load(output.read_text()) == {"ran": True}
    assert yaml.safe_load(descriptor.read_text())["instruments"]["legacy"]["simulate"] is False
    assert sorted(p.name for p in descriptor.parent.iterdir()) == ["bench.yaml", "meter.yaml"]
    assert list(cwd.iterdir()) == []


@pytest.mark.parametrize(
    "unsafe",
    [
        "hook",
        "custom_entry_backend",
        "custom_profile_backend",
        "driver",
        "model",
        "unknown_profile",
        "missing_simulation",
    ],
)
def test_run_rejects_unsupported_inputs_before_backend_or_script(
    tmp_path, monkeypatch, unsafe, offline_tripwires
):
    def modify(config, root):
        if unsafe == "hook":
            config["automation"] = {"pre_experiment": ["shell: should-not-run"]}
        elif unsafe == "custom_entry_backend":
            config["devices"]["device"]["backend"] = {
                "type": "custom",
                "import_path": "outside:device",
            }
        elif unsafe == "unknown_profile":
            config["devices"]["device"]["profile"] = "fixture/profile-does-not-exist"
        else:
            path = root / "meter.yaml"
            data = yaml.safe_load(path.read_text())
            if unsafe == "custom_profile_backend":
                data["backend"] = {"type": "circuit_sim", "import_path": "outside:backend"}
            elif unsafe in {"driver", "model"}:
                data["driver" if unsafe == "driver" else "config_model"] = "outside:module"
            else:
                data.pop("simulation")
            path.write_text(yaml.safe_dump(data))

    descriptor, script = _inputs(tmp_path, body=modify)
    script.write_text("raise RuntimeError('script import must not happen')\n")
    monkeypatch.setattr(Bench, "_initialize_devices", _forbid)
    result = CliRunner().invoke(app, ["run", str(script), "--bench", str(descriptor), "--simulate"])
    assert result.exit_code == 1
    assert "script import must not happen" not in result.output
    assert "Cannot simulate bench entry" in result.output or "automation hooks" in result.output


def test_bench_sim_file_round_trips_with_distinct_destination(tmp_path, offline_tripwires):
    descriptor, _ = _inputs(tmp_path)
    output = tmp_path / "generated.yaml"
    result = CliRunner().invoke(
        app, ["bench", "sim", str(descriptor), "--output-path", str(output)]
    )
    assert result.exit_code == 0, result.output + repr(result.exception)
    data = yaml.safe_load(output.read_text())
    assert data["simulate"] and data["simulation_only"]
    assert data["instruments"]["legacy"]["file"] == str(descriptor.parent / "meter.yaml")
    entries = data["instruments"] | data["devices"]
    for entry in entries.values():
        assert entry["simulate"] is True
        assert entry["address"] == "sim"
        assert entry["backend"] == {"type": "sim"}
    bench = Bench.open(output)
    try:
        assert bench.device.is_simulated and bench.legacy.is_simulated
    finally:
        bench.close_all()


def test_export_retains_explicit_relative_circuit_sim(tmp_path, offline_tripwires):
    pytest.importorskip("pytestlab.sim.circuit")

    def with_circuit(config, root):
        (root / "fixture.sp").write_text("RLOAD vload 0 100\n.end\n")
        config["instruments"]["psu"] = {
            "profile": "keysight/EDU36311A",
            "simulate": False,
            "backend": {"type": "circuit_sim"},
        }
        config["sim_circuit"] = {
            "netlist": "fixture.sp",
            "seed": 19,
            "wiring": {"psu.CH1+": "vload", "psu.CH1-": "0"},
        }

    descriptor, _ = _inputs(tmp_path, body=with_circuit)
    output = tmp_path / "circuit-generated.yaml"
    result = CliRunner().invoke(
        app, ["bench", "sim", str(descriptor), "--output-path", str(output)]
    )
    assert result.exit_code == 0, result.output + repr(result.exception)
    data = yaml.safe_load(output.read_text())
    assert data["instruments"]["psu"]["backend"] == {"type": "circuit_sim"}
    assert data["sim_circuit"]["netlist"] == str(descriptor.parent / "fixture.sp")
    bench = Bench.open(output)
    try:
        assert bench.psu.is_simulated
        assert bench._sim_session is not None
    finally:
        bench.close_all()


def test_bench_sim_stdout_is_raw_yaml_and_failures_are_stderr(tmp_path, offline_tripwires):
    descriptor, _ = _inputs(tmp_path)
    result = CliRunner().invoke(app, ["bench", "sim", str(descriptor)])
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert result.stderr == ""
    assert "\x1b[" not in result.stdout
    assert yaml.safe_load(result.stdout)["simulation_only"] is True
    moved = tmp_path / "redirected-output.yaml"
    moved.write_text(result.stdout)
    bench = Bench.open(moved)
    try:
        assert bench.legacy.is_simulated
    finally:
        bench.close_all()

    failure = CliRunner().invoke(app, ["bench", "sim", str(tmp_path / "not-found.yaml")])
    assert failure.exit_code == 1
    assert failure.stdout == ""
    assert "Bench configuration file not found" in failure.stderr
