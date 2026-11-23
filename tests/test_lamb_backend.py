from __future__ import annotations

from types import SimpleNamespace

import pytest

from pytestlab.devices.registry import BackendBuildContext
from pytestlab.devices.registry import _build_lamb_backend
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.instruments.backends import lamb as lamb_module


class _Response:
    status_code = 200
    text = "SIM::PSU"
    content = b"1.25\n"

    def __init__(self, text: str | None = None) -> None:
        if text is not None:
            self.text = text

    def raise_for_status(self) -> None:
        return None


def _response_for(url: str, kwargs: dict[str, object]) -> _Response:
    payload = kwargs.get("json")
    if url.endswith("/add") and isinstance(payload, dict):
        identity = payload.get("model_name")
        if isinstance(identity, str) and "::" in identity:
            return _Response(identity)
    return _Response()


class _Client:
    instances: list[_Client] = []

    def __init__(self) -> None:
        self.closed = False
        self.requests: list[dict[str, object]] = []
        self.instances.append(self)

    def post(self, url: str, **kwargs: object) -> _Response:
        self.requests.append({"url": url, **kwargs})
        return _response_for(url, kwargs)

    def get(self, url: str, **kwargs: object) -> _Response:
        self.requests.append({"url": url, **kwargs})
        return _Response()

    def close(self) -> None:
        self.closed = True


def test_lamb_backend_reuses_http_session_until_disconnect(monkeypatch) -> None:
    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", _Client)
    backend = lamb_module.LambBackend(address="SIM::PSU", url="http://lamb.test", timeout_ms=2500)

    assert backend.query("VOLT?") == "1.25"
    backend.write("OUTP ON")
    assert backend.query_raw("WAV?") == b"1.25\n"

    assert len(_Client.instances) == 1
    assert [request["timeout"] for request in _Client.instances[0].requests] == [
        7.5,
        7.5,
        7.5,
    ]
    assert all(
        "write_termination" not in request.get("json", {})
        for request in _Client.instances[0].requests
    )

    backend.disconnect()
    assert _Client.instances[0].closed is True
    assert backend.query("VOLT?") == "1.25"
    assert len(_Client.instances) == 2


def test_close_releases_managed_session_and_reconnects_by_model(monkeypatch) -> None:
    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", _Client)
    backend = lamb_module.LambBackend(
        model_name="EDU34450A",
        serial_number="SIMDMM",
        url="http://lamb.test",
    )

    backend.connect()
    assert backend.instrument_address == "SIM::PSU"
    backend.close()
    assert backend.instrument_address is None
    assert _Client.instances[0].requests[-1]["url"] == ("http://lamb.test/instrument/close")
    assert _Client.instances[0].requests[-1]["json"] == {
        "resource_string": "SIM::PSU",
        "command": "",
    }

    backend.connect()
    assert backend.instrument_address == "SIM::PSU"
    assert len(_Client.instances) == 2


def test_explicit_address_backend_retains_identity_for_reactivation() -> None:
    backend = _build_lamb_backend(
        BackendBuildContext(
            config=SimpleNamespace(
                model="EDU34450A",
                serial_number="SIMDMM",
                lamb_url="http://lamb.test",
            ),
            config_source="test",
            address="USB::EDU34450A::SIMDMM::INSTR",
            timeout_ms=5000,
            simulate=False,
            backend_type="lamb",
        )
    )

    assert isinstance(backend, lamb_module.LambBackend)
    assert backend.instrument_address == "USB::EDU34450A::SIMDMM::INSTR"
    assert backend.model_name == "EDU34450A"
    assert backend.serial_number == "SIMDMM"


def test_query_reactivates_explicit_resource_after_lamb_404(monkeypatch) -> None:
    class MissingThenActiveClient(_Client):
        def __init__(self) -> None:
            super().__init__()
            self.query_count = 0

        def post(self, url: str, **kwargs: object) -> _Response:
            self.requests.append({"url": url, **kwargs})
            if url.endswith("/instrument/query"):
                self.query_count += 1
                if self.query_count == 1:
                    return SimpleNamespace(
                        status_code=404,
                        text="Instrument not found",
                        content=b"Instrument not found",
                    )
            return _response_for(url, kwargs)

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", MissingThenActiveClient)
    backend = lamb_module.LambBackend(
        address="USB::EDU34450A::SIMDMM::INSTR",
        model_name="EDU34450A",
        serial_number="SIMDMM",
        url="http://lamb.test",
    )

    assert backend.query("READ?") == "1.25"
    client = _Client.instances[0]
    assert [request["url"] for request in client.requests] == [
        "http://lamb.test/instrument/query",
        "http://lamb.test/add",
        "http://lamb.test/instrument/query",
    ]
    assert client.requests[1]["json"] == {"model_name": "USB::EDU34450A::SIMDMM::INSTR"}
    assert backend.instrument_address == "USB::EDU34450A::SIMDMM::INSTR"


