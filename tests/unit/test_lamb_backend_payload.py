import os
import subprocess
import sys
from pathlib import Path

from pytestlab.instruments.backends.lamb import LambBackend


def test_lamb_backend_payload_includes_timeout_budget():
    backend = LambBackend(
        address="USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        timeout_ms=300_000,
    )

    assert backend._instrument_payload("*IDN?") == {
        "visa_string": "USB::2A8D::9007::MXR404A::MY62310227::INSTR",
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
    monkeypatch.setenv("TIM_LAMB_ORIGIN", "agent")

    assert LambBackend._request_headers()["X-TIM-Origin"] == "agent"


def test_lamb_backend_omits_empty_origin(monkeypatch):
    monkeypatch.delenv("TIM_LAMB_ORIGIN", raising=False)

    assert "X-TIM-Origin" not in LambBackend._request_headers()


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
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
