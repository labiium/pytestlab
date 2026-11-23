from __future__ import annotations

import json
import shlex
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from pytestlab.bench import Bench
from pytestlab.bench import SafeDeviceWrapper
from pytestlab.cli import app

_CAPABILITIES = {
    "native_read": True,
    "query_delay_ms": True,
    "resource_timing_policy": True,
    "write_termination": True,
}


def _bench_yaml(tmp_path: Path, *, database: bool = False) -> Path:
    marker = tmp_path / "automation-ran"
    config = {
        "bench_name": "CLI scoped session test",
        "simulate": False,
        "devices": {
            "prober": {
                "profile": "suss/PA200",
                "address": "GPIB0::1::INSTR",
                "simulate": False,
                "backend": {"type": "lamb", "url": "http://lamb.test:8000"},
            },
            # Must be omitted from a selected-prober inspection session.
            "unrelated": {
                "file": "missing-device-profile.yaml",
                "address": "GPIB0::99::INSTR",
                "simulate": False,
                "backend": {"type": "lamb", "url": "http://lamb.test:8000"},
            },
        },
        "sim_circuit": {"netlist": "missing-netlist.cir"},
        "automation": {
            "pre_experiment": [f"touch {shlex.quote(str(marker))}"],
            "post_experiment": [f"touch {shlex.quote(str(marker))}"],
        },
    }
    if database:
        config["experiment"] = {
            "title": "Must not start",
            "description": "inspection only",
            "database_path": str(tmp_path / "must-not-exist.sqlite"),
        }
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def _mock_lamb_http(monkeypatch, *, query_status: int = 200) -> list[tuple[str, dict]]:
    requests: list[tuple[str, dict]] = []
    original_init = httpx.Client.__init__

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        requests.append((request.url.path, payload))
        if request.url.host != "lamb.test" or request.url.port != 8000:
            return httpx.Response(502, text="unexpected test destination")
        if request.url.path == "/capabilities":
            return httpx.Response(200, json=_CAPABILITIES)
        if request.url.path == "/add":
            assert payload == {"model_name": "GPIB0::1::INSTR"}
            return httpx.Response(200, text=payload["model_name"])
        if request.url.path == "/instrument/timing":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/instrument/query":
            if query_status != 200:
                return httpx.Response(query_status, text="synthetic query failure")
            return httpx.Response(200, text="0 -10.000000 -20.000000 1000.000000 31")
        if request.url.path == "/instrument/close":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, text=f"unexpected endpoint {request.url.path}")

    def mock_init(self, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", mock_init)
    return requests


def test_actual_bench_open_capabilities_and_preflight_do_no_http_or_hooks(tmp_path, monkeypatch):
    requests = _mock_lamb_http(monkeypatch)
    bench_path = _bench_yaml(tmp_path, database=True)
    runner = CliRunner()

    capabilities = runner.invoke(
        app, ["prober", "capabilities", "prober", "--json", "--bench", str(bench_path)]
    )
    assert capabilities.exit_code == 0, capabilities.output
    assert "position" in json.loads(capabilities.stdout)["supports"]
    assert requests == []

    # PA200 lacks mapped physical readbacks, so full preflight correctly fails
    # while remaining static and disconnected.
    preflight = runner.invoke(app, ["prober", "preflight", "prober", "--bench", str(bench_path)])
    assert preflight.exit_code == 1
    assert "contact state readback is not declared" in preflight.output
    assert requests == []
    assert not (tmp_path / "automation-ran").exists()
    assert not (tmp_path / "must-not-exist.sqlite").exists()


def test_actual_bench_open_position_queries_selected_prober_and_closes(tmp_path, monkeypatch):
    requests = _mock_lamb_http(monkeypatch)
    bench_path = _bench_yaml(tmp_path)

    result = CliRunner().invoke(app, ["position", "prober", "--json", "--bench", str(bench_path)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"x": -0.01, "y": -0.02, "z": 1.0}
    queries = [payload for path, payload in requests if path == "/instrument/query"]
    assert len(queries) == 1
    assert queries[0]["command"] == "31"
    assert queries[0]["write_termination"] == ""
    assert queries[0]["read_termination"] == 10
    assert queries[0]["query_delay_ms"] == 100
    paths = [path for path, _ in requests]
    assert paths.count("/add") == 1
    assert paths.index("/add") < paths.index("/instrument/query")
    assert requests[-1] == (
        "/instrument/close",
        {"resource_string": "GPIB0::1::INSTR", "command": ""},
    )
    assert not (tmp_path / "automation-ran").exists()


def test_actual_bench_open_closes_handle_after_failed_query(tmp_path, monkeypatch):
    requests = _mock_lamb_http(monkeypatch, query_status=503)
    bench_path = _bench_yaml(tmp_path)

    result = CliRunner().invoke(app, ["position", "prober", "--json", "--bench", str(bench_path)])

    assert result.exit_code == 1
    assert "synthetic query failure" in result.output
    paths = [path for path, _ in requests]
    assert paths.count("/add") == 1
    assert paths.index("/add") < paths.index("/instrument/query")
    assert requests[-1] == (
        "/instrument/close",
        {"resource_string": "GPIB0::1::INSTR", "command": ""},
    )
    assert not (tmp_path / "automation-ran").exists()


def test_selected_session_ignores_unrelated_invalid_profile_and_provider(tmp_path, monkeypatch):
    requests = _mock_lamb_http(monkeypatch)
    bench_path = _bench_yaml(tmp_path)

    result = CliRunner().invoke(
        app, ["prober", "capabilities", "prober", "--bench", str(bench_path)]
    )

    assert result.exit_code == 0, result.output
    assert requests == []


def test_alias_scoped_bench_preserves_selected_resource_safety_wrapper(tmp_path, monkeypatch):
    requests = _mock_lamb_http(monkeypatch)
    path = tmp_path / "limited-bench.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Scoped safety wrapper test",
                "simulate": False,
                "devices": {
                    "smu": {
                        "profile": "hp/4142B",
                        "role": "source_measure",
                        "address": "GPIB0::23::INSTR",
                        "simulate": False,
                        "backend": {"type": "lamb", "url": "http://lamb.test:8000"},
                        "safety_limits": {"channels": {1: {"voltage": {"max": 1.0}}}},
                    }
                },
            }
        )
    )

    bench = Bench.open(path, aliases={"smu"}, start_experiment=False)
    try:
        resource = bench.devices["smu"]
        assert isinstance(resource, SafeDeviceWrapper)
        assert resource.safety_limits.channels[1].voltage == {"max": 1.0}
    finally:
        bench.close_all()
    assert requests == []


