"""JPEG camera captures from the LAMB webcam API."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from urllib.parse import quote

import httpx

from ..._lamb_url import resolve_lamb_url
from ...camera import CameraCapabilities
from ...camera import Frame
from ...config.camera_config import require_lamb_camera_resource
from ...config.camera_config import resolve_lamb_camera_resource
from ...devices.registry import BackendBuildContext


class LambCameraBackend:
    """Capture JPEG frames from one explicitly configured LAMB camera."""

    capabilities = CameraCapabilities(formats=("image/jpeg",))

    def __init__(self, url: str, resource_string: str | None, timeout_ms: int) -> None:
        self._resource_string = require_lamb_camera_resource(resource_string)
        self.url = url.rstrip("/")
        self.timeout = timeout_ms / 1000
        self._client: httpx.Client | None = None

    @property
    def resource_string(self) -> str:
        """The exact resource configured for this backend's lifetime."""
        return self._resource_string

    def connect(self) -> None:
        if self._client is not None:
            return
        client = httpx.Client(timeout=self.timeout)
        try:
            response = client.get(f"{self.url}/webcams")
            response.raise_for_status()
            payload = response.json()
            devices = payload.get("devices") if isinstance(payload, dict) else None
            if not isinstance(devices, list):
                raise ValueError("LAMB camera discovery must return a devices list")
            matches = [
                device
                for device in devices
                if isinstance(device, dict)
                and isinstance(device.get("resource_string"), str)
                and device["resource_string"] == self.resource_string
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Configured camera is not uniquely available from LAMB: "
                    f"{self.resource_string} ({len(matches)} matches)"
                )
        except Exception:
            client.close()
            raise
        self._client = client

    def disconnect(self) -> None:
        self.close()

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()

    @staticmethod
    def _dimension(name: str, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
        return value

    def validate_capture_parameters(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """Reject invalid dimensions before the generic Camera connects."""
        self._dimension("width", width)
        self._dimension("height", height)

    def capture(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> Frame[bytes]:
        self.validate_capture_parameters(width=width, height=height)
        if self._client is None:
            raise RuntimeError("LAMB camera backend is not connected")

        params: dict[str, str | int] = {"format": "jpeg"}
        if width is not None:
            params["width"] = width
        if height is not None:
            params["height"] = height
        encoded_resource = quote(self.resource_string, safe="")
        response = self._client.post(
            f"{self.url}/webcams/{encoded_resource}/capture",
            params=params,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "image/jpeg" or not response.content:
            raise ValueError("LAMB camera response must contain a nonempty JPEG image")

        return Frame(
            data=response.content,
            captured_at=datetime.now(UTC),
            metadata={"timestamp_source": "client_response_received"},
            content_type=content_type,
            # The API returns image bytes, not source sensor dimensions.
            width=None,
            height=None,
        )


def build_lamb_camera_backend(context: BackendBuildContext) -> LambCameraBackend:
    """Build a camera backend using the standard LAMB URL precedence."""
    spec = context.backend_spec or {}
    url = resolve_lamb_url(
        spec.get("url"),
        profile_url=getattr(context.config, "lamb_url", None),
    )
    resource_string = resolve_lamb_camera_resource(context.address, spec)
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("LAMB camera backend requires an HTTP(S) url")
    return LambCameraBackend(url, resource_string, context.timeout_ms)
