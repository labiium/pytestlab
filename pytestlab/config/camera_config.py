"""Generic camera configuration, independent of vendor-specific profiles."""

from collections.abc import Mapping
from typing import Any
from typing import Literal

from .device_config import DeviceConfig


class CameraConfig(DeviceConfig):
    """Logical generic camera configuration; discovered hardware supplies identity."""

    manufacturer: str = "generic"
    model: str = "camera"
    role: Literal["measurement"] = "measurement"
    device_type: Literal["camera"] = "camera"


def require_lamb_camera_resource(resource_string: Any) -> str:
    """Validate the exact camera resource without normalizing it."""
    if not isinstance(resource_string, str) or not resource_string.strip():
        raise ValueError(
            "LAMB camera requires an explicit nonempty address or resource_string "
            "from ptl camera discover."
        )
    return resource_string


def resolve_lamb_camera_resource(address: str | None, backend: Mapping[str, Any]) -> str:
    """Resolve the explicit binding used by the built-in LAMB camera backend."""
    if "camera_id" in backend or "camera_label" in backend:
        raise ValueError(
            "Use address or resource_string from ptl camera discover, not camera_id/camera_label."
        )
    resource_string = backend.get("resource_string")
    if address and resource_string and address != resource_string:
        raise ValueError("Conflicting camera address and backend resource_string.")
    return require_lamb_camera_resource(address or resource_string)
