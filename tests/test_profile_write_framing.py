from __future__ import annotations

import pytest

from pytestlab.config.device_config import DeviceConfig
from pytestlab.config.loader import load_device_profile
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.prober import GenericProberDevice
from pytestlab.profile_transport import ProfileTransport


class Wire:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.timeout = 1000

    def connect(self) -> None:
        self.calls.append(("connect", None))

    def disconnect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def set_read_termination(self, value: str | None) -> None:
        self.calls.append(("read_termination", value))

    def set_write_termination(self, value: str | None) -> None:
        self.calls.append(("write_termination", value))

    def set_min_command_interval(self, seconds: float) -> None:
        pass

    def get_timeout(self) -> int:
        return self.timeout

    def set_timeout(self, value: int) -> None:
        self.timeout = value

    def query(self, command: str, delay: float | None = None) -> str:
        self.calls.append(("query", command))
        return "0 1000 2000 0 H 31"


def test_eoi_only_framing_applies_to_direct_profile_queries() -> None:
    wire = Wire()
    transport = ProfileTransport(wire, {"write_termination": None})
    transport.query("31")
    assert wire.calls == [("write_termination", None), ("query", "31")]


def test_framing_is_applied_before_connect_and_after_reconnect() -> None:
    wire = Wire()
    transport = ProfileTransport(wire, {"message_io": {"write_termination": "\r\n"}})
    transport.connect()
    transport.disconnect()
    transport.connect()
    assert wire.calls == [
        ("write_termination", "\r\n"),
        ("connect", None),
        ("write_termination", "\r\n"),
        ("connect", None),
    ]


@pytest.mark.parametrize("value", [True, 1, [], {}, "bad", "\n\n"])
def test_invalid_write_framing_fails_before_io(value: object) -> None:
    wire = Wire()
    with pytest.raises(ValueError, match="write_termination"):
        ProfileTransport(wire, {"message_io": {"write_termination": value}})
    assert wire.calls == []


def test_required_write_framing_cannot_be_silently_ignored() -> None:
    wire = Wire()
    wire.set_write_termination = None  # type: ignore[assignment]
    transport = ProfileTransport(wire, {"write_termination": None})
    with pytest.raises(InstrumentConfigurationError, match="write termination"):
        transport.connect()
    assert wire.calls == []


@pytest.mark.parametrize("value", [None, "", "\n", "\r", "\r\n"])
def test_transport_config_accepts_explicit_write_framing(value: str | None) -> None:
    config = DeviceConfig(
        manufacturer="Fixture",
        model="Test",
        device_type="prober",
        role="dut_control",
        transport={"write_termination": value},
    )
    assert config.transport["write_termination"] == value


def test_packaged_prober_applies_eoi_only_framing_to_high_level_readback() -> None:
    profile = load_device_profile("suss/PA200")
    assert "write_termination" in profile.transport
    assert profile.transport["write_termination"] is None
    wire = Wire()
    prober = GenericProberDevice(profile, wire)
    prober.get_position()
    query_index = wire.calls.index(("query", "31"))
    assert ("write_termination", None) in wire.calls[:query_index]


@pytest.mark.parametrize("key", ["write_terminaton", "read_terminaton"])
def test_unknown_message_framing_is_rejected_before_io(key: str) -> None:
    wire = Wire()
    settings = {"message_io": {key: "\r"}}
    with pytest.raises(ValueError, match="Unknown.*message_io"):
        ProfileTransport(wire, settings)
    with pytest.raises(ValueError, match="Unknown.*message_io"):
        DeviceConfig(
            manufacturer="Fixture",
            model="Test",
            device_type="prober",
            role="dut_control",
            transport=settings,
        )
    assert wire.calls == []
