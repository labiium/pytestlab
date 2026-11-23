import os
import subprocess
import sys
from pathlib import Path

import pytest

from pytestlab.instruments.backends.lamb import LambBackend


def test_lamb_backend_payload_includes_timeout_budget():
    backend = LambBackend(
        address="USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        timeout_ms=300_000,
    )

    assert backend._instrument_payload("*IDN?") == {
        "resource_string": "USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        "command": "*IDN?",
        "timeout_ms": 300_000,
    }


def test_lamb_backend_set_timeout_updates_payload_budget():
    backend = LambBackend(address="USB::2A8D::9007::MXR404A::MY62310227::INSTR")

    backend.set_timeout(12_345)

    assert backend._instrument_payload(":SYSTem:ERRor?")["timeout_ms"] == 12_345


def test_lamb_backend_default_payload_budget_is_30_seconds():
    backend = LambBackend(address="USB::2A8D::9007::MXR404A::MY62310227::INSTR")

    assert backend._instrument_payload("*IDN?")["timeout_ms"] == 30_000


def test_lamb_backend_none_timeout_uses_default_30_seconds():
    backend = LambBackend(
        address="USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        timeout_ms=None,
    )

    assert backend._instrument_payload("*IDN?")["timeout_ms"] == 30_000


def test_lamb_backend_http_timeout_exceeds_payload_budget():
    backend = LambBackend(
        address="USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        timeout_ms=30_000,
    )

    assert backend._instrument_payload("*IDN?")["timeout_ms"] == 30_000
    assert backend._http_timeout_sec() == 35.0
    assert backend._http_timeout_sec() > backend._instrument_payload("*IDN?")["timeout_ms"] / 1000


def test_lamb_backend_labels_requests_with_configured_origin(monkeypatch):
    monkeypatch.setenv("PYTESTLAB_TIM_ATTRIBUTION", "1")
    monkeypatch.setenv("TIM_LAMB_ORIGIN", "agent")

    assert LambBackend._request_headers()["X-TIM-Origin"] == "agent"


def test_lamb_backend_omits_empty_origin(monkeypatch):
    monkeypatch.setenv("PYTESTLAB_TIM_ATTRIBUTION", "1")
    monkeypatch.delenv("TIM_LAMB_ORIGIN", raising=False)

    assert LambBackend._request_headers()["X-TIM-Origin"] == "controller"


def test_lamb_backend_forwards_production_operation_token(monkeypatch):
    monkeypatch.setenv("PYTESTLAB_TIM_ATTRIBUTION", "1")
    monkeypatch.setenv("TIM_LAMB_OPERATION_TOKEN", "operation-secret")

    assert LambBackend._request_headers()["X-TIM-Operation-Token"] == "operation-secret"


def test_lamb_backend_forwards_harness_episode_identity(monkeypatch):
    monkeypatch.delenv("PYTESTLAB_TIM_ATTRIBUTION", raising=False)
    monkeypatch.setenv("TIM_LAMB_RUNTIME_MANIFEST", "/artifacts/results/test/runtime/lamb/run.json")
    monkeypatch.setenv("TIM_HARNESS_RUN_ID", "run-123")
    monkeypatch.setenv("TIM_HARNESS_BLOCK_ID", "block-7")
    monkeypatch.setenv("TIM_HARNESS_ARM", "pytestlab")
    monkeypatch.setenv("TIM_HARNESS_TASK_ID", "psu_safe_setup")
    monkeypatch.setenv("TIM_HARNESS_VARIANT_ID", "logic_bias")

    headers = LambBackend._request_headers()

    assert headers["X-TIM-Harness-Run-Id"] == "run-123"
    assert headers["X-TIM-Block-Id"] == "block-7"
    assert headers["X-TIM-Arm"] == "pytestlab"
    assert headers["X-TIM-Task-Id"] == "psu_safe_setup"
    assert headers["X-TIM-Variant-Id"] == "logic_bias"


