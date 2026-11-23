from __future__ import annotations

import pytest

from pytestlab import AutoDevice
from pytestlab.config.device_config import DeviceConfig
from pytestlab.profile_transport import ProfileTransport


class Clock:
    now = 0.0

    def __init__(self):
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class IO:
    def __init__(self, clock, address=None):
        self.clock, self.address = clock, address
        self.calls, self.policies = [], []
        self.timeout = 2000

    def connect(self):
        pass

    def close(self):
        self.calls.append(("close",))

    def disconnect(self):
        pass

    def set_min_command_interval(self, seconds):
        self.policies.append(seconds)

    def get_timeout(self):
        return self.timeout

    def set_timeout(self, value):
        self.timeout = value

    def write(self, command):
        self.calls.append(("write", command, self.clock.now))
        self.clock.now += 0.1

    def query(self, command, delay=None):
        self.calls.append(("query", command, self.clock.now, delay))
        self.clock.now += 0.1
        return "1.25"

    def query_raw(self, command, delay=None):
        self.calls.append(("raw", command, self.clock.now, delay))
        return b"\x00\n\xff"

    def read_status_byte(self):
        self.calls.append(("status", self.clock.now))
        return 0x10


@pytest.fixture
def clock(monkeypatch):
    from pytestlab import profile_transport

    value = Clock()
    monkeypatch.setattr(profile_transport.time, "monotonic", value.monotonic)
    monkeypatch.setattr(profile_transport.time, "sleep", value.sleep)
    profile_transport._RESOURCE_TIMING.clear()
    return value


def test_minimum_interval_is_after_completion_and_not_doubled(clock):
    io = IO(clock)
    transport = ProfileTransport(io, {"min_command_interval_s": 0.5})
    transport.write("A")
    transport.query("B")
    assert io.calls[0][2] == 0
    assert io.calls[1][2] == pytest.approx(0.6)
    assert clock.sleeps == [0.5]
    clock.now += 2
    transport.write("C")
    assert clock.sleeps == [0.5]
    assert io.timeout == 2000


def test_same_resource_aliases_share_spacing_and_cannot_lower_it(clock):
    one, two = IO(clock, "GPIB0::1::INSTR"), IO(clock, "gpib0::1::instr")
    a = ProfileTransport(one, {"min_command_interval_s": 0.5})
    b = ProfileTransport(two, {"min_command_interval_s": 0.1})
    a.write("A")
    b.write("B")
    assert two.calls[0][2] == pytest.approx(0.6)
    assert b.lock is a.lock


def test_other_resource_is_not_delayed(clock):
    a = ProfileTransport(IO(clock, "GPIB0::1::INSTR"), {"min_command_interval_s": 0.5})
    other_io = IO(clock, "GPIB0::2::INSTR")
    b = ProfileTransport(other_io, {"min_command_interval_s": 0.5})
    a.write("A")
    b.write("B")
    assert other_io.calls[0][2] == pytest.approx(0.1)
    assert clock.sleeps == []


def test_interval_timeout_does_not_send_the_next_command(clock):
    io = IO(clock)
    transport = ProfileTransport(io, {"min_command_interval_s": 0.5})
    transport.write("A")
    io.timeout = 300
    with pytest.raises(TimeoutError):
        transport.write("B")
    assert [call[1] for call in io.calls] == ["A"]
    assert io.timeout == 300


def test_raw_and_status_obey_spacing_without_text_eos_or_status_queries(clock):
    io = IO(clock)
    transport = ProfileTransport(io, {"min_command_interval_s": 0.5, "query_delay_s": 0.1})
    assert transport.query_raw("BINARY") == b"\x00\n\xff"
    assert transport.read_status_byte() == 0x10
    assert io.calls == [("raw", "BINARY", 0, 0.1), ("status", 0.5)]


def test_profile_query_delay_cannot_be_lowered_by_a_caller(clock):
    io = IO(clock)
    transport = ProfileTransport(io, {"query_delay_s": 0.1})
    transport.query("READ", delay=0)
    assert io.calls[-1][-1] == 0.1


@pytest.mark.parametrize(
    "profile_minimum,bench_minimum,expected",
    [(0.5, None, 0.5), (0.5, 0.1, 0.5), (0.1, 0.5, 0.5)],
)
def test_motion_factory_preserves_exact_minimum_interval(
    clock, profile_minimum, bench_minimum, expected
):
    io = IO(clock)
    config = {
        "manufacturer": "Fixture",
        "model": "Stage",
        "device_type": "motion_stage",
        "role": "fixture",
        "transport": {"min_command_interval_s": profile_minimum, "query_delay_s": 0.1},
        "motion": {
            "axes": [{"name": "x"}],
            "queries": {
                "position": {
                    "template": "POS?",
                    "response": {"type": "axis_tuple", "axes": ["x"]},
                }
            },
        },
    }
    override = None if bench_minimum is None else {"min_command_interval_s": bench_minimum}
    stage = AutoDevice.from_dict(config, backend_override=io, transport_override=override)

    assert stage.get_position() == {"x": 1.25}
    assert io.calls == [("query", "POS?", 0.0, 0.1)]
    assert clock.now == pytest.approx(0.1)
    assert clock.sleeps == []
    assert io.policies == [expected]

    clock.now += 0.2
    stage.get_position()
    assert io.calls[-1][2] == pytest.approx(0.1 + expected)
    assert clock.sleeps == pytest.approx([expected - 0.2])
    assert io.timeout == 2000


@pytest.mark.parametrize("section", [None, "motion", "switch", "transport"])
def test_removed_pacing_setting_is_rejected(section):
    setting = {"command_pacing_s": 0.1}
    with pytest.raises(ValueError, match="command_pacing_s"):
        DeviceConfig(
            manufacturer="Fixture",
            model="Stage",
            device_type="motion_stage",
            role="fixture",
            **(setting if section is None else {section: setting}),
        )


def test_direct_transport_rejects_removed_pacing(clock):
    with pytest.raises(ValueError, match="command_pacing_s"):
        ProfileTransport(IO(clock), {"command_pacing_s": 0.1})
