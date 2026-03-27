from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "Database",
    "DatabaseBackup",
    "MeasurementDatabase",
    "Experiment",
    "ExperimentParameter",
    "MeasurementResult",
    "Result",
    "Sweep",
]

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "Database": ("pytestlab.experiments.database", "Database"),
    "DatabaseBackup": ("pytestlab.experiments.database", "DatabaseBackup"),
    "MeasurementDatabase": ("pytestlab.experiments.database", "MeasurementDatabase"),
    "Experiment": ("pytestlab.experiments.experiments", "Experiment"),
    "ExperimentParameter": ("pytestlab.experiments.experiments", "ExperimentParameter"),
    "MeasurementResult": ("pytestlab.experiments.results", "MeasurementResult"),
    "Result": ("pytestlab.experiments.results", "MeasurementResult"),
    "Sweep": ("pytestlab.experiments.sweep", "Sweep"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_ATTRS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals().keys()))
