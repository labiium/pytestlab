from __future__ import annotations

from datetime import UTC

import httpx
import pytest

from pytestlab.camera import Camera
from pytestlab.camera import Frame
from pytestlab.config.device_config import DeviceConfig
from pytestlab.devices import AutoDevice
from pytestlab.devices.registry import BackendBuildContext
from pytestlab.errors import InstrumentConnectionError
from pytestlab.instruments.backends.lamb_camera import LambCameraBackend
from pytestlab.instruments.backends.lamb_camera import build_lamb_camera_backend

CAMERA_ID = "toupcam:native-e3cmos12000kpa-0547-4002"
BASE_URL = "http://lamb.test:8000"
JPEG = b"\xff\xd8test-jpeg\xff\xd9"


class HttpClient:
    def __init__(self, **kwargs):
        self.timeout = kwargs["timeout"]
        self.closed = False
        self.calls = []

    def get(self, url):
        self.calls.append(("GET", url, None))
        return httpx.Response(
            200,
            json={"devices": [{"resource_string": CAMERA_ID}]},
            request=httpx.Request("GET", url),
        )

    def post(self, url, *, params):
        self.calls.append(("POST", url, params))
        return httpx.Response(
            200,
            content=JPEG,
            headers={"content-type": "image/jpeg"},
            request=httpx.Request("POST", url),
        )

    def close(self):
        self.closed = True


