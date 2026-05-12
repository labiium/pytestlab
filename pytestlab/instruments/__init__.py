from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from .AutoInstrument import AutoInstrument
    from .DCActiveLoad import DCActiveLoad
    from .instrument import Instrument
    from .Multimeter import Multimeter
    from .Oscilloscope import Oscilloscope
    from .PowerSupply import PowerSupply
    from .WaveformGenerator import WaveformGenerator

__all__ = [
    "AutoInstrument",
    "DCActiveLoad",
    "Instrument",
    "Multimeter",
    "Oscilloscope",
    "PowerSupply",
    "WaveformGenerator",
]

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "AutoInstrument": ("pytestlab.instruments.AutoInstrument", "AutoInstrument"),
    "DCActiveLoad": ("pytestlab.instruments.DCActiveLoad", "DCActiveLoad"),
    "Instrument": ("pytestlab.instruments.instrument", "Instrument"),
    "Multimeter": ("pytestlab.instruments.Multimeter", "Multimeter"),
    "Oscilloscope": ("pytestlab.instruments.Oscilloscope", "Oscilloscope"),
    "PowerSupply": ("pytestlab.instruments.PowerSupply", "PowerSupply"),
    "WaveformGenerator": ("pytestlab.instruments.WaveformGenerator", "WaveformGenerator"),
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
