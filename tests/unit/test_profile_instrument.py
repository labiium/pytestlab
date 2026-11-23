from __future__ import annotations

import pytest

from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments import AutoInstrument


class _Backend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def connect(self) -> None:
        self.calls.append(("connect", None))

    def disconnect(self) -> None:
        self.calls.append(("disconnect", None))

    def close(self) -> None:
        self.calls.append(("close", None))

    def write(self, command: str) -> None:
        self.calls.append(("write", command))

    def query(self, command: str, delay: float | None = None) -> str:
        self.calls.append(("query", command))
        return "0" if command == "SYST:ERR?" else "0:READY"

    def query_raw(self, command: str, delay: float | None = None) -> bytes:
        raise AssertionError("raw query is not expected")

    def set_timeout(self, timeout_ms: int) -> None:
        del timeout_ms

    def get_timeout(self) -> int:
        return 100

    def read_status_byte(self) -> int:
        self.calls.append(("status", None))
        return 32


def _config() -> dict[str, object]:
    return {
        "manufacturer": "Test",
        "model": "ProfileDevice",
        "device_type": "instrument",
        "role": "measurement",
        "scpi": {
            "commands": {"set_value": {"template": "SET {value}"}},
            "queries": {
                "read_value": {"template": "READ?", "response": {"type": "str"}},
                "get_error": {"template": "SYST:ERR?"},
            },
        },
        "operation_options": {
            "set_value": {
                "mode": "write",
                "transport": {"set": "set_value"},
                "value": {
                    "kind": "range",
                    "min": 0,
                    "max": 10,
                    "bindings": [{"alias": "set", "parameter": "value"}],
                },
            },
            "read_value": {"mode": "query", "transport": {"read": "read_value"}},
            "status_byte": {"mode": "native", "backend_method": "read_status_byte"},
            "guarded": {
                "mode": "write",
                "requires_context": ["interlock_closed"],
                "transport": {"set": "set_value"},
                "value": {
                    "kind": "range",
                    "min": 0,
                    "max": 10,
                    "bindings": [{"alias": "set", "parameter": "value"}],
                },
            },
        },
    }


def test_profile_driver_discovers_and_describes_without_backend_io() -> None:
    backend = _Backend()
    instrument = AutoInstrument.from_dict(_config(), backend_override=backend)

    description = instrument.describe_operation("read_value")

    assert "read_value" in instrument.list_operations()
    assert description["method"] == "execute_profile_operation"
    assert backend.calls == []


def test_profile_driver_executes_scpi_and_native_operations() -> None:
    backend = _Backend()
    instrument = AutoInstrument.from_dict(_config(), backend_override=backend)

    instrument.execute_profile_operation("set_value", value=5)
    assert instrument.execute_profile_operation("read_value") == "0:READY"
    assert instrument.execute_profile_operation("status_byte") == 32

    assert ("write", "SET 5") in backend.calls
    assert ("query", "READ?") in backend.calls
    assert ("status", None) in backend.calls
    assert not any(call[0] == "query" and call[1] == "*STB?" for call in backend.calls)


def test_profile_driver_checks_context_and_ranges_before_backend_io() -> None:
    backend = _Backend()
    instrument = AutoInstrument.from_dict(_config(), backend_override=backend)

    with pytest.raises(InstrumentConfigurationError, match="safety context"):
        instrument.execute_profile_operation("guarded", value=5)
    assert backend.calls == []

    with pytest.raises(InstrumentParameterError):
        instrument.execute_profile_operation("set_value", value=11)
    assert backend.calls == []


def test_profile_query_without_error_queue_does_not_probe_idn_or_error_alias() -> None:
    config = _config()
    scpi = config["scpi"]
    assert isinstance(scpi, dict)
    queries = scpi["queries"]
    assert isinstance(queries, dict)
    queries.pop("get_error")
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    assert instrument.supports_error_queue() is False
    assert instrument.execute_profile_operation("read_value") == "0:READY"
    assert backend.calls == [("connect", None), ("query", "READ?")]


def test_profile_driver_alias_resolves_explicit_driver_without_model_setup() -> None:
    config = _config()
    config["driver"] = "profile_instrument"
    instrument = AutoInstrument.from_dict(config, backend_override=_Backend())
    assert instrument.__class__.__name__ == "ProfileInstrument"


def test_profile_query_uses_explicit_query_alias_when_mapping_order_is_reversed() -> None:
    config = _config()
    config["scpi"]["commands"]["prepare"] = {"template": "PREP"}
    config["operation_options"]["reversed_query"] = {
        "mode": "query",
        "transport": {"query": "read_value", "write": "prepare"},
    }
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    assert instrument.execute_profile_operation("reversed_query") == "0:READY"
    assert [(kind, command) for kind, command in backend.calls if command != "SYST:ERR?"] == [
        ("connect", None),
        ("write", "PREP"),
        ("query", "READ?"),
    ]


