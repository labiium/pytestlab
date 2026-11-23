from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from pytestlab import AutoDevice
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments.backends.lamb import LambBackend


class NoIO:
    def __init__(self):
        self.calls = []

    def connect(self):
        self.calls.append("connect")

    def disconnect(self):
        pass

    def close(self):
        pass

    def write(self, command):
        self.calls.append(command)

    def query(self, command, delay=None):
        self.calls.append(command)
        return "1"

    def set_read_termination(self, value):
        pass


@pytest.mark.parametrize(
    "method,args",
    [
        ("reset", ()),
        ("clear_status", ()),
        ("run_self_test", ()),
        ("lock_panel", ()),
        ("wait_for_operation_complete", ()),
        ("wait_for_operation_complete", (False,)),
    ],
)
def test_non_scpi_profile_never_uses_unconfigured_standard_commands(method, args):
    io = NoIO()
    instrument = AutoDevice.from_dict(
        {
            "manufacturer": "Example",
            "model": "native",
            "device_type": "instrument",
            "role": "measurement",
            "capabilities": {"standard_commands": False, "error_queue": False},
            "scpi": {"queries": {}},
        },
        backend_override=io,
    )
    with pytest.raises(InstrumentConfigurationError):
        getattr(instrument, method)(*args)
    assert io.calls == []


def test_bench_transport_override_preserves_profile_minimums_and_caller_config():
    io = NoIO()
    config = {
        "manufacturer": "Example",
        "model": "native",
        "device_type": "instrument",
        "role": "measurement",
        "transport": {"min_command_interval_s": 0.5},
        "capabilities": {"standard_commands": False, "error_queue": False},
        "scpi": {"queries": {}},
    }
    device = AutoDevice.from_dict(
        config, backend_override=io, transport_override={"min_command_interval_s": 0.1}
    )
    assert device.config.transport["min_command_interval_s"] == 0.5
    assert config["transport"]["min_command_interval_s"] == 0.5
    assert io.calls == []


def test_lamb_native_reads_and_mandatory_policy_are_explicit_and_binary_safe():
    requests = []
    original_client = httpx.Client

    def handler(request):
        import json

        payload = json.loads(request.content) if request.content else {}
        requests.append((request.url.path, payload))
        if request.url.path == "/capabilities":
            return httpx.Response(200, json={"native_read": True, "resource_timing_policy": True})
        if request.url.path == "/add":
            return httpx.Response(200, text=payload["model_name"])
        if request.url.path == "/instrument/timing":
            return httpx.Response(200, json=payload)
        if request.url.path == "/instrument/read":
            return httpx.Response(200, text="1.25\r\n")
        if request.url.path == "/instrument/read_raw":
            return httpx.Response(200, content=b"\x00\n\xff")
        raise AssertionError(request.url.path)

    with patch(
        "pytestlab.instruments.backends.lamb.httpx.Client",
        side_effect=lambda: original_client(transport=httpx.MockTransport(handler)),
    ):
        backend = LambBackend(address="GPIB0::12::INSTR", url="http://mock.invalid")
        backend.set_min_command_interval(0.5)
        backend.set_read_termination("\r\n")
        assert backend.read() == "1.25"
        assert backend.read_raw() == b"\x00\n\xff"
        backend.disconnect()
    assert requests[1] == (
        "/instrument/timing",
        {"resource_string": "GPIB0::12::INSTR", "min_command_interval_ms": 500},
    )
    text_read = next(p for name, p in requests if name == "/instrument/read")
    raw_read = next(p for name, p in requests if name == "/instrument/read_raw")
    assert "command" not in text_read and "command" not in raw_read
    assert text_read["read_termination"] == 10
    assert "read_termination" not in raw_read
    assert text_read["min_command_interval_ms"] == raw_read["min_command_interval_ms"] == 500


def test_visa_read_raw_temporarily_disables_text_termination_and_never_writes():
    from pytestlab.instruments.backends.visa_backend import VisaBackend

    class Resource:
        read_termination = "\n"

        def read(self):
            return "1.25\n"

        def read_raw(self):
            assert self.read_termination is None
            return b"\x00\n\xff"

        def write(self, command):
            raise AssertionError("unexpected write")

    backend = object.__new__(VisaBackend)
    backend.address = "MOCK"
    backend.instrument = Resource()
    assert backend.read() == "1.25"
    assert backend.read_raw() == b"\x00\n\xff"
    assert backend.instrument.read_termination == "\n"
