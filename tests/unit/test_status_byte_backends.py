from __future__ import annotations

import pytest

from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConnectionError
from pytestlab.instruments.backends import lamb as lamb_module
from pytestlab.instruments.backends import visa_backend as visa_module
from pytestlab.instruments.backends.visa_backend import VisaBackend


class _LambResponse:
    def __init__(self, payload: object, *, status_code: int = 200, text: str = "") -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.content = text.encode()

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise lamb_module.httpx.HTTPStatusError(
                "request failed",
                request=lamb_module.httpx.Request(
                    "POST", "http://lamb.test/instrument/read_status_byte"
                ),
                response=lamb_module.httpx.Response(self.status_code, text=self.text),
            )


def _address_ack(request_kwargs: dict[str, object]) -> _LambResponse:
    payload = request_kwargs.get("json")
    assert isinstance(payload, dict)
    return _LambResponse({}, text=payload["model_name"])


class _LambClient:
    instances: list[_LambClient] = []

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.closed = False
        self.instances.append(self)

    def post(self, url: str, **kwargs: object) -> _LambResponse:
        self.requests.append({"url": url, **kwargs})
        if url.endswith("/add"):
            return _address_ack(kwargs)
        return _LambResponse({"status_byte": 160})

    def close(self) -> None:
        self.closed = True


def test_lamb_read_status_byte_uses_native_endpoint_payload_and_timeout(monkeypatch) -> None:
    _LambClient.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", _LambClient)
    backend = lamb_module.LambBackend(
        address="GPIB0::1::INSTR", url="http://lamb.test", timeout_ms=12_345
    )

    assert backend.read_status_byte() == 160
    add, request = _LambClient.instances[0].requests
    assert add["json"] == {"model_name": "GPIB0::1::INSTR"}
    assert request["url"] == "http://lamb.test/instrument/read_status_byte"
    assert request["json"] == {"resource_string": "GPIB0::1::INSTR", "timeout_ms": 12_345}
    assert request["timeout"] == 17.345


def test_lamb_read_status_byte_retries_missing_handle_with_reactivated_address(monkeypatch) -> None:
    class MissingThenActiveClient(_LambClient):
        def post(self, url: str, **kwargs: object) -> _LambResponse:
            self.requests.append({"url": url, **kwargs})
            if (
                url.endswith("/instrument/read_status_byte")
                and len(
                    [
                        request
                        for request in self.requests
                        if str(request["url"]).endswith("read_status_byte")
                    ]
                )
                == 1
            ):
                return _LambResponse({}, status_code=404, text="Instrument not found")
            if url.endswith("/add"):
                return _address_ack(kwargs)
            return _LambResponse({"status_byte": 3})

    _LambClient.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", MissingThenActiveClient)
    backend = lamb_module.LambBackend(
        address="USB::MODEL::SERIAL::INSTR",
        model_name="MODEL",
        serial_number="SERIAL",
        url="http://lamb.test",
    )

    assert backend.read_status_byte() == 3
    requests = _LambClient.instances[0].requests
    assert [request["url"] for request in requests] == [
        "http://lamb.test/instrument/read_status_byte",
        "http://lamb.test/add",
        "http://lamb.test/instrument/read_status_byte",
    ]
    assert requests[1]["json"] == {"model_name": "USB::MODEL::SERIAL::INSTR"}
    assert requests[2]["json"] == {
        "resource_string": "USB::MODEL::SERIAL::INSTR",
        "timeout_ms": 30_000,
    }


@pytest.mark.parametrize(
    "address",
    ["GPIB0::17::INSTR", "USB::VENDOR::PRODUCT::SERIAL::INSTR", "TCPIP0::scope::inst0::INSTR"],
)
def test_lamb_explicit_address_reactivation_registers_complete_uri(
    monkeypatch, address: str
) -> None:
    class DirectAddressClient(_LambClient):
        def post(self, url: str, **kwargs: object) -> _LambResponse:
            self.requests.append({"url": url, **kwargs})
            if url.endswith("/instrument/read_status_byte"):
                reads = [
                    request
                    for request in self.requests
                    if str(request["url"]).endswith("read_status_byte")
                ]
                if len(reads) == 1:
                    return _LambResponse({}, status_code=404, text="Instrument not found")
                return _LambResponse({"status_byte": 7})
            if url.endswith("/add"):
                return _address_ack(kwargs)
            raise AssertionError(f"unexpected URL: {url}")

    _LambClient.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", DirectAddressClient)
    backend = lamb_module.LambBackend(
        address=address,
        model_name="LEGACY-MODEL",
        serial_number="LEGACY-SERIAL",
        url="http://lamb.test",
    )

    assert backend.read_status_byte() == 7
    requests = _LambClient.instances[0].requests
    registrations = [
        request["json"] for request in requests if str(request["url"]).endswith("/add")
    ]
    expected_count = 2 if address.startswith("GPIB") else 1
    assert registrations == [{"model_name": address}] * expected_count
    assert requests[-1]["json"]["resource_string"] == address
    assert backend.instrument_address == address


