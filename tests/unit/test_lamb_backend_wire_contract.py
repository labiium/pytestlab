from __future__ import annotations

from typing import Any

import pytest

from pytestlab.instruments.backends.lamb import LambBackend


class FakeResponse:
    def __init__(self, content: bytes = b"", status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.text = content.decode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP status {self.status_code}")


class FakeClient:
    requests: list[dict[str, Any]] = []
    responses: list[FakeResponse] = []

    def __init__(self, **_: Any):
        pass

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        return self.responses.pop(0)


@pytest.mark.parametrize("address", ["GPIB0::23::INSTR", "GPIB0::23::4::INSTR"])
def test_explicit_gpib_registers_through_add_and_uses_resource_string(
    monkeypatch: Any, address: str
) -> None:
    FakeClient.requests = []
    FakeClient.responses = [FakeResponse(address.encode()), FakeResponse(b"Acme,Model,123,1")]
    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", FakeClient)

    backend = LambBackend(
        address=address,
        url="http://lamb-server:8000",
        model_name="ignored-model",
        serial_number="ignored-serial",
    )
    assert backend.query("*IDN?") == "Acme,Model,123,1"

    add_request, query_request = FakeClient.requests
    assert add_request["url"] == "http://lamb-server:8000/add"
    assert add_request["json"] == {"model_name": address}
    assert query_request["json"] == {
        "resource_string": address,
        "command": "*IDN?",
    }


def test_write_and_raw_query_use_resource_string(monkeypatch: Any) -> None:
    FakeClient.requests = []
    FakeClient.responses = [FakeResponse(), FakeResponse(b"\x01\x02")]
    monkeypatch.setattr("pytestlab.instruments.backends.lamb.httpx.Client", FakeClient)

    backend = LambBackend(address="USB0::0x1234::0x5678::SERIAL::INSTR")
    backend.write("*IDN?")
    assert backend.query_raw("*IDN?") == b"\x01\x02"

    assert [request["json"]["resource_string"] for request in FakeClient.requests] == [
        "USB0::0x1234::0x5678::SERIAL::INSTR",
        "USB0::0x1234::0x5678::SERIAL::INSTR",
    ]
    assert all("visa_string" not in request["json"] for request in FakeClient.requests)
