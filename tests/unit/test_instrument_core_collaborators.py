from __future__ import annotations

import pytest

from pytestlab.common.health import HealthStatus
from pytestlab.config.device_config import DeviceRole
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.instruments.instrument import Instrument


class CoreBackend:
    def __init__(self):
        self.connected = False
        self.timeout_ms = 5000
        self.timeout_history: list[int] = []
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.raw_queries: list[str] = []
        self.responses: dict[str, list[str]] = {
            ":SYSTem:ERRor?": ['+0,"No error"'],
            "SYSTem:ERRor?": ['+0,"No error"'],
            "*IDN?": ["PyTestLab,Core,001,1.0"],
            "*OPC?": ["1"],
            "*ESR?": ["0", "1"],
        }
        self.raw_responses: dict[str, bytes] = {"RAW?": b"\x01\x02"}

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def close(self) -> None:
        self.connected = False

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        self.queries.append(cmd)
        responses = self.responses.get(cmd, ['+0,"No error"'])
        if len(responses) > 1:
            return responses.pop(0)
        return responses[0]

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        self.raw_queries.append(cmd)
        return self.raw_responses[cmd]

    def set_timeout(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        self.timeout_history.append(timeout_ms)

    def get_timeout(self) -> int:
        return self.timeout_ms


@pytest.fixture
def core_instrument():
    config = InstrumentConfig(
        manufacturer="PyTestLab",
        model="CoreInstrument",
        device_type="instrument",
        role=DeviceRole.MEASUREMENT,
    )
    backend = CoreBackend()
    return Instrument(config=config, backend=backend), backend


def test_command_session_preserves_success_log_shape(core_instrument):
    instrument, backend = core_instrument

    instrument._send_command("CONF:VOLT")
    response = instrument._query("*IDN?")
    raw = instrument._query_raw("RAW?")

    assert backend.connected is True
    assert response == "PyTestLab,Core,001,1.0"
    assert raw == b"\x01\x02"
    assert [entry["type"] for entry in instrument._command_log] == [
        "write",
        "query",
        "query_raw",
    ]
    assert instrument._command_log[0]["command"] == "CONF:VOLT"
    assert instrument._command_log[1]["response"] == "PyTestLab,Core,001,1.0"
    assert instrument._command_log[2]["response_len"] == 2


def test_command_session_preserves_failure_log_shape(core_instrument):
    instrument, backend = core_instrument

    def fail_write(cmd: str) -> None:
        raise RuntimeError("write failed")

    backend.write = fail_write

    with pytest.raises(InstrumentCommunicationError, match="Failed to send command"):
        instrument._send_command("BAD")

    assert instrument._command_log[-1]["command"] == "BAD"
    assert instrument._command_log[-1]["success"] is False
    assert instrument._command_log[-1]["type"] == "write"


def test_waiter_preserves_wait_log_entries(core_instrument):
    instrument, backend = core_instrument

    instrument._wait()
    instrument._wait_event()

    assert "*OPC?" in backend.queries
    assert backend.queries.count("*ESR?") == 2
    assert instrument._command_log[-2]["type"] == "wait"
    assert instrument._command_log[-1]["type"] == "wait_event"
    assert instrument._command_log[-1]["final_esr"] == 1


def test_base_health_monitor_preserves_status_mapping(core_instrument):
    instrument, backend = core_instrument
    backend.responses[":SYSTem:ERRor?"] = ['+0,"No error"']
    backend.responses["SYSTem:ERRor?"] = ['-101,"Command error"', '+0,"No error"']

    report = instrument.health_check()

    assert report.status is HealthStatus.WARNING
    assert report.instrument_idn == "PyTestLab,Core,001,1.0"
    assert report.warnings == ["Stored Error: -101 - Command error"]


def test_temporary_communication_timeout_restores_backend_timeout(core_instrument):
    instrument, backend = core_instrument

    assert instrument.get_communication_timeout() == 5000
    with instrument.temporary_communication_timeout(300_000):
        assert backend.timeout_ms == 300_000

    assert backend.timeout_ms == 5000
    assert backend.timeout_history == [300_000, 5000]


def test_wait_for_operation_complete_applies_method_timeout_hint(core_instrument):
    instrument, backend = core_instrument

    response = instrument.wait_for_operation_complete(timeout=123.456)

    assert response == "1"
    assert "*OPC?" in backend.queries
    assert backend.timeout_history[-2:] == [123_456, 5000]
    assert backend.timeout_ms == 5000


def test_low_level_helpers_accept_one_shot_timeout(core_instrument):
    instrument, backend = core_instrument

    instrument._send_command("CONF:VOLT", timeout_ms=40_000)
    response = instrument._query("*IDN?", timeout_ms=50_000)
    raw = instrument._query_raw("RAW?", timeout_ms=60_000)

    assert response == "PyTestLab,Core,001,1.0"
    assert raw == b"\x01\x02"
    assert backend.timeout_history == [40_000, 5000, 50_000, 5000, 60_000, 5000]
    assert backend.timeout_ms == 5000