def test_profile_query_with_multiple_aliases_and_no_query_slot_fails_before_io() -> None:
    config = _config()
    config["scpi"]["commands"]["prepare"] = {"template": "PREP"}
    config["operation_options"]["ambiguous_query"] = {
        "mode": "query",
        "transport": {"first": "prepare", "second": "read_value"},
    }
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    with pytest.raises(InstrumentConfigurationError, match="exactly one query transport alias"):
        instrument.execute_profile_operation("ambiguous_query")
    assert backend.calls == []


def test_profile_query_can_be_state_changing_when_profile_says_so() -> None:
    config = _config()
    config["operation_options"]["control_query"] = {
        "mode": "query",
        "safety_class": "state-changing",
        "transport": {"query": "read_value"},
    }
    instrument = AutoInstrument.from_dict(config, backend_override=_Backend())

    description = instrument.describe_operation("control_query")
    assert description["safety_class"] == "state-changing"
    assert description["execution"]["safety_class"] == "state-changing"


def test_profile_integer_constraint_rejects_fractional_value_before_io() -> None:
    config = _config()
    config["operation_options"]["integer_value"] = {
        "mode": "write",
        "transport": {"set": "set_value"},
        "value": {
            "kind": "range",
            "min": 0,
            "max": 10,
            "constraints": {"integer": True},
            "bindings": [{"alias": "set", "parameter": "value"}],
        },
    }
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    with pytest.raises(InstrumentParameterError, match="integer"):
        instrument.execute_profile_operation("integer_value", value=1.5)
    assert backend.calls == []


def test_native_operation_support_reports_missing_supplied_backend_without_connecting() -> None:
    config = _config()
    backend = _Backend()
    backend.read_status_byte = None
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    assert instrument.supports_operation("status_byte") is False
    assert instrument.describe_operation("status_byte")["support"]["supported"] is False
    catalog = instrument.describe_operations(scope="model")["general"]
    status = next(item for item in catalog if item["operation_id"] == "status_byte")
    assert status["support"] == instrument.describe_operation("status_byte")["support"]
    supported = instrument.describe_operations(scope="model", include_unsupported=False)["general"]
    assert all(item["operation_id"] != "status_byte" for item in supported)
    assert backend.calls == []


def test_profile_write_missing_required_parameter_fails_before_any_alias_is_sent() -> None:
    config = _config()
    config["scpi"]["commands"]["prepare"] = {"template": "PREP"}
    config["operation_options"]["multi_write"] = {
        "mode": "write",
        "transport": {"first": "prepare", "second": "set_value"},
        "value": {
            "kind": "range",
            "min": 0,
            "max": 10,
            "bindings": [{"alias": "second", "parameter": "value"}],
        },
    }
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    with pytest.raises(InstrumentParameterError, match="Required profile parameter"):
        instrument.execute_profile_operation("multi_write")
    assert backend.calls == []


def test_profile_integer_constraint_canonicalizes_whole_float_before_formatting() -> None:
    config = _config()
    config["operation_options"]["integer_value"] = {
        "mode": "write",
        "transport": {"set": "set_value"},
        "value": {
            "kind": "range",
            "min": 0,
            "max": 10,
            "constraints": {"integer": True},
            "bindings": [{"alias": "set", "parameter": "value"}],
        },
    }
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    instrument.execute_profile_operation("integer_value", value=1.0)
    assert ("write", "SET 1") in backend.calls


@pytest.mark.parametrize("invalid_status", [-1, 256])
def test_native_status_byte_rejects_values_outside_byte_range(invalid_status: int) -> None:
    config = _config()
    backend = _Backend()
    backend.read_status_byte = lambda: invalid_status
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    with pytest.raises(InstrumentCommunicationError, match="invalid status byte"):
        instrument.execute_profile_operation("status_byte")


def test_generic_execution_rejects_legacy_operation_without_explicit_mode_before_io() -> None:
    config = _config()
    config["operation_options"]["legacy_query"] = {
        "transport": {"query": "read_value"},
    }
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    with pytest.raises(InstrumentConfigurationError, match="explicit execution mode"):
        instrument.execute_profile_operation("legacy_query")
    assert backend.calls == []


def test_profile_message_io_read_termination_is_set_before_connect() -> None:
    config = _config()
    config["capabilities"] = {"message_io": {"read_termination": "\n"}}
    backend = _Backend()
    backend.set_read_termination = lambda value: backend.calls.append(("termination", value))
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    instrument.execute_profile_operation("set_value", value=5)

    assert backend.calls.index(("termination", "\n")) < backend.calls.index(("connect", None))


def test_profile_message_io_requires_backend_termination_capability_before_connect() -> None:
    config = _config()
    config["capabilities"] = {"message_io": {"read_termination": "\n"}}
    backend = _Backend()
    instrument = AutoInstrument.from_dict(config, backend_override=backend)

    with pytest.raises(InstrumentConfigurationError, match="read-termination"):
        instrument.execute_profile_operation("set_value", value=5)
    assert backend.calls == []


def test_profile_without_message_io_metadata_does_not_configure_termination() -> None:
    backend = _Backend()
    instrument = AutoInstrument.from_dict(_config(), backend_override=backend)

    instrument.execute_profile_operation("set_value", value=5)

    assert not any(kind == "termination" for kind, _ in backend.calls)
