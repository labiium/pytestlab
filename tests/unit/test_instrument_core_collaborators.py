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

    def get_timeout(self) -> int:
        return getattr(self, "timeout_ms", 5000)


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
