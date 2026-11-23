from __future__ import annotations

import json

import httpx
import pytest

from pytestlab.errors import InstrumentConnectionError
from pytestlab.instruments.backends.lamb import LambBackend


def _backend(address, responses):
    requests = []

    def handle(request):
        requests.append((request.url.path, json.loads(request.content)))
        status, body = responses.pop(0)
        return httpx.Response(status, content=body)

    backend = LambBackend(
        address=address, url="http://lamb.test", model_name="unused", serial_number="unused"
    )
    backend._client = httpx.Client(transport=httpx.MockTransport(handle))
    return backend, requests


@pytest.mark.parametrize("address", ["GPIB0::23::INSTR", "GPIB0::23::4::INSTR", "gpib1::9::instr"])
@pytest.mark.parametrize("connect_first", [False, True])
def test_explicit_gpib_activates_exact_resource_once_before_io(address, connect_first):
    backend, requests = _backend(address, [(200, address.encode()), (200, b"ID"), (200, b"ID")])
    try:
        if connect_first:
            backend.connect()
            backend.connect()
            assert requests == [("/add", {"model_name": address})]
        assert backend.query("*IDN?") == backend.query("*IDN?") == "ID"
        assert requests == [
            ("/add", {"model_name": address}),
            (
                "/instrument/query",
                {
                    "resource_string": address,
                    "command": "*IDN?",
                    "timeout_ms": 30_000,
                    "read_termination": None,
                },
            ),
            (
                "/instrument/query",
                {
                    "resource_string": address,
                    "command": "*IDN?",
                    "timeout_ms": 30_000,
                    "read_termination": None,
                },
            ),
        ]
    finally:
        backend.disconnect()


@pytest.mark.parametrize("reply", [b"WRONG::RESOURCE::INSTR", b"", b"GPIB0::24::INSTR"])
@pytest.mark.parametrize("during_recovery", [False, True])
def test_mismatched_registration_never_changes_target_or_replays_command(reply, during_recovery):
    address = "GPIB0::23::INSTR"
    if during_recovery:
        responses = [(200, address.encode()), (404, b"Instrument not found"), (200, reply)]
    else:
        responses = [(200, reply)]
    backend, requests = _backend(address, responses)
    with pytest.raises(InstrumentConnectionError, match="exact configured resource"):
        backend.query("READ?")
    assert backend.instrument_address == address
    assert not backend._resource_acquired
    expected = ["/add", "/instrument/query", "/add"] if during_recovery else ["/add"]
    assert [path for path, _ in requests] == expected
    assert all(
        payload.get("model_name", payload.get("resource_string")) == address
        for _, payload in requests
    )
    backend.close()
    assert [path for path, _ in requests] == expected


def test_write_and_raw_query_use_canonical_resource_string():
    address = "USB0::0x1234::0x5678::SERIAL::INSTR"
    backend, requests = _backend(address, [(200, b""), (200, b"\x01\x02")])
    try:
        backend.write("*CLS")
        assert backend.query_raw("READ?") == b"\x01\x02"
        assert [path for path, _ in requests] == ["/instrument/write", "/instrument/query_raw"]
        assert all(payload["resource_string"] == address for _, payload in requests)
        assert all("visa_string" not in payload for _, payload in requests)
    finally:
        backend.disconnect()


def test_explicit_resource_is_pinned_after_close(monkeypatch):
    address = "GPIB0::23::INSTR"
    backend, first = _backend(address, [(200, address.encode()), (200, b"Closed")])
    other, second = _backend(address, [(200, address.encode()), (200, b"READ")])
    replacement_client = other._client

    backend.connect()
    backend.instrument_address = "GPIB0::999::INSTR"
    assert backend._instrument_payload("READ?")["resource_string"] == address
    assert backend._status_byte_payload()["resource_string"] == address
    backend.close()
    assert backend.instrument_address is None
    assert first == [
        ("/add", {"model_name": address}),
        ("/instrument/close", {"resource_string": address, "command": ""}),
    ]
    monkeypatch.setattr(backend, "_get_client", lambda: replacement_client)
    assert backend.query("READ?") == "READ"
    assert second[0] == ("/add", {"model_name": address})
    assert second[1][1]["resource_string"] == address
    other.disconnect()