def make_backend(monkeypatch, client_type=HttpClient):
    clients = []

    def make_client(**kwargs):
        client = client_type(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("pytestlab.instruments.backends.lamb_camera.httpx.Client", make_client)
    return LambCameraBackend(BASE_URL, CAMERA_ID, 2_500), clients


def test_camera_discovery_capture_and_reconnect(monkeypatch):
    backend, clients = make_backend(monkeypatch)
    camera = Camera(
        DeviceConfig(
            manufacturer="ToupTek", model="E3CMOS12000KPA", device_type="camera", role="measurement"
        ),
        backend,
    )

    frame = camera.capture(width=1024, height=540)
    assert isinstance(frame, Frame)
    assert frame.data == JPEG
    assert frame.content_type == "image/jpeg"
    assert frame.width is None and frame.height is None
    assert frame.metadata == {"timestamp_source": "client_response_received"}
    assert frame.captured_at.tzinfo == UTC
    assert clients[0].timeout == 2.5
    method, url, params = clients[0].calls[1]
    assert method == "POST"
    assert url == f"{BASE_URL}/webcams/toupcam%3Anative-e3cmos12000kpa-0547-4002/capture"
    assert params == {"format": "jpeg", "width": 1024, "height": 540}

    camera.close()
    assert clients[0].closed
    camera.capture()
    assert len(clients) == 2
    camera.close()


@pytest.mark.parametrize("bad_dimension", [True, False, 0, -1, 1.5, "640"])
@pytest.mark.parametrize("name", ["width", "height"])
def test_invalid_dimensions_fail_before_connect_or_http(monkeypatch, name, bad_dimension):
    backend, clients = make_backend(monkeypatch)
    camera = Camera(
        DeviceConfig(
            manufacturer="ToupTek", model="E3CMOS12000KPA", device_type="camera", role="measurement"
        ),
        backend,
    )
    with pytest.raises(ValueError, match=name):
        camera.capture(**{name: bad_dimension})
    assert clients == []


@pytest.mark.parametrize("entrypoint", ["capture_to", "capture_many"])
def test_invalid_dimensions_fail_before_network_for_file_captures(
    monkeypatch, tmp_path, entrypoint
):
    backend, clients = make_backend(monkeypatch)
    camera = Camera(
        DeviceConfig(
            manufacturer="ToupTek",
            model="E3CMOS12000KPA",
            device_type="camera",
            role="measurement",
        ),
        backend,
    )
    with pytest.raises(ValueError, match="width"):
        if entrypoint == "capture_to":
            camera.capture_to(tmp_path / "bad.jpg", width=True)
        else:
            camera.capture_many([tmp_path / "bad.jpg"], width=True)
    assert clients == []


@pytest.mark.parametrize(
    "resources",
    [
        (),
        ("CAMERA::A",),
        ("CAMERA::A", "CAMERA::B"),
        (CAMERA_ID, CAMERA_ID),
    ],
)
def test_configured_camera_requires_exact_unique_inventory_match_and_closes_client(
    monkeypatch, resources
):
    class Discovery(HttpClient):
        def get(self, url):
            self.calls.append(("GET", url, None))
            return httpx.Response(
                200,
                json={"devices": [{"resource_string": resource} for resource in resources]},
                request=httpx.Request("GET", url),
            )

    backend, clients = make_backend(monkeypatch, Discovery)
    with pytest.raises(ValueError, match=CAMERA_ID):
        backend.connect()
    assert len(clients) == 1 and clients[0].closed
    assert clients[0].calls == [("GET", f"{BASE_URL}/webcams", None)]
    assert backend._client is None
    assert backend.resource_string == CAMERA_ID


@pytest.mark.parametrize(
    "status,headers,body,exception",
    [
        (503, {"content-type": "application/json"}, b"offline", httpx.HTTPStatusError),
        (200, {"content-type": "image/png"}, b"png", ValueError),
        (200, {"content-type": "image/jpeg"}, b"", ValueError),
    ],
)
def test_capture_rejects_http_errors_and_invalid_images(
    monkeypatch, status, headers, body, exception
):
    class InvalidCapture(HttpClient):
        def post(self, url, *, params):
            return httpx.Response(
                status,
                content=body,
                headers=headers,
                request=httpx.Request("POST", url),
            )

    backend, _ = make_backend(monkeypatch, InvalidCapture)
    backend.connect()
    with pytest.raises(exception):
        backend.capture()
    backend.close()


def test_factory_selects_builtin_camera_profile_and_lamb_backend(monkeypatch):
    _, clients = make_backend(monkeypatch)
    camera = AutoDevice.from_preset(
        "touptek/E3CMOS12000KPA",
        backend_type_hint="lamb",
        backend_spec_override={
            "type": "lamb",
            "url": BASE_URL,
            "resource_string": CAMERA_ID,
        },
    )
    assert isinstance(camera, Camera)
    assert camera.get_capabilities().formats == ("image/jpeg",)
    assert not camera.get_capabilities().supports_stream
    assert camera.capture().data == JPEG
    assert clients[0].calls[0][0] == "GET"
    camera.close()


@pytest.mark.parametrize("resource", [None, "", "  ", 0, False])
def test_missing_or_invalid_resource_fails_before_client_allocation(monkeypatch, resource):
    def forbidden(**_kwargs):
        pytest.fail("invalid resource must not allocate an HTTP client")

    monkeypatch.setattr("pytestlab.instruments.backends.lamb_camera.httpx.Client", forbidden)
    with pytest.raises(ValueError, match="requires an explicit nonempty address"):
        LambCameraBackend(BASE_URL, resource, 2_500)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_factory_does_not_discover_when_address_is_unset(monkeypatch, count):
    clients = []

    class Inventory(HttpClient):
        def get(self, url):
            return httpx.Response(
                200,
                json={"devices": [{"resource_string": f"CAMERA::{i}"} for i in range(count)]},
                request=httpx.Request("GET", url),
            )

    def make_client(**kwargs):
        clients.append(Inventory(**kwargs))
        return clients[-1]

    monkeypatch.setattr("pytestlab.instruments.backends.lamb_camera.httpx.Client", make_client)
    camera = AutoDevice.from_preset(
        "touptek/E3CMOS12000KPA",
        backend_spec_override={"type": "lamb", "url": BASE_URL},
    )
    with pytest.raises(ValueError, match="requires an explicit nonempty address"):
        camera.capture()
    camera.close()
    assert clients == []


def test_configured_camera_is_unchanged_with_other_attached_cameras(monkeypatch):
    class Inventory(HttpClient):
        def get(self, url):
            self.calls.append(("GET", url, None))
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {"resource_string": "CAMERA::A"},
                        {"resource_string": CAMERA_ID},
                        {"resource_string": "CAMERA::B"},
                    ],
                },
                request=httpx.Request("GET", url),
            )

    backend, clients = make_backend(monkeypatch, Inventory)
    for _ in range(2):
        backend.connect()
        assert backend.resource_string == CAMERA_ID
        with pytest.raises(AttributeError):
            backend.resource_string = "CAMERA::B"
        assert backend.capture().data == JPEG
        backend.close()
    assert len(clients) == 2 and all(client.closed for client in clients)
    for client in clients:
        assert client.calls[1][1] == (
            f"{BASE_URL}/webcams/toupcam%3Anative-e3cmos12000kpa-0547-4002/capture"
        )


