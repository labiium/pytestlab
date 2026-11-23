from __future__ import annotations

from pytestlab import AutoInstrument


class FakeIO:
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
        if command == "ID?":
            return "HP3458A"
        if command == "*IDN?":
            return "HEWLETT PACKARD,4142B,0,4.20"
        raise AssertionError(command)

    def query_raw(self, command: str, delay: float | None = None) -> bytes:
        self.calls.append(("query_raw", command))
        return b""

    def set_timeout(self, timeout_ms: int) -> None:
        self.calls.append(("timeout", str(timeout_ms)))

    def get_timeout(self) -> int:
        return 2000

    def set_read_termination(self, value: str | None) -> None:
        self.calls.append(("read_termination", value))

    def read_status_byte(self) -> int:
        self.calls.append(("read_status_byte", None))
        return 0x98


def test_3458a_uses_generic_instrument_identity_and_native_status() -> None:
    io = FakeIO()
    instrument = AutoInstrument.from_preset("agilent/3458A", backend_override=io)
    assert instrument.id() == "HP3458A"
    assert instrument.read_status_byte() == 0x98
    assert instrument.supports_native_status_byte()
    assert [call for call in io.calls if call[0] == "query"] == [("query", "ID?")]


def test_4142b_uses_same_generic_instrument_surface() -> None:
    io = FakeIO()
    instrument = AutoInstrument.from_preset("hp/4142B", backend_override=io)
    assert instrument.id() == "HEWLETT PACKARD,4142B,0,4.20"
    assert instrument.read_status_byte() == 0x98
    assert [call for call in io.calls if call[0] == "query"] == [("query", "*IDN?")]


def test_native_health_check_does_not_invent_scpi_error_queries():
    from pytestlab.common.health import HealthStatus

    io = FakeIO()
    instrument = AutoInstrument.from_preset("agilent/3458A", backend_override=io)
    report = instrument.health_check()
    assert report.status is HealthStatus.OK
    assert report.instrument_idn == "HP3458A"
    assert [call for call in io.calls if call[0] == "query"] == [("query", "ID?")]


def test_profile_can_disable_identity_and_error_queue_without_io():
    import pytest

    from pytestlab import AutoDevice
    from pytestlab.common.health import HealthStatus
    from pytestlab.errors import InstrumentConfigurationError

    io = FakeIO()
    device = AutoDevice.from_dict(
        {
            "manufacturer": "Example",
            "model": "status-only",
            "device_type": "instrument",
            "role": "metadata",
            "capabilities": {"identity": False, "error_queue": False},
            "scpi": {"queries": {}},
        },
        backend_override=io,
    )
    assert not device.supports_identity()
    with pytest.raises(InstrumentConfigurationError, match="identity capability"):
        device.id()
    assert device.health_check().status is HealthStatus.UNKNOWN
    assert io.calls == []


def test_explicit_disabled_error_queue_methods_reject_without_io():
    import pytest

    from pytestlab.errors import InstrumentConfigurationError

    io = FakeIO()
    instrument = AutoInstrument.from_preset("agilent/3458A", backend_override=io)
    for method in (instrument.get_error, instrument.get_all_errors):
        with pytest.raises(InstrumentConfigurationError, match="error queue"):
            method()
    assert io.calls == []
