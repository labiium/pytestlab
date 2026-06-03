"""
pytestlab – scientific measurement toolbox
=========================================

This package exposes a rich measurement API while keeping import-time side
effects to a minimum. Public attributes are loaded on demand so that lightweight
operations (like invoking the CLI) do not pay the cost of the full measurement
stack until those objects are actually needed.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "0.3.0"  # Update this line to change the version

__all__ = [
    "Session",
    "AutoDevice",
    "AutoInstrument",
    "Bench",
    "Device",
    "DeviceConfig",
    "DeviceIO",
    "DeviceRole",
    "Experiment",
    "Instrument",
    "InstrumentConfig",
    "MeasurementResult",
    "InstrumentConfigurationError",
    "InstrumentParameterError",
    "Measurement",
    "MeasurementSession",
    "SwitchMatrixDevice",
    "AccessoryProfile",
    "BoundAccessory",
    "MeasurementChain",
    "set_log_level",
    "get_logger",
    "reinitialize_logging",
]

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "Session": ("pytestlab.measurements.session", "MeasurementSession"),
    "AutoDevice": ("pytestlab.devices", "AutoDevice"),
    "AutoInstrument": ("pytestlab.instruments.AutoInstrument", "AutoInstrument"),
    "Bench": ("pytestlab.bench", "Bench"),
    "Device": ("pytestlab.devices", "Device"),
    "DeviceConfig": ("pytestlab.config", "DeviceConfig"),
    "DeviceIO": ("pytestlab.devices", "DeviceIO"),
    "DeviceRole": ("pytestlab.config", "DeviceRole"),
    "Experiment": ("pytestlab.experiments", "Experiment"),
    "Instrument": ("pytestlab.instruments", "Instrument"),
    "InstrumentConfig": ("pytestlab.config", "InstrumentConfig"),
    "MeasurementResult": ("pytestlab.experiments", "MeasurementResult"),
    "InstrumentConfigurationError": (
        "pytestlab.errors",
        "InstrumentConfigurationError",
    ),
    "InstrumentParameterError": (
        "pytestlab.errors",
        "InstrumentParameterError",
    ),
    "Measurement": ("pytestlab.measurements.session", "Measurement"),
    "MeasurementSession": ("pytestlab.measurements.session", "MeasurementSession"),
    "SwitchMatrixDevice": ("pytestlab.devices", "SwitchMatrixDevice"),
    "AccessoryProfile": ("pytestlab.accessories", "AccessoryProfile"),
    "BoundAccessory": ("pytestlab.accessories", "BoundAccessory"),
    "MeasurementChain": ("pytestlab.accessories", "MeasurementChain"),
    "set_log_level": ("pytestlab._log", "set_log_level"),
    "get_logger": ("pytestlab._log", "get_logger"),
    "reinitialize_logging": ("pytestlab._log", "reinitialize_logging"),
}

_COMPLIANCE_TRIGGERS: set[str] = {
    "Experiment",
    "Measurement",
    "MeasurementResult",
    "MeasurementSession",
}


def __getattr__(name: str) -> Any:
    """Dynamically resolve public attributes without importing heavy modules up front."""
    if name == "compliance":
        module = import_module("pytestlab.compliance")
        globals()[name] = module
        return module

    try:
        module_name, attr_name = _LAZY_ATTRS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    if name in _COMPLIANCE_TRIGGERS and "compliance" not in globals():
        globals()["compliance"] = import_module("pytestlab.compliance")

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazily-resolved attributes through dir()."""
    return sorted(set(__all__) | set(globals().keys()))