def test_lamb_backend_import_does_not_require_pyvisa():
    project_root = Path(__file__).resolve().parents[2]
    code = """
import builtins
original_import = builtins.__import__
def without_pyvisa(name, *args, **kwargs):
    if name == "pyvisa" or name.startswith("pyvisa."):
        raise ModuleNotFoundError("blocked optional pyvisa dependency")
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_pyvisa
from pytestlab.instruments.backends.lamb import LambBackend
assert LambBackend._request_headers()["X-TIM-Origin"] == "agent"
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env={
            **os.environ,
            "PYTHONPATH": str(project_root),
            "TIM_LAMB_ORIGIN": "agent",
            "PYTESTLAB_TIM_ATTRIBUTION": "1",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_generic_failure_never_replays_resource_operation(monkeypatch):
    import httpx

    backend = LambBackend(address="USB::MODEL::SERIAL::INSTR")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, text="instrument failed after execution")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(backend, "_get_client", lambda: client)
    result = backend._post_request(
        "http://lamb.test/instrument/write",
        json={"resource_string": backend.instrument_address, "command": "OUTPUT OFF"},
    )
    assert result.status_code == 500
    assert len(calls) == 1
    client.close()


@pytest.mark.parametrize("enabled", [None, "0", "false"])
def test_lamb_backend_ordinary_request_omits_all_tim_headers_and_does_not_walk_stack(
    monkeypatch, enabled
):
    if enabled is None:
        monkeypatch.delenv("PYTESTLAB_TIM_ATTRIBUTION", raising=False)
    else:
        monkeypatch.setenv("PYTESTLAB_TIM_ATTRIBUTION", enabled)
    monkeypatch.delenv("TIM_LAMB_RUNTIME_MANIFEST", raising=False)
    monkeypatch.setenv("TIM_LAMB_ORIGIN", "agent")
    monkeypatch.setenv("TIM_LAMB_OPERATION_TOKEN", "stale-test-token")
    monkeypatch.setenv("TIM_HARNESS_TASK_ID", "stray-env")
    monkeypatch.setattr(
        "pytestlab.instruments.backends.lamb.describe_emitter",
        lambda: pytest.fail("ordinary requests must never inspect Python frames"),
    )

    backend = LambBackend(address="USB::TEST")

    def post(url, **kwargs):
        assert url.endswith("/instrument/query")
        assert kwargs["headers"] == {"Accept": "application/json", "Accept-Charset": "utf-8"}
        return type(
            "Response",
            (),
            {"status_code": 200, "content": b"ok", "raise_for_status": lambda self: None},
        )()

    monkeypatch.setattr(backend, "_post_request", post)
    assert backend.query("READ?") == "ok"


@pytest.mark.parametrize("override", [None, "0"])
def test_deployed_tim_launcher_context_works_with_optional_ids(monkeypatch, override):
    if override is None:
        monkeypatch.delenv("PYTESTLAB_TIM_ATTRIBUTION", raising=False)
    else:
        monkeypatch.setenv("PYTESTLAB_TIM_ATTRIBUTION", override)
    for key, value in {
        "TIM_LAMB_RUNTIME_MANIFEST": "/artifacts/results/test/runtime/lamb/episode.json",
        "TIM_HARNESS_ARM": "pytestlab",
        "TIM_HARNESS_TASK_ID": "example_task",
        "TIM_HARNESS_VARIANT_ID": "example_variant",
        "TIM_HARNESS_RUN_ID": "",
        "TIM_HARNESS_BLOCK_ID": "",
        "TIM_LAMB_OPERATION_TOKEN": "",
    }.items():
        monkeypatch.setenv(key, value)
    headers = LambBackend._request_headers()
    if override is None:
        assert headers["X-TIM-Arm"] == "pytestlab"
        assert headers["X-TIM-Task-Id"] == "example_task"
        assert headers["X-TIM-Variant-Id"] == "example_variant"
        assert "X-TIM-Emitter" in headers
        assert "X-TIM-Harness-Run-Id" not in headers
    else:
        assert not any(name.startswith("X-TIM-") for name in headers)