def test_query_retries_only_the_explicit_resource_after_missing_handle(monkeypatch) -> None:
    class MissingHandleResponse:
        status_code = 404
        text = "Instrument not found"
        content = b"Instrument not found"

        def raise_for_status(self) -> None:
            raise lamb_module.httpx.HTTPStatusError(
                "instrument missing",
                request=lamb_module.httpx.Request("POST", "http://lamb.test/instrument/query"),
                response=lamb_module.httpx.Response(404),
            )

    class MissingHandleClient(_Client):
        def post(self, url: str, **kwargs: object) -> MissingHandleResponse | _Response:
            self.requests.append({"url": url, **kwargs})
            if url.endswith("/instrument/query"):
                return MissingHandleResponse()
            return _response_for(url, kwargs)

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", MissingHandleClient)
    backend = lamb_module.LambBackend(
        address="USB::EDU34450A::UNKNOWN::INSTR",
        model_name="EDU34450A",
        url="http://lamb.test",
    )

    with pytest.raises(InstrumentCommunicationError):
        backend.query("READ?")

    assert [request["url"] for request in _Client.instances[0].requests] == [
        "http://lamb.test/instrument/query",
        "http://lamb.test/add",
        "http://lamb.test/instrument/query",
    ]
    assert _Client.instances[0].requests[1]["json"] == {
        "model_name": "USB::EDU34450A::UNKNOWN::INSTR"
    }
    assert backend.instrument_address == "USB::EDU34450A::UNKNOWN::INSTR"


def test_non_handle_404_is_not_retried(monkeypatch) -> None:
    class RouteMissingResponse:
        status_code = 404
        text = "Route not found"
        content = b"Route not found"

        def raise_for_status(self) -> None:
            raise lamb_module.httpx.HTTPStatusError(
                "route missing",
                request=lamb_module.httpx.Request("POST", "http://lamb.test/instrument/query"),
                response=lamb_module.httpx.Response(404),
            )

    class RouteMissingClient(_Client):
        def post(self, url: str, **kwargs: object) -> RouteMissingResponse | _Response:
            self.requests.append({"url": url, **kwargs})
            if url.endswith("/instrument/query"):
                return RouteMissingResponse()
            return _Response()

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", RouteMissingClient)
    backend = lamb_module.LambBackend(
        model_name="EDU34450A",
        serial_number="SIMDMM",
        url="http://lamb.test",
    )

    with pytest.raises(InstrumentCommunicationError):
        backend.query("READ?")

    assert [request["url"] for request in _Client.instances[0].requests] == [
        "http://lamb.test/add",
        "http://lamb.test/instrument/query",
    ]


def test_write_termination_is_in_command_operations_and_survives_retry(monkeypatch) -> None:
    class CapabilityResponse(_Response):
        def json(self) -> dict[str, bool]:
            return {"write_termination": True, "native_read": True}

    class RetryClient(_Client):
        def __init__(self) -> None:
            super().__init__()
            self.queried = False

        def get(self, url: str, **kwargs: object) -> CapabilityResponse:
            self.requests.append({"url": url, **kwargs})
            return CapabilityResponse()

        def post(self, url: str, **kwargs: object) -> _Response:
            self.requests.append({"url": url, **kwargs})
            if url.endswith("/instrument/query_raw") and not self.queried:
                self.queried = True
                return SimpleNamespace(
                    status_code=404,
                    text="Instrument not found",
                    content=b"Instrument not found",
                )
            return _response_for(url, kwargs)

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", RetryClient)
    backend = lamb_module.LambBackend(
        address="USB::DMM::INSTR", model_name="DMM", url="http://lamb.test"
    )
    backend.set_write_termination("\r\n")
    backend.write("CONF:VOLT")
    assert backend.query_raw("DATA?") == b"1.25\n"
    backend.read_raw()

    client = _Client.instances[0]
    command_requests = [
        request
        for request in client.requests
        if request["url"].endswith(
            ("/instrument/write", "/instrument/query_raw", "/instrument/read_raw")
        )
    ]
    assert [request["json"].get("write_termination") for request in command_requests] == [
        "\r\n",
        "\r\n",
        "\r\n",
        None,
    ]
    assert [request["json"].get("command") for request in command_requests] == [
        "CONF:VOLT",
        "DATA?",
        "DATA?",
        None,
    ]


