import json

import httpx
import pytest

from pytestlab.config import DeviceConfig
from pytestlab.config import PowerSupplyConfig
from pytestlab.devices.base import Device
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.instruments.backends.lamb import LambBackend
from pytestlab.instruments.command_attribution import describe_emitter
from pytestlab.instruments.PowerSupply import PowerSupply


class FakeResponse:
    status_code = 200
    content = b"ok"
    text = "ok"

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [FakeResponse()])
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _opt_in_tim_attribution(monkeypatch):
    monkeypatch.setenv("PYTESTLAB_TIM_ATTRIBUTION", "1")


def backend_with(client):
    backend = LambBackend(address="USB::1")
    backend._client = client
    return backend


def test_direct_backend_call_is_attributed_and_keeps_metadata_on_retry():
    missing = FakeResponse()
    missing.status_code = 404
    missing.text = "instrument not found"
    client = FakeClient([missing, FakeResponse()])
    backend = backend_with(client)
    backend._reactivate_after_missing_handle = lambda: True

    backend.query("*IDN?")

    assert len(client.requests) == 2
    first = json.loads(client.requests[0][1]["headers"]["X-TIM-Emitter"])
    second = json.loads(client.requests[1][1]["headers"]["X-TIM-Emitter"])
    assert first == second
    assert first["kind"] == "agent_raw_scpi"
    assert first["basis"] == "python_call_stack"


def test_native_low_level_query_is_attributed_to_sdk_boundary():
    backend = backend_with(FakeClient())
    config = PowerSupplyConfig(manufacturer="test", model="test", role="stimulus", channels=[])
    psu = PowerSupply(config, backend=backend)

    psu._error_check = lambda: None
    psu._query("*IDN?")

    emitter = json.loads(backend._client.requests[0][1]["headers"]["X-TIM-Emitter"])
    assert emitter["kind"] == "pytestlab_native_method"
    assert emitter["method"] == "Instrument._query"
    assert emitter["classification_complete"] is True


def test_device_query_is_attributed_as_raw_scpi():
    client = FakeClient()
    device = Device(
        DeviceConfig(manufacturer="test", model="device", device_type="generic", role="custom"),
        backend=backend_with(client),
    )

    device.query("MEAS?")

    emitter = json.loads(client.requests[0][1]["headers"]["X-TIM-Emitter"])
    assert emitter["kind"] == "agent_raw_scpi"
    assert emitter["method"] == "Device.query"


def test_http_failure_still_carries_emitter():
    response = FakeResponse()
    response.status_code = 500
    response.raise_for_status = lambda: (_ for _ in ()).throw(
        httpx.HTTPStatusError(
            "failure",
            request=httpx.Request("POST", "http://x"),
            response=httpx.Response(500, text="failure"),
        )
    )
    backend = backend_with(FakeClient([response]))

    with pytest.raises(InstrumentCommunicationError):
        backend.query("*IDN?")

    assert "X-TIM-Emitter" in backend._client.requests[0][1]["headers"]


def test_attribution_failure_falls_back_without_changing_io(monkeypatch):
    import pytestlab.instruments.backends.lamb as lamb

    client = FakeClient()
    backend = backend_with(client)
    monkeypatch.setattr(
        lamb, "describe_emitter", lambda: (_ for _ in ()).throw(RuntimeError("broken"))
    )

    assert backend.query("SYST:ERR?") == "ok"
    headers = client.requests[0][1]["headers"]
    metadata = json.loads(headers["X-TIM-Emitter"])
    assert metadata["kind"] == "transport"
    assert metadata["classification_complete"] is False
    assert metadata["instrumentation_error"] == "RuntimeError"
    assert metadata["callsite"]["file"].endswith("lamb.py")
    assert client.requests[0][1]["json"]["command"] == "SYST:ERR?"


def test_describe_emitter_returns_no_frame_objects():
    metadata = describe_emitter()
    assert set(metadata) >= {"schema_version", "kind", "method", "callsite", "basis", "transport"}
    assert all(not hasattr(value, "f_back") for value in metadata.values())
