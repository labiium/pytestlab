from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytestlab.camera import Camera
from pytestlab.camera import CaptureResult
from pytestlab.camera import Frame
from pytestlab.config.device_config import DeviceConfig
from pytestlab.devices import AutoDevice
from pytestlab.devices import register_device_type


class CameraConfig(DeviceConfig):
    pass


class CameraBackend:
    def __init__(self) -> None:
        self.connected = False
        self.captures = 0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def close(self) -> None:
        self.connected = False

    def capture(self, **kwargs: object) -> dict[str, object]:
        self.captures += 1
        return {"data": b"pixels", "metadata": {"exposure_ms": kwargs["exposure_ms"]}}

    def capture_to(self, path: str | Path, **_: object) -> None:
        Path(path).write_bytes(b"saved-pixels")


class CaptureOnlyBackend:
    def __init__(self) -> None:
        self.connected = False
        self.captures = 0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def close(self) -> None:
        self.connected = False

    def capture(self, **_: object) -> dict[str, object]:
        self.captures += 1
        return {"data": b"capture-only"}


class SuffixAwareBackend(CaptureOnlyBackend):
    def capture_to(self, path: str | Path, **_: object) -> None:
        if Path(path).suffix != ".png":
            raise AssertionError(f"format suffix was lost: {path}")
        Path(path).write_bytes(b"png")


def config() -> CameraConfig:
    return CameraConfig(
        manufacturer="Acme", model="GenericCam", device_type="test_camera", role="fixture"
    )


def test_capture_returns_typed_frame_and_applies_metadata_hook() -> None:
    backend = CameraBackend()
    camera = Camera(config(), backend, metadata_hook=lambda _: {"operator": "qa"})

    frame = camera.capture(exposure_ms=4)

    assert isinstance(frame, Frame)
    assert frame.data == b"pixels"
    assert frame.metadata == {"exposure_ms": 4, "operator": "qa"}
    assert backend.connected


def test_metadata_hook_preserves_frame_description() -> None:
    class DescribedBackend(CameraBackend):
        def capture(self, **_: object) -> Frame[bytes]:
            return Frame(
                b"pixels",
                content_type="image/png",
                width=12,
                height=8,
                capture_id="capture-1",
            )

    frame = Camera(
        config(), DescribedBackend(), metadata_hook=lambda _: {"source": "microscope"}
    ).capture()

    assert frame.content_type == "image/png"
    assert frame.width == 12
    assert frame.height == 8
    assert frame.capture_id == "capture-1"


def test_capture_to_atomically_publishes_image_and_metadata(tmp_path: Path) -> None:
    camera = Camera(config(), CameraBackend())
    image = tmp_path / "capture.bin"
    metadata = tmp_path / "capture.json"

    result = camera.capture_to(image, metadata_path=metadata)

    assert isinstance(result, CaptureResult)
    assert result.path == image
    assert image.read_bytes() == b"saved-pixels"
    assert metadata.read_text() == "{}\n"
    assert not list(tmp_path.glob(".*"))


def test_capability_validation_rejects_non_camera_backend() -> None:
    with pytest.raises(TypeError, match=r"capture\(\) or capture_to\(\)"):
        Camera(config(), object())  # type: ignore[arg-type]


def test_capture_to_applies_metadata_hook_once_for_capture_only_backends(tmp_path: Path) -> None:
    calls: list[int] = []
    camera = Camera(
        config(),
        CaptureOnlyBackend(),
        metadata_hook=lambda _: calls.append(1) or {"source": "camera"},
    )

    result = camera.capture_to(tmp_path / "capture.bin", metadata_path=tmp_path / "capture.json")

    assert result.frame.data == b"capture-only"
    assert calls == [1]
    assert json.loads((tmp_path / "capture.json").read_text()) == {"source": "camera"}


def test_capture_to_refuses_overwrite_by_default(tmp_path: Path) -> None:
    image = tmp_path / "capture.bin"
    image.write_bytes(b"existing")
    camera = Camera(config(), CameraBackend())

    with pytest.raises(FileExistsError):
        camera.capture_to(image)


def test_capture_to_preserves_destination_suffix_for_native_encoders(tmp_path: Path) -> None:
    camera = Camera(config(), SuffixAwareBackend())

    result = camera.capture_to(tmp_path / "capture.png")

    assert result.path.read_bytes() == b"png"


def test_capture_sequence_keeps_one_device_and_numbers_frames(tmp_path: Path) -> None:
    backend = CaptureOnlyBackend()
    camera = Camera(config(), backend)

    results = camera.capture_sequence(tmp_path, count=3, interval_s=0)

    assert [result.path.name for result in results] == [
        "capture-000001.png",
        "capture-000002.png",
        "capture-000003.png",
    ]
    assert backend.captures == 3


def test_capture_sequence_preflights_all_destinations(tmp_path: Path) -> None:
    backend = CaptureOnlyBackend()
    camera = Camera(config(), backend)
    (tmp_path / "capture-000002.png").write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        camera.capture_sequence(tmp_path, count=3)

    assert backend.captures == 0
    assert not (tmp_path / "capture-000001.png").exists()


def test_frame_save_stages_invalid_metadata_before_publishing_image(tmp_path: Path) -> None:
    frame = Frame(b"pixels", metadata={"invalid": float("nan")})
    image = tmp_path / "capture.png"

    with pytest.raises(ValueError):
        frame.save(image, metadata_path=tmp_path / "capture.json")

    assert not image.exists()
    assert not (tmp_path / "capture.json").exists()


def test_camera_driver_works_through_autodevice_registration() -> None:
    class RegisteredCamera(Camera):
        pass

    register_device_type("test_camera", RegisteredCamera, replace=True)
    device = AutoDevice.from_model(config(), backend_override=CameraBackend())

    assert isinstance(device, RegisteredCamera)
    assert device.capture(exposure_ms=1).data == b"pixels"


def test_camera_factory_backend_is_allocated_only_on_first_use():
    from pytestlab.devices.base import _BackendFactory

    allocations = []
    backend = CaptureOnlyBackend()

    def build():
        allocations.append(True)
        return backend

    camera = Camera(config(), _BackendFactory(build))
    assert allocations == []
    camera.close()
    assert allocations == []
    assert camera.capture().data == b"capture-only"
    assert allocations == [True]
    assert backend.connected
    camera.close()
    assert not backend.connected