@pytest.mark.parametrize(
    ("address_override", "spec", "error"),
    [
        (CAMERA_ID, {}, None),
        (CAMERA_ID, {"resource_string": CAMERA_ID}, None),
        (CAMERA_ID, {"resource_string": "CAMERA::other"}, "Conflicting camera address"),
        (None, {"camera_id": CAMERA_ID}, "not camera_id/camera_label"),
        (None, {"camera_label": CAMERA_ID}, "not camera_id/camera_label"),
    ],
)
def test_explicit_resource_aliases_conflicts_and_legacy_fields(
    monkeypatch, address_override, spec, error
):
    _, clients = make_backend(monkeypatch)

    def build():
        return AutoDevice.from_preset(
            "touptek/E3CMOS12000KPA",
            address_override=address_override,
            backend_spec_override={"type": "lamb", "url": BASE_URL, **spec},
        )

    camera = build()
    if error:
        with pytest.raises(ValueError, match=error):
            camera.capture()
        assert clients == []
    else:
        assert camera.capture().data == JPEG
    camera.close()
    if not error:
        assert clients[0].closed


@pytest.mark.parametrize("address", [None, CAMERA_ID])
def test_profile_free_bench_camera_needs_explicit_resource(monkeypatch, tmp_path, address):
    from pytestlab.bench import Bench

    _, clients = make_backend(monkeypatch)
    path = tmp_path / "bench.yaml"
    path.write_text(
        "bench_name: camera\nsimulate: false\ndevices:\n  camera:\n    device_type: camera\n"
        + (f"    address: {address}\n" if address is not None else "")
        + f"    backend:\n      type: lamb\n      url: {BASE_URL}\n"
    )
    if address is None:
        with pytest.raises(
            InstrumentConnectionError, match="requires an explicit nonempty address"
        ):
            Bench.open(path)
        assert clients == []
    else:
        with Bench.open(path) as bench:
            assert bench.camera.capture().data == JPEG
        assert clients[0].closed


def test_inline_camera_cannot_override_instrument_profile():
    from pytestlab.config.bench_config import DeviceEntry

    with pytest.raises(ValueError, match="cannot be combined"):
        DeviceEntry(device_type="camera", profile="keysight/DSOX1204G")


@pytest.mark.parametrize(
    "explicit,profile,env,expected",
    [
        ("http://override:8000", "http://profile:8000", "http://env:8000", "http://override:8000"),
        (None, "http://profile:8000", "http://env:8000", "http://profile:8000"),
        (None, None, "http://env:8000", "http://env:8000"),
        (None, None, None, "http://lamb-server:8000"),
        ("", "", "http://env:8000", "http://env:8000"),
    ],
)
def test_camera_url_matches_instrument_lamb_precedence(
    monkeypatch, explicit, profile, env, expected
):
    from pytestlab.devices.registry import _build_lamb_backend

    monkeypatch.delenv("LAMB_SERVER", raising=False)
    if env is not None:
        monkeypatch.setenv("LAMB_SERVER", env)
    config = DeviceConfig(
        manufacturer="ugreen",
        model="camera",
        device_type="camera",
        role="measurement",
        lamb_url=profile,
    )
    context = BackendBuildContext(
        config=config,
        config_source="test",
        address=None,
        timeout_ms=1000,
        simulate=False,
        backend_type="lamb",
        backend_spec={"url": explicit, "resource_string": CAMERA_ID},
    )
    backend = build_lamb_camera_backend(context)
    assert backend.url == expected
    # Same precedence as the existing instrument backend; no connection opened.
    instrument_config = config.model_copy(update={"device_type": "oscilloscope"})
    from dataclasses import replace

    instrument = _build_lamb_backend(replace(context, config=instrument_config))
    assert instrument.base_url == expected
    camera = _build_lamb_backend(context)
    assert isinstance(camera, LambCameraBackend)
    assert camera.url == expected
