from types import SimpleNamespace
from unittest.mock import Mock

from pytestlab.common.health import HealthStatus
from pytestlab.instruments.command_session import InstrumentCommandSession
from pytestlab.instruments.health_monitor import InstrumentHealthMonitor


class _Backend:
    def connect(self):
        pass

    def write(self, command):
        self.last_write = command

    def query(self, command, delay=None):
        return "response"

    def query_raw(self, command, delay=None):
        return b"raw"


class _SessionInstrument:
    config = SimpleNamespace(model="test")

    def __init__(self):
        self._backend = _Backend()
        self._command_log = []
        self._connected = False
        self._error_check = Mock()

    def _ensure_backend_connected(self):
        self._connected = True

    def supports_error_queue(self):
        return False


def test_command_session_skips_error_polling_when_profile_disables_queue():
    instrument = _SessionInstrument()
    session = InstrumentCommandSession(instrument)

    session.send_command("CONF")
    assert session.query("READ?") == "response"
    assert session.query_raw("DATA?") == b"raw"
    instrument._error_check.assert_not_called()


class _HealthInstrument:
    def __init__(self, capabilities, status_byte=0x0A):
        self.config = SimpleNamespace(capabilities=capabilities)
        self.status_byte_value = status_byte
        self.id = Mock(return_value="unused")
        self.get_all_errors = Mock(return_value=[])
        self.read_status_byte = Mock(return_value=status_byte)
        self._ensure_backend_connected = Mock()
        self.has_profile_alias = Mock(side_effect=lambda alias: alias == "identify")
        self.supports_error_queue = Mock(return_value=True)


def test_health_uses_profile_status_flags_without_identity_or_error_queue():
    instrument = _HealthInstrument(
        {
            "identity": {"enabled": False},
            "error_queue": False,
            "status_byte": {
                "enabled": True,
                "flags": {
                    "matrix_open": {"mask": 0x08, "severity": "warning"},
                    "syntax_error": {"mask": 0x02, "severity": "warning"},
                    "transport": {"mask": 0x80, "severity": "info"},
                },
            },
        }
    )
    instrument.supports_error_queue.return_value = False

    report = InstrumentHealthMonitor(instrument).check()

    assert report.status is HealthStatus.WARNING
    assert report.instrument_idn is None
    assert report.status_byte == 0x0A
    assert report.status_flags == {"matrix_open": True, "syntax_error": True, "transport": False}
    instrument.id.assert_not_called()
    instrument.get_all_errors.assert_not_called()
    instrument.read_status_byte.assert_called_once_with()


def test_optional_identity_failure_is_warning_after_connection_succeeds():
    instrument = _HealthInstrument({"identity": {"enabled": True, "required": False}})
    instrument.id.side_effect = RuntimeError("identity unsupported")
    instrument.supports_error_queue.return_value = False
    instrument.has_profile_alias.return_value = True

    report = InstrumentHealthMonitor(instrument).check()

    assert report.status is HealthStatus.WARNING
    assert not report.errors
    assert any("IDN Query" in message for message in report.warnings)
