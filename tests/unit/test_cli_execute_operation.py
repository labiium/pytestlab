from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from pytestlab.cli import _semantic_operation_rows
from pytestlab.cli import app
from pytestlab.devices.base import _BackendFactory
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments.operation_contract import OperationDescriptor

runner = CliRunner()


class _FakeOperationDevice:
    _backend_source = _BackendFactory(lambda: None)

    def __init__(self) -> None:
        self.calls: list[tuple[str, object, dict[str, object]]] = []
        self.config = SimpleNamespace(
            operation_options=SimpleNamespace(operation=lambda operation_id: object())
        )

    def operation_descriptors(self):
        return (
            OperationDescriptor(
                "read_status",
                public_method="execute_profile_operation",
                safety_class="read",
            ),
        )

    def describe_operation(self, operation_id):
        return {
            "operation_id": operation_id,
            "method": "execute_profile_operation",
            "support": {"supported": True},
            "parameters": {"channel": {"required": False, "kind": "integer"}},
            "execution": {"requires_context": [], "safety_class": "read"},
        }

    def _resolve_operation_arguments(self, operation_id, params):
        assert operation_id == "read_status"
        assert params == {"channel": 2}

    def execute_profile_operation(self, operation_id, *, safety_context=None, **params):
        self.calls.append((operation_id, safety_context, params))
        return "ready"

    def close(self):
        raise AssertionError("lazy backend should not be closed")


def test_execute_operation_uses_declared_generic_operation_and_json(monkeypatch):
    device = _FakeOperationDevice()
    monkeypatch.setattr("pytestlab.cli_typer._operation_instrument", lambda *args, **kwargs: device)

    result = runner.invoke(
        app,
        [
            "instrument",
            "execute-operation",
            "profile.yaml",
            "read_status",
            "--params",
            '{"channel": 2}',
            "--safety-context",
            '{"operator_confirmed": true}',
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "operation_id": "read_status",
        "result": "ready",
    }
    assert device.calls == [("read_status", {"operator_confirmed": True}, {"channel": 2})]


def test_execute_operation_rejects_non_object_json_before_constructing(monkeypatch):
    called = False

    def fail(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("instrument construction must not run")

    monkeypatch.setattr("pytestlab.cli_typer._operation_instrument", fail)
    result = runner.invoke(
        app,
        [
            "instrument",
            "execute-operation",
            "profile.yaml",
            "read_status",
            "--params",
            "[]",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert called is False


def test_execute_operation_missing_safety_context_does_not_touch_backend(monkeypatch):
    device = _FakeOperationDevice()

    def guarded(operation_id, *, safety_context=None, **params):
        raise InstrumentConfigurationError(
            "Fake", "Profile operation requires safety context: closed"
        )

    device.execute_profile_operation = guarded
    monkeypatch.setattr("pytestlab.cli_typer._operation_instrument", lambda *args, **kwargs: device)

    result = runner.invoke(
        app,
        [
            "instrument",
            "execute-operation",
            "profile.yaml",
            "read_status",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["operation_id"] == "read_status"


def test_full_test_passes_operation_id_and_skips_dynamic_state_changes():
    calls = []

    class Device:
        def operation_descriptors(self):
            return (
                OperationDescriptor(
                    "read_status",
                    public_method="execute_profile_operation",
                    safety_class="read",
                ),
                OperationDescriptor(
                    "set_mode",
                    public_method="execute_profile_operation",
                    safety_class="state-changing",
                ),
            )

        def describe_operation(self, operation_id):
            return {
                "support": {"supported": True},
                "parameters": {},
                "execution": {"requires_context": [], "safety_class": "read"},
            }

        def execute_profile_operation(self, operation_id, *, safety_context=None, **params):
            calls.append((operation_id, safety_context, params))

    rows, failures, warnings, skipped = _semantic_operation_rows(Device(), include_writes=True)

    assert failures == warnings == 0
    assert skipped == 1
    assert calls == [("read_status", {}, {})]
    assert next(row for row in rows if row["alias"] == "set_mode")["status"] == "skip"