def test_lamb_constructor_does_not_open_http_session(monkeypatch) -> None:
    _LambClient.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", _LambClient)

    lamb_module.LambBackend(address="GPIB0::1::INSTR", url="http://lamb.test")

    assert _LambClient.instances == []


@pytest.mark.parametrize("payload", [{}, {"status_byte": "160"}, {"status_byte": 256}, 160])
def test_lamb_read_status_byte_rejects_invalid_response(monkeypatch, payload: object) -> None:
    class InvalidResponseClient(_LambClient):
        def post(self, url: str, **kwargs: object) -> _LambResponse:
            self.requests.append({"url": url, **kwargs})
            if url.endswith("/add"):
                return _address_ack(kwargs)
            return _LambResponse(payload)

    _LambClient.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", InvalidResponseClient)
    backend = lamb_module.LambBackend(address="GPIB0::1::INSTR", url="http://lamb.test")

    with pytest.raises(InstrumentCommunicationError, match="status_byte"):
        backend.read_status_byte()


def test_visa_read_status_byte_delegates_to_native_read_stb(monkeypatch) -> None:
    class FakeResource:
        def __init__(self) -> None:
            self.read_stb_calls = 0
            self.timeout = None

        def read_stb(self) -> int:
            self.read_stb_calls += 1
            return 32

        def close(self) -> None:
            return None

    resource = FakeResource()
    backend = VisaBackend.__new__(VisaBackend)
    backend.address = "GPIB0::1::INSTR"
    backend.instrument = resource

    assert backend.read_status_byte() == 32
    assert resource.read_stb_calls == 1


def test_visa_read_status_byte_fails_before_connection() -> None:
    backend = VisaBackend.__new__(VisaBackend)
    backend.address = "GPIB0::1::INSTR"
    backend.instrument = None

    with pytest.raises(InstrumentConnectionError, match="Not connected"):
        backend.read_status_byte()


def test_lamb_read_termination_is_lazy_and_query_only(monkeypatch) -> None:
    _LambClient.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", _LambClient)
    backend = lamb_module.LambBackend(address="USB::VENDOR::PRODUCT::SERIAL::INSTR")

    backend.set_read_termination("\r\n")

    assert (
        backend._instrument_payload("READ?", include_read_termination=True)["read_termination"]
        == 10
    )
    assert "read_termination" not in backend._instrument_payload("READ?")
    assert "read_termination" not in backend._status_byte_payload()
    assert _LambClient.instances == []

    assert backend.query("READ?") == ""
    request = _LambClient.instances[0].requests[0]
    assert request["json"]["read_termination"] == 10


@pytest.mark.parametrize("value", [123, "\u20ac"])
def test_read_termination_rejects_nonstring_or_multibyte_final_character(value: object) -> None:
    backend = lamb_module.LambBackend(address="USB::VENDOR::PRODUCT::SERIAL::INSTR")

    with pytest.raises((TypeError, ValueError)):
        backend.set_read_termination(value)  # type: ignore[arg-type]


def test_read_termination_none_or_empty_disables_lamb_eos() -> None:
    backend = lamb_module.LambBackend(address="USB::VENDOR::PRODUCT::SERIAL::INSTR")

    backend.set_read_termination("\n")
    backend.set_read_termination("")
    assert backend._read_termination is None
    assert (
        backend._instrument_payload("READ?", include_read_termination=True)["read_termination"]
        is None
    )

    backend.set_read_termination(None)
    assert backend._read_termination is None


class _VisaResource:
    def __init__(self, raw: bytes = b"A\nB") -> None:
        self.timeout = None
        self.chunk_size = 4096
        self.writes: list[str] = []
        self.read_raw_terminations: list[str | None] = []
        self._termination = None
        self.raw = raw

    @property
    def read_termination(self):
        return self._termination

    @read_termination.setter
    def read_termination(self, value):
        self._termination = value

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def read_raw(self) -> bytes:
        self.read_raw_terminations.append(self.read_termination)
        return self.raw

    def close(self) -> None:
        return None


def test_visa_read_termination_applies_on_connect_and_current_resource(monkeypatch) -> None:
    resource = _VisaResource()
    monkeypatch.setattr(visa_module.pyvisa.resources, "MessageBasedResource", _VisaResource)
    backend = VisaBackend.__new__(VisaBackend)
    backend.address = "GPIB0::1::INSTR"
    backend.rm = type("Manager", (), {"open_resource": lambda self, address: resource})()
    backend.instrument = None
    backend._timeout_ms = 5000
    backend._read_termination = None
    backend._write_termination = None

    backend.set_read_termination("\r\n")
    assert resource.read_termination is None
    backend.connect()
    assert resource.read_termination == "\r\n"

    backend.set_read_termination("")
    assert resource.read_termination == ""


def test_visa_query_raw_is_not_clipped_by_text_termination() -> None:
    resource = _VisaResource()
    backend = VisaBackend.__new__(VisaBackend)
    backend.address = "GPIB0::1::INSTR"
    backend.instrument = resource
    backend._read_termination = None
    backend._write_termination = None

    backend.set_read_termination("\n")

    assert backend.query_raw("BIN?") == b"A\nB"
    assert resource.read_termination == "\n"
    assert resource.read_raw_terminations == [None]
