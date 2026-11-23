from __future__ import annotations

from pytestlab.instruments.backends import lamb as lamb_module


class Response:
    status_code = 200
    text = "+1.25"
    content = b"+1.25"

    def json(self):
        return {"native_read": True}

    def raise_for_status(self) -> None:
        return None


class Client:
    instances: list[Client] = []

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.closed = False
        self.instances.append(self)

    def get(self, url: str, **kwargs: object) -> Response:
        self.requests.append((url, kwargs))
        return Response()

    def post(self, url: str, **kwargs: object) -> Response:
        self.requests.append((url, kwargs))
        response = Response()
        if url.endswith("/add"):
            payload = kwargs.get("json")
            assert isinstance(payload, dict)
            response.text = payload["model_name"]
        return response

    def close(self) -> None:
        self.closed = True


def prepare(monkeypatch):
    Client.instances.clear()
    monkeypatch.setattr(lamb_module.httpx, "Client", Client)


def test_close_without_remote_resource_does_not_create_client(monkeypatch):
    prepare(monkeypatch)
    backend = lamb_module.LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")

    backend.close()

    assert Client.instances == []
    assert backend.instrument_address is None
    assert backend._explicit_address == "GPIB0::12::INSTR"


def test_capability_request_does_not_make_close_release_a_resource(monkeypatch):
    prepare(monkeypatch)
    backend = lamb_module.LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")

    backend._ensure_server_capability("native_read")
    backend.close()

    client = Client.instances[0]
    assert [url for url, _ in client.requests] == ["http://lamb.test/capabilities"]
    assert client.closed


def test_used_explicit_resource_is_closed(monkeypatch):
    prepare(monkeypatch)
    backend = lamb_module.LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")

    backend.query("READ?")
    backend.close()

    client = Client.instances[0]
    assert [url for url, _ in client.requests] == [
        "http://lamb.test/add",
        "http://lamb.test/instrument/query",
        "http://lamb.test/instrument/close",
    ]
    assert client.requests[-1][1]["json"] == {
        "resource_string": "GPIB0::12::INSTR",
        "command": "",
    }
    assert client.closed
    assert backend._explicit_address == "GPIB0::12::INSTR"
    assert not backend._resource_acquired


def test_close_after_disconnect_still_releases_used_resource(monkeypatch):
    prepare(monkeypatch)
    backend = lamb_module.LambBackend(address="GPIB0::12::INSTR", url="http://lamb.test")

    backend.query("READ?")
    backend.disconnect()
    backend.close()

    assert len(Client.instances) == 2
    assert [url for url, _ in Client.instances[0].requests] == [
        "http://lamb.test/add",
        "http://lamb.test/instrument/query",
    ]
    assert [url for url, _ in Client.instances[1].requests] == ["http://lamb.test/instrument/close"]
    assert all(client.closed for client in Client.instances)
