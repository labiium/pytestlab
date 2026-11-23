from __future__ import annotations

import httpx
import pytest

from pytestlab.errors import InstrumentCommunicationError
from pytestlab.instruments.backends.lamb import LambBackend
from pytestlab.instruments.backends.visa_backend import VisaBackend


class _LambClient:
    instances: list[_LambClient] = []

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.status_attempts = 0
        self.instances.append(self)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        payload = kwargs.get("json")
        assert isinstance(payload, dict)
        self.requests.append((url, payload))
        if url.endswith("/instrument/read_status_byte"):
            self.status_attempts += 1
            if self.status_attempts == 1:
                return httpx.Response(
                    404, text="Instrument not found", request=httpx.Request("POST", url)
                )
            return httpx.Response(
                200, json={"status_byte": 0x98}, request=httpx.Request("POST", url)
            )
        if url.endswith("/instrument/query"):
            return httpx.Response(200, content=b"HP3458A\r\n", request=httpx.Request("POST", url))
        if url.endswith("/instrument/query_raw"):
            return httpx.Response(200, content=b"\x00\n\xff", request=httpx.Request("POST", url))
        if url.endswith("/instrument/close"):
            return httpx.Response(200, text="Closed", request=httpx.Request("POST", url))
        if url.endswith("/add"):
            return httpx.Response(
                200, text=str(payload["model_name"]), request=httpx.Request("POST", url)
            )
        raise AssertionError(url)

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        assert url.endswith("/capabilities")
        self.requests.append((url, {}))
        return httpx.Response(
            200,
            json={"query_delay_ms": True, "query_delay_protocols": ["GPIB"]},
            request=httpx.Request("GET", url),
        )

    def close(self) -> None:
        pass


def test_lamb_native_status_retry_preserves_uri_and_separates_text_eos(monkeypatch) -> None:
    _LambClient.instances.clear()
    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", _LambClient)
    uri = "GPIB0::12::INSTR"
    backend = LambBackend(address=uri, url="http://lamb.test", timeout_ms=2000)

    assert backend.read_status_byte() == 0x98
    backend.set_read_termination("\n")
    assert backend.query("ID?", delay=0.1) == "HP3458A"
    assert backend.query_raw("BINARY?", delay=0.002) == b"\x00\n\xff"
    backend.close()

    requests = _LambClient.instances[0].requests
    assert requests[:4] == [
        ("http://lamb.test/add", {"model_name": uri}),
        (
            "http://lamb.test/instrument/read_status_byte",
            {"resource_string": uri, "timeout_ms": 2000},
        ),
        ("http://lamb.test/add", {"model_name": uri}),
        (
            "http://lamb.test/instrument/read_status_byte",
            {"resource_string": uri, "timeout_ms": 2000},
        ),
    ]
    query_payload = next(payload for url, payload in requests if url.endswith("/instrument/query"))
    assert query_payload["read_termination"] == 10
    assert query_payload["query_delay_ms"] == 100
    raw_payload = next(
        payload for url, payload in requests if url.endswith("/instrument/query_raw")
    )
    assert "read_termination" not in raw_payload
    assert raw_payload["query_delay_ms"] == 2
    assert [url for url, _ in requests].count("http://lamb.test/capabilities") == 1
    assert backend.instrument_address is None
    assert backend._explicit_address == uri


def test_lamb_native_status_rejects_boolean_payload(monkeypatch) -> None:
    class BoolClient(_LambClient):
        def post(self, url: str, **kwargs: object) -> httpx.Response:
            if url.endswith("/instrument/read_status_byte"):
                return httpx.Response(
                    200, json={"status_byte": True}, request=httpx.Request("POST", url)
                )
            return super().post(url, **kwargs)

    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", BoolClient)
    backend = LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")
    with pytest.raises(InstrumentCommunicationError, match="invalid response"):
        backend.read_status_byte()


def test_lamb_query_delay_rejects_invalid_values() -> None:
    backend = LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")
    with pytest.raises(ValueError, match="finite, non-negative"):
        backend.query("ID?", delay=-0.1)
    with pytest.raises(ValueError, match="finite, non-negative"):
        backend.query("ID?", delay=float("nan"))


