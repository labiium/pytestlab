"""
PyTestLab GUI Components
========================

A declarative GUI framework for building interactive instrument control panels
in Jupyter notebooks.

Widget classes are loaded lazily so importing :mod:`pytestlab.gui` does not
require Jupyter widget dependencies until a GUI feature is accessed.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "awidget_callback",
    "InstrumentPanel",
    "Slider",
    "Toggle",
    "Button",
]

_LAZY_ATTRS = {
    "awidget_callback": ("pytestlab.gui.threading_utils", "awidget_callback"),
    "InstrumentPanel": ("pytestlab.gui.builder", "InstrumentPanel"),
    "Slider": ("pytestlab.gui.builder", "Slider"),
    "Toggle": ("pytestlab.gui.builder", "Toggle"),
    "Button": ("pytestlab.gui.builder", "Button"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _LAZY_ATTRS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    try:
        value = getattr(import_module(module_name), attribute)
    except ModuleNotFoundError as exc:
        if exc.name == "ipywidgets":
            raise ModuleNotFoundError(
                "pytestlab.gui requires the optional 'ipywidgets' package"
            ) from exc
        raise
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
