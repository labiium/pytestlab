from __future__ import annotations

from .base import Device
from .base import DeviceIO
from .factory import AutoDevice
from .providers import BackendProvider
from .providers import BackendResourceScope
from .providers import get_backend_provider
from .providers import prepare_backend_resources
from .providers import register_backend_provider
from .registry import BackendBuildContext
from .registry import get_backend_factory
from .registry import get_config_model
from .registry import get_config_registry
from .registry import get_device_driver
from .registry import get_device_registry
from .registry import register_backend
from .registry import register_config_model
from .registry import register_device_type
from .switch_matrix import SwitchMatrixDevice

__all__ = [
    "AutoDevice",
    "BackendBuildContext",
    "BackendProvider",
    "BackendResourceScope",
    "Device",
    "DeviceIO",
    "get_backend_factory",
    "get_backend_provider",
    "get_config_model",
    "get_config_registry",
    "get_device_driver",
    "get_device_registry",
    "register_backend",
    "prepare_backend_resources",
    "register_backend_provider",
    "register_config_model",
    "register_device_type",
    "SwitchMatrixDevice",
]
