"""Offline tests of documented scope self-test protocols and dispatch."""

import json

import pytest
from typer.testing import CliRunner

from pytestlab.cli_typer import _profile_scpi_command_rows
from pytestlab.cli_typer import _semantic_operation_rows
from pytestlab.cli_typer import app
from pytestlab.config.loader import load_device_profile
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments.instrument import Instrument
from pytestlab.instruments.Oscilloscope import Oscilloscope


class ScopeBackend:
    is_simulated = False

    def __init__(self):
        self.result = "+0"
        self.commands = []
        self.connected = 0
        self.timeout = 2000

    def connect(self):
        self.connected += 1

    def query(self, command, delay=None):
        self.commands.append(("query", command, self.timeout))
        if command == "*TST?":
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result
        raise AssertionError(f"Unexpected query: {command}")

    def write(self, command):
        self.commands.append(("write", command))
        raise AssertionError(f"Unexpected write: {command}")

    def close(self):
        pass

    def get_timeout(self):
        return self.timeout

    def set_timeout(self, timeout_ms):
        self.timeout = timeout_ms


def _scope(model="DSOX1204G"):
    backend = ScopeBackend()
    return Oscilloscope(load_device_profile(f"keysight/{model}"), backend=backend), backend


@pytest.mark.parametrize(
    "model", ["DSOX1202G", "DSOX1204G", "DSOX3054G", "MSOX2024A", "HD304MSO", "MXR404A"]
)
def test_bundled_scope_maps_native_self_test_without_changing_the_public_api(model):
    scope, backend = _scope(model)
    assert scope.supports_operation("run_self_test")
    assert type(scope).run_self_test is Instrument.run_self_test
    assert scope.run_self_test(full_test=False) == "Passed"
    assert backend.commands == [("query", "*TST?", 240_000)]
    assert backend.timeout == 2000


def test_scope_returns_legacy_failure_text_without_draining_errors():
    scope, backend = _scope()
    backend.result = "+42"
    assert scope.run_self_test().startswith("Failed: Code 42.")
    assert backend.commands == [("query", "*TST?", 240_000)]


def test_scope_missing_alias_fails_before_io_without_raw_fallback():
    config = load_device_profile("keysight/DSOX1204G")
    assert config.scpi is not None and config.scpi.queries is not None
    config.scpi.queries.pop("self_test")
    backend = ScopeBackend()
    scope = Oscilloscope(config, backend=backend)
    with pytest.raises(InstrumentConfigurationError):
        scope.run_self_test()
    assert not backend.commands and not backend.connected


@pytest.mark.parametrize(
    "reply,exception",
    [
        (TimeoutError("late test result"), InstrumentCommunicationError),
        ("0,1", InstrumentCommunicationError),
    ],
)
def test_scope_ambiguous_result_raises_without_retry_and_restores_timeout(reply, exception):
    scope, backend = _scope()
    backend.result = reply
    with pytest.raises(exception):
        scope.run_self_test()
    assert backend.commands == [("query", "*TST?", 240_000)]
    assert backend.timeout == 2000


def test_scope_self_test_is_never_invoked_by_generic_diagnostics(tmp_path, monkeypatch):
    scope, backend = _scope()
    descriptor = next(d for d in scope.operation_descriptors() if d.operation_id == "run_self_test")
    assert scope.describe_operation("run_self_test")["python_only"] is True

    monkeypatch.setattr("pytestlab.cli_typer._operation_instrument", lambda *a, **kw: scope)
    result = CliRunner().invoke(
        app, ["instrument", "execute-operation", "keysight/DSOX1204G", "run_self_test"]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "python_only_operation"

    class SemanticView:
        def operation_descriptors(self):
            return (descriptor,)

        describe_operation = staticmethod(scope.describe_operation)
        run_self_test = staticmethod(scope.run_self_test)

    rows, failures, warnings, _ = _semantic_operation_rows(SemanticView(), include_writes=True)
    assert failures == warnings == 0 and rows[0]["status"] == "skip"

    profile = tmp_path / "profile.yaml"
    profile.write_text(
        'scpi:\n  queries:\n    self_test: {template: "*TST?"}\n',
        encoding="utf-8",
    )
    for include_writes in (False, True):
        _, rows, failures, warnings, skipped = _profile_scpi_command_rows(
            str(profile), device=scope, include_writes=include_writes, strict_response=True
        )
        assert failures == warnings == 0 and skipped == 1 and rows[0]["status"] == "skip"
    _, rows, failures, warnings, skipped = _profile_scpi_command_rows(
        str(profile), strict_response=True
    )
    assert failures == warnings == skipped == 0 and rows[0]["detail"] == "*TST?"
    assert not backend.commands and not backend.connected