def test_explicit_eoi_framing_is_sent_as_empty_string(monkeypatch) -> None:
    class CapabilityResponse(_Response):
        def json(self) -> dict[str, bool]:
            return {"write_termination": True}

    class CapabilityClient(_Client):
        def get(self, url: str, **kwargs: object) -> CapabilityResponse:
            self.requests.append({"url": url, **kwargs})
            return CapabilityResponse()

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", CapabilityClient)
    backend = lamb_module.LambBackend(address="SIM::PSU", url="http://lamb.test")
    backend.set_write_termination(None)
    backend.write("*CLS")

    write_request = _Client.instances[0].requests[-1]
    assert write_request["json"]["write_termination"] == ""


def test_write_termination_requires_server_capability_before_activation(monkeypatch) -> None:
    class OldServerResponse(_Response):
        def json(self) -> dict[str, bool]:
            return {"native_read": True}

    class OldServerClient(_Client):
        def get(self, url: str, **kwargs: object) -> OldServerResponse:
            self.requests.append({"url": url, **kwargs})
            return OldServerResponse()

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", OldServerClient)
    backend = lamb_module.LambBackend(model_name="DMM", url="http://lamb.test")
    with pytest.raises(InstrumentCommunicationError, match="write_termination"):
        backend.set_write_termination("\n")

    assert [request["url"] for request in _Client.instances[0].requests] == [
        "http://lamb.test/capabilities"
    ]


@pytest.mark.parametrize("value", ["x", "\n\r", "\x00", 1, True])
def test_write_termination_rejects_invalid_values_before_capability_request(
    monkeypatch, value
) -> None:
    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", _Client)
    backend = lamb_module.LambBackend(address="SIM::PSU", url="http://lamb.test")
    with pytest.raises((TypeError, ValueError)):
        backend.set_write_termination(value)
    assert _Client.instances == []


def test_reconnect_rechecks_required_framing_before_any_instrument_request(monkeypatch) -> None:
    class CapabilityResponse(_Response):
        def __init__(self, supported: bool) -> None:
            self.supported = supported

        def json(self) -> dict[str, bool]:
            return {"write_termination": self.supported}

    class ChangingServerClient(_Client):
        def get(self, url: str, **kwargs: object) -> CapabilityResponse:
            self.requests.append({"url": url, **kwargs})
            return CapabilityResponse(len(_Client.instances) == 1)

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", ChangingServerClient)
    backend = lamb_module.LambBackend(address="GPIB0::1::INSTR", url="http://lamb.test")
    backend.set_write_termination(None)
    backend.disconnect()
    with pytest.raises(InstrumentCommunicationError, match="write_termination"):
        backend.query("31")
    assert backend._write_termination == ""
    assert [request["url"] for request in _Client.instances[1].requests] == [
        "http://lamb.test/capabilities"
    ]


@pytest.mark.parametrize("required", ["native_read", "query_delay_ms", "resource_timing_policy"])
def test_reconnect_rechecks_all_required_native_features(monkeypatch, required: str) -> None:
    class CapabilityResponse(_Response):
        def json(self) -> dict[str, bool]:
            if len(_Client.instances) > 1:
                return {}
            return {"native_read": True, "query_delay_ms": True, "resource_timing_policy": True}

    class ChangingServerClient(_Client):
        def get(self, url: str, **kwargs: object) -> CapabilityResponse:
            self.requests.append({"url": url, **kwargs})
            return CapabilityResponse()

    _Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", ChangingServerClient)
    backend = lamb_module.LambBackend(address="GPIB0::1::INSTR", url="http://lamb.test")
    backend.prepare_read()
    if required == "resource_timing_policy":
        backend.set_min_command_interval(0.1)
    backend.disconnect()
    with pytest.raises(InstrumentCommunicationError, match=required):
        if required == "native_read":
            backend.read()
        elif required == "query_delay_ms":
            backend.query("31", delay=0.1)
        else:
            backend.query("31")
    assert [request["url"] for request in _Client.instances[1].requests] == [
        "http://lamb.test/capabilities"
    ]