def test_lamb_query_delay_requires_server_capability(monkeypatch) -> None:
    class OldServerClient(_LambClient):
        def get(self, url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(404, text="Not found", request=httpx.Request("GET", url))

    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", OldServerClient)
    backend = LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")
    with pytest.raises(InstrumentCommunicationError, match="query_delay_ms capability"):
        backend.query("ID?", delay=0.1)


def test_zero_query_delay_does_not_require_capability(monkeypatch) -> None:
    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", _LambClient)
    backend = LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")
    assert backend._query_delay_ms(0) is None


def test_visa_native_status_and_text_termination_do_not_use_scpi() -> None:
    class FakeInstrument:
        read_termination = ""
        timeout = 5000
        calls: list[str] = []

        def read_stb(self) -> int:
            self.calls.append("read_stb")
            return 0x43

    backend = object.__new__(VisaBackend)
    backend.address = "GPIB0::22::INSTR"
    backend.instrument = FakeInstrument()
    backend._timeout_ms = 5000
    backend._read_termination = None

    backend.set_read_termination("\r\n")
    assert backend.instrument.read_termination == "\r\n"
    assert backend.read_status_byte() == 0x43
    assert backend.instrument.calls == ["read_stb"]


@pytest.mark.parametrize("termination", [None, "", "\n", "\r", "\r\n"])
def test_visa_write_termination_applies_to_resource_without_commands(termination) -> None:
    class FakeInstrument:
        write_termination = "default"

    backend = object.__new__(VisaBackend)
    backend.address = "GPIB0::1::INSTR"
    backend.instrument = FakeInstrument()
    backend._write_termination = None

    backend.set_write_termination(termination)

    expected = "" if termination is None else termination
    assert backend.instrument.write_termination == expected


@pytest.mark.parametrize("termination", ["x", "\n\r", "\x00", 1, True])
def test_visa_write_termination_rejects_invalid_values(termination) -> None:
    backend = object.__new__(VisaBackend)
    backend.address = "GPIB0::1::INSTR"
    backend.instrument = None
    backend._write_termination = None

    with pytest.raises((TypeError, ValueError)):
        backend.set_write_termination(termination)


def test_lamb_write_termination_capability_precedes_io_and_frames_commands(monkeypatch) -> None:
    class FramingClient(_LambClient):
        def __init__(self) -> None:
            super().__init__()
            self.requests: list[tuple[str, dict[str, object]]] = []

        def get(self, url: str, **kwargs: object) -> httpx.Response:
            self.requests.append((url, {}))
            return httpx.Response(
                200,
                json={"write_termination": True},
                request=httpx.Request("GET", url),
            )

        def post(self, url: str, **kwargs: object) -> httpx.Response:
            payload = kwargs.get("json")
            assert isinstance(payload, dict)
            self.requests.append((url, payload))
            if url.endswith("/add"):
                return httpx.Response(
                    200, text=str(payload["model_name"]), request=httpx.Request("POST", url)
                )
            if url.endswith("/instrument/write"):
                return httpx.Response(200, request=httpx.Request("POST", url))
            raise AssertionError(url)

    FramingClient.instances.clear()
    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", FramingClient)
    backend = LambBackend(address="GPIB0::1::INSTR", url="http://lamb.test")
    backend.set_write_termination(None)
    backend.write("CONF")

    requests = FramingClient.instances[0].requests
    assert requests[0][0].endswith("/capabilities")
    assert requests[1] == ("http://lamb.test/add", {"model_name": "GPIB0::1::INSTR"})
    assert requests[2][0].endswith("/instrument/write")
    assert requests[2][1]["write_termination"] == ""


def test_lamb_write_termination_fails_before_activation_on_old_server(monkeypatch) -> None:
    class OldServerClient(_LambClient):
        def get(self, url: str, **kwargs: object) -> httpx.Response:
            self.requests.append((url, {}))
            return httpx.Response(
                200,
                json={"query_delay_ms": True},
                request=httpx.Request("GET", url),
            )

    OldServerClient.instances.clear()
    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", OldServerClient)
    backend = LambBackend(model_name="DMM", url="http://lamb.test")
    with pytest.raises(InstrumentCommunicationError, match="write_termination capability"):
        backend.set_write_termination("\n")

    assert [url for url, _ in OldServerClient.instances[0].requests] == [
        "http://lamb.test/capabilities"
    ]
