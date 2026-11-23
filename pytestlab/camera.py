"""Generic camera capability for PyTestLab devices.

The capability deliberately knows nothing about a camera vendor or transport.
Backends only need to expose ``capture`` and/or ``capture_to``; custom camera
drivers can be registered with :class:`pytestlab.devices.AutoDevice` in the
same way as any other :class:`pytestlab.devices.Device`.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Generic
from typing import Protocol
from typing import TypeVar

from .config.device_config import DeviceConfig
from .devices.base import Device
from .devices.base import DeviceBackend
from .devices.base import _BackendFactory

FrameData = TypeVar("FrameData")


class CameraBackend(DeviceBackend, Protocol):
    """Lifecycle-only camera backend marker.

    A camera backend implements one or both of the optional capture protocols
    below.  Keeping those surfaces separate allows capture-only and
    capture-to-only hardware drivers to remain valid.
    """


class CameraCaptureBackend(CameraBackend, Protocol):
    """Backend that returns a frame in memory."""

    def capture(self, **kwargs: Any) -> Any: ...


class CameraCaptureToBackend(CameraBackend, Protocol):
    """Backend that writes a native frame to a supplied path."""

    def capture_to(self, path: str | Path, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class CameraCapabilities:
    """Declared camera features used by discovery and CLI dispatch."""

    formats: tuple[str, ...] = ("image/png",)
    supports_trigger: bool = False
    supports_stream: bool = False
    max_width: int | None = None
    max_height: int | None = None

    def __post_init__(self) -> None:
        if not self.formats or any(not value for value in self.formats):
            raise ValueError("camera formats must contain at least one value")
        if self.max_width is not None and self.max_width < 1:
            raise ValueError("camera max_width must be positive")
        if self.max_height is not None and self.max_height < 1:
            raise ValueError("camera max_height must be positive")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CameraCapabilities:
        """Build a strict declaration from a profile or backend mapping."""

        formats_value = value.get("formats", ("image/png",))
        if isinstance(formats_value, str):
            formats = (formats_value,)
        elif isinstance(formats_value, (list, tuple)):
            formats = tuple(str(item) for item in formats_value)
        else:
            raise TypeError("camera formats must be a string or sequence")

        def bool_value(name: str, default: bool = False) -> bool:
            item = value.get(name, default)
            if isinstance(item, bool):
                return item
            if isinstance(item, str):
                normalized = item.strip().lower()
                if normalized in {"1", "true", "yes", "on"}:
                    return True
                if normalized in {"0", "false", "no", "off"}:
                    return False
            raise TypeError(f"camera {name} must be boolean")

        return cls(
            formats=formats,
            supports_trigger=bool_value("supports_trigger"),
            supports_stream=bool_value("supports_stream"),
            max_width=value.get("max_width"),
            max_height=value.get("max_height"),
        )


@dataclass(frozen=True)
class Frame(Generic[FrameData]):
    """One captured frame and the metadata associated with that capture."""

    data: FrameData
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    capture_id: str | int | None = None

    def save(
        self,
        path: str | Path,
        *,
        metadata_path: str | Path | None = None,
        overwrite: bool = False,
    ) -> CaptureResult[FrameData]:
        """Atomically save the frame and optional metadata sidecar."""

        destination = Path(path)
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)
        metadata_destination = Path(metadata_path) if metadata_path is not None else None
        if metadata_destination == destination:
            raise ValueError("metadata_path must differ from image path")
        if metadata_destination is not None and metadata_destination.exists() and not overwrite:
            raise FileExistsError(metadata_destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        published_metadata: Path | None = None
        image_temporary = Camera._temporary_path(destination)
        metadata_temporary: Path | None = None
        try:
            Camera._write_data(image_temporary, self.data)
            if metadata_destination is not None:
                published_metadata = metadata_destination
                metadata_temporary = Camera._temporary_path(metadata_destination)
                Camera._write_json(metadata_temporary, dict(self.metadata))
            Camera._publish_atomic(image_temporary, destination, overwrite=overwrite)
            if metadata_temporary is not None:
                assert metadata_destination is not None
                Camera._publish_atomic(
                    metadata_temporary,
                    metadata_destination,
                    overwrite=overwrite,
                )
        finally:
            image_temporary.unlink(missing_ok=True)
            if metadata_temporary is not None:
                metadata_temporary.unlink(missing_ok=True)
        return CaptureResult(self, destination, published_metadata)


@dataclass(frozen=True)
class CaptureResult(Generic[FrameData]):
    """Result of :meth:`Camera.capture_to`."""

    frame: Frame[FrameData]
    path: Path
    metadata_path: Path | None = None


MetadataHook = Callable[[Frame[Any]], Mapping[str, Any]]


class Camera(Device[DeviceConfig]):
    """Vendor-neutral camera capability layered on a normal PyTestLab device.

    A custom driver may subclass this class, or a registered driver may expose
    an equivalent backend and delegate to an instance of this capability. The
    backend is intentionally duck-typed so USB, network, VISA, and local
    camera implementations can use the same API.
    """

    def __init__(
        self,
        config: DeviceConfig,
        backend: CameraBackend | _BackendFactory,
        *,
        metadata_hook: MetadataHook | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(config, backend, **kwargs)
        if not isinstance(backend, _BackendFactory):
            self.validate_capability(backend)
        self.metadata_hook = metadata_hook

    @staticmethod
    def validate_capability(backend: Any) -> None:
        """Raise ``TypeError`` unless the backend can capture frames."""

        if not callable(getattr(backend, "capture", None)) and not callable(
            getattr(backend, "capture_to", None)
        ):
            raise TypeError("Camera backend must provide callable capture() or capture_to().")

    def get_capabilities(self) -> CameraCapabilities:
        """Return backend-declared capabilities without opening a capture."""

        value = getattr(self._backend, "capabilities", None)
        if isinstance(value, CameraCapabilities):
            return value
        if isinstance(value, Mapping):
            try:
                return CameraCapabilities.from_mapping(value)
            except (TypeError, ValueError) as exc:
                raise TypeError("invalid camera capability declaration") from exc
        return CameraCapabilities()

    describe_capabilities = get_capabilities

    def _validate_capture_parameters(self, **kwargs: Any) -> None:
        validator = getattr(self._backend, "validate_capture_parameters", None)
        if callable(validator):
            validator(**kwargs)

    def capture(self, **kwargs: Any) -> Frame[Any]:
        """Capture a frame in memory, using the backend's native operation."""

        capture = getattr(self._backend, "capture", None)
        if not callable(capture):
            raise NotImplementedError("This camera backend only supports capture_to().")
        self._validate_capture_parameters(**kwargs)
        self._ensure_backend_connected()
        return self._with_metadata(self._coerce_frame(capture(**kwargs)))

    def capture_to(
        self,
        path: str | Path,
        *,
        metadata_path: str | Path | None = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> CaptureResult[Any]:
        """Capture to ``path`` and atomically publish image/metadata files.

        The backend writes to a sibling temporary file. Only after the backend
        succeeds is it renamed into place, preventing readers from observing a
        partial frame. Metadata is optional and, when requested, is published
        through its own temporary-file-then-replace operation; the two files
        are individually atomic, not a single filesystem transaction.
        """

        destination = Path(path)
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)
        metadata_destination = Path(metadata_path) if metadata_path is not None else None
        if metadata_destination == destination:
            raise ValueError("metadata_path must differ from image path")
        if metadata_destination is not None and metadata_destination.exists() and not overwrite:
            raise FileExistsError(metadata_destination)
        self._validate_capture_parameters(**kwargs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_backend_connected()
        temporary = self._temporary_path(destination)
        metadata_temporary: Path | None = None
        try:
            capture_to = getattr(self._backend, "capture_to", None)
            if callable(capture_to):
                returned = capture_to(temporary, **kwargs)
                frame = self._frame_from_written_file(returned, temporary)
            else:
                capture = getattr(self._backend, "capture", None)
                if not callable(capture):
                    raise NotImplementedError("camera backend cannot capture frames")
                frame = self._with_metadata(self._coerce_frame(capture(**kwargs)))
                self._write_data(temporary, frame.data)
            if callable(capture_to):
                frame = self._with_metadata(frame)

            published_metadata_path: Path | None = None
            if metadata_destination is not None:
                published_metadata_path = metadata_destination
                metadata_temporary = self._temporary_path(metadata_destination)
                self._write_json(metadata_temporary, dict(frame.metadata))
            self._publish_atomic(temporary, destination, overwrite=overwrite)
            if metadata_temporary is not None:
                assert metadata_destination is not None
                self._publish_atomic(
                    metadata_temporary,
                    metadata_destination,
                    overwrite=overwrite,
                )
            return CaptureResult(frame, destination, published_metadata_path)
        finally:
            temporary.unlink(missing_ok=True)
            if metadata_temporary is not None:
                metadata_temporary.unlink(missing_ok=True)

    def capture_many(
        self,
        paths: Iterable[str | Path],
        *,
        interval_s: float = 0.0,
        metadata: bool = True,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> tuple[CaptureResult[Any], ...]:
        """Capture to explicit paths while keeping one backend connection.

        All destinations are preflighted before the first capture, so a
        collision cannot leave a partially numbered series on disk.
        """

        if interval_s < 0:
            raise ValueError("interval_s must be non-negative")
        destinations = tuple(Path(path) for path in paths)
        if not destinations:
            raise ValueError("paths must contain at least one destination")
        self._validate_capture_parameters(**kwargs)
        metadata_paths = tuple(
            destination.with_suffix(".json") if metadata else None for destination in destinations
        )
        self._preflight_paths(destinations, metadata_paths, overwrite=overwrite)
        results: list[CaptureResult[Any]] = []
        for index, (destination, metadata_path) in enumerate(
            zip(destinations, metadata_paths, strict=True), start=1
        ):
            results.append(
                self.capture_to(
                    destination,
                    metadata_path=metadata_path,
                    overwrite=overwrite,
                    **kwargs,
                )
            )
            if interval_s and index != len(destinations):
                time.sleep(interval_s)
        return tuple(results)

    def capture_sequence(
        self,
        output_dir: str | Path,
        *,
        count: int,
        interval_s: float = 0.0,
        prefix: str = "capture",
        metadata: bool = True,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> tuple[CaptureResult[Any], ...]:
        """Capture a numbered series while keeping one device open."""

        if count < 1:
            raise ValueError("count must be positive")
        if interval_s < 0:
            raise ValueError("interval_s must be non-negative")
        if not prefix or any(char in prefix for char in "/\\"):
            raise ValueError("prefix must be a non-empty filename component")
        self._validate_capture_parameters(**kwargs)
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        return self.capture_many(
            (root / f"{prefix}-{index:06d}.png" for index in range(1, count + 1)),
            interval_s=interval_s,
            metadata=metadata,
            overwrite=overwrite,
            **kwargs,
        )

    @staticmethod
    def _preflight_paths(
        destinations: tuple[Path, ...],
        metadata_paths: tuple[Path | None, ...],
        *,
        overwrite: bool,
    ) -> None:
        seen: set[Path] = set()
        for destination, metadata_path in zip(destinations, metadata_paths, strict=True):
            for path in (destination, metadata_path):
                if path is None:
                    continue
                if path in seen:
                    raise ValueError(f"capture destinations collide: {path}")
                seen.add(path)
                if path.exists() and not overwrite:
                    raise FileExistsError(path)

    def _with_metadata(self, frame: Frame[Any]) -> Frame[Any]:
        metadata = dict(frame.metadata)
        if self.metadata_hook is not None:
            metadata.update(self.metadata_hook(frame))
        return Frame(
            frame.data,
            frame.captured_at,
            metadata,
            frame.content_type,
            frame.width,
            frame.height,
            frame.capture_id,
        )

    @staticmethod
    def _coerce_frame(value: Any) -> Frame[Any]:
        if isinstance(value, Frame):
            return value
        if isinstance(value, Mapping) and "data" in value:
            return Frame(
                value["data"],
                metadata=dict(value.get("metadata", {})),
                content_type=value.get("content_type"),
                width=value.get("width"),
                height=value.get("height"),
                capture_id=value.get("capture_id"),
            )
        return Frame(value)

    def _frame_from_written_file(self, value: Any, path: Path) -> Frame[Any]:
        if value is not None:
            frame = self._coerce_frame(value)
            if not path.exists():
                self._write_data(path, frame.data)
            return frame
        return Frame(path.read_bytes())

    @staticmethod
    def _temporary_path(destination: Path) -> Path:
        fd, name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=destination.suffix,
            dir=destination.parent,
        )
        os.close(fd)
        temporary = Path(name)
        temporary.unlink()
        return temporary

    @staticmethod
    def _write_data(path: Path, data: Any) -> None:
        if isinstance(data, str):
            path.write_text(data)
        elif isinstance(data, (bytes, bytearray, memoryview)):
            path.write_bytes(bytes(data))
        else:
            raise TypeError("capture_to requires bytes-like or string frame data.")

    @staticmethod
    def _publish_atomic(temporary: Path, destination: Path, *, overwrite: bool) -> None:
        """Publish a same-directory temporary file without a TOCTOU overwrite."""

        if overwrite:
            os.replace(temporary, destination)
            return
        try:
            # ``link`` is atomic on the same filesystem and fails if a caller
            # won the race to create the destination.  This is preferable to
            # checking ``exists`` and then unconditionally replacing it.
            os.link(temporary, destination)
        except FileExistsError:
            raise FileExistsError(destination) from None

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any], *, overwrite: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Camera._temporary_path(path)
        try:
            Camera._write_json(temporary, payload)
            Camera._publish_atomic(temporary, path, overwrite=overwrite)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, default=str, sort_keys=True, allow_nan=False) + "\n")


CameraDevice = Camera


__all__ = [
    "Camera",
    "CameraDevice",
    "CameraBackend",
    "CameraCaptureBackend",
    "CameraCaptureToBackend",
    "CameraCapabilities",
    "CaptureResult",
    "Frame",
    "MetadataHook",
]