@pytest.mark.parametrize("identity_ok", [True, False])
def test_full_test_uses_selected_bench_psu_and_safety_limits_without_writes(
    tmp_path, monkeypatch, identity_ok
):
    commands = []
    closed = []
    tables = []
    marker = tmp_path / "automation-ran"

    class Backend:
        is_simulated = False

        def connect(self):
            pass

        def close(self):
            closed.append(True)

        def query(self, command, delay=None):
            commands.append(command)
            if command == "*IDN?":
                return (
                    f"Keysight Technologies,{'EDU36311A' if identity_ok else 'NGE102B'},MY123,1.0"
                )
            if command.startswith("OUTP:STAT? "):
                return "ON" if "(@2)" in command else "OFF"
            if command.startswith("MEAS:VOLT? "):
                return "0.5"
            if command.startswith("MEAS:CURR? "):
                return "-0.04"
            if command == "SYST:ERR?":
                return '+0,"No error"'
            raise AssertionError(f"Unexpected query: {command}")

        def write(self, command):
            pytest.fail(f"Unexpected write: {command}")

    def build(**kwargs):
        assert kwargs["address_override"] == "GPIB0::7::INSTR"
        return Backend()

    monkeypatch.setattr("pytestlab.devices.AutoDevice._build_backend", staticmethod(build))
    monkeypatch.setattr(
        "pytestlab.cli_typer._print_instrument_check_table", lambda **kw: tables.append(kw)
    )
    bench_path = tmp_path / "bench.yaml"
    bench_path.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Guarded full test",
                "reset_on_open": True,
                "devices": {
                    "psu": {
                        "profile": "keysight/EDU36311A",
                        "address": "GPIB0::7::INSTR",
                        "backend": {"type": "visa"},
                        "safety_limits": {
                            "channels": {1: {"voltage": {"max": 0.4}, "current": {"max_abs": 0.02}}}
                        },
                    },
                    "ignored": {"file": "missing.yaml"},
                },
                "automation": {
                    key: [f"touch {shlex.quote(str(marker))}"]
                    for key in ("pre_experiment", "post_experiment")
                },
            }
        )
    )
    result = CliRunner().invoke(
        app, ["instrument", "full-test", "psu", "--bench", str(bench_path), "--include-writes"]
    )

    assert result.exit_code == 0, result.output
    assert "Bench safety limits" in result.stdout and "0.4" in result.stdout
    assert commands[0] == "*IDN?"
    assert closed == [True] and not marker.exists()
    assert tables[0]["title"] == "Bench Instrument Full Test (psu)"
    rows = {(row["kind"], row["alias"]): row for row in tables[0]["rows"]}
    assert rows["mapping", "set_voltage"]["status"] == "ok"
    assert rows["operation", "set_voltage"]["status"] == "skip"
    assert rows["operation", "set_output"]["status"] == "skip"
    if identity_ok:
        assert tables[0]["failures"] == 1
        channel_one = rows["PSU readback", "channel 1"]
        assert channel_one["status"] == "fail"
        assert "exceeds the configured 0.4 V cap" in channel_one["detail"]
        assert "absolute current exceeds the configured 0.02 A cap" in channel_one["detail"]
        assert "output on" in rows["PSU readback", "channel 2"]["detail"]
    else:
        assert tables[0]["failures"] == 1
        assert rows["PSU readback", "identify"]["status"] == "fail"
        assert all(command in {"*IDN?", "SYST:ERR?"} for command in commands)


def test_bench_id_with_startup_reset_config_never_calls_reset(tmp_path, monkeypatch):
    bench_path = tmp_path / "bench.yaml"
    bench_path.write_text(
        yaml.safe_dump(
            {
                "bench_name": "ID inspection",
                "reset_on_open": True,
                "simulate": True,
                "devices": {"psu": {"profile": "keysight/EDU36311A"}},
            }
        )
    )

    def forbid_reset(self):
        pytest.fail("Read-only bench identification must not reset the bench")

    monkeypatch.setattr(Bench, "reset", forbid_reset)
    result = CliRunner().invoke(app, ["bench", "id", str(bench_path)])
    assert result.exit_code == 0, result.output
    assert "Simulated" in result.stdout
