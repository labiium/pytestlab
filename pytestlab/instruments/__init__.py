from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType
from typing import Any

__all__ = [
    "AutoDevice",
    "AutoInstrument",
    "DCActiveLoad",
    "Device",
    "DeviceIO",
    "ImpedanceAnalyzer",
    "ImpedanceReading",
    "Instrument",
    "InstrumentSelfTestResult",
    "Multimeter",
    "OperationDescription",
    "OperationOption",
    "OperationParameterDescription",
    "Oscilloscope",
    "PowerSupply",
    "ProfileInstrument",
    "SharedClockModel",
    "SourceMeasure",
    "WaveformGenerator",
    "WaveformSetResult",
]

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "AutoDevice": ("pytestlab.devices", "AutoDevice"),
    "Device": ("pytestlab.devices", "Device"),
    "DeviceIO": ("pytestlab.devices", "DeviceIO"),
    "AutoInstrument": ("pytestlab.instruments.AutoInstrument", "AutoInstrument"),
    "DCActiveLoad": ("pytestlab.instruments.DCActiveLoad", "DCActiveLoad"),
    "ImpedanceAnalyzer": ("pytestlab.instruments.ImpedanceAnalyzer", "ImpedanceAnalyzer"),
    "ImpedanceReading": ("pytestlab.instruments.ImpedanceAnalyzer", "ImpedanceReading"),
    "Instrument": ("pytestlab.instruments.instrument", "Instrument"),
    "InstrumentSelfTestResult": ("pytestlab.instruments.self_test", "InstrumentSelfTestResult"),
    "Multimeter": ("pytestlab.instruments.Multimeter", "Multimeter"),
    "OperationDescription": (
        "pytestlab.instruments.operation_contract",
        "OperationDescription",
    ),
    "OperationOption": ("pytestlab.instruments.operation_contract", "OperationOption"),
    "OperationParameterDescription": (
        "pytestlab.instruments.operation_contract",
        "OperationParameterDescription",
    ),
    "Oscilloscope": ("pytestlab.instruments.Oscilloscope", "Oscilloscope"),
    "PowerSupply": ("pytestlab.instruments.PowerSupply", "PowerSupply"),
    "ProfileInstrument": (
        "pytestlab.instruments.profile_instrument",
        "ProfileInstrument",
    ),
    "SourceMeasure": ("pytestlab.instruments.SourceMeasure", "SourceMeasure"),
    "SharedClockModel": ("pytestlab.instruments.waveform_set", "SharedClockModel"),
    "WaveformSetResult": ("pytestlab.instruments.waveform_set", "WaveformSetResult"),
    "WaveformGenerator": (
        "pytestlab.instruments.WaveformGenerator",
        "WaveformGenerator",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_ATTRS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))


class _InstrumentPackage(ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        # Importing a legacy CamelCase submodule binds it to its parent package.
        # Keep the same-named public export a class, regardless of import order.
        target = _LAZY_ATTRS.get(name)
        if target is not None and isinstance(value, ModuleType) and value.__name__ == target[0]:
            value = getattr(value, target[1])
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _InstrumentPackage
