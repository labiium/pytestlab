from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "AccuracySpec",
    "BaseConfig",
    "Config",
    "DCActiveLoadConfig",
    "InstrumentConfig",
    "ConfigLoader",
    "MultimeterConfig",
    "OscilloscopeConfig",
    "PowerMeterConfig",
    "PowerSupplyConfig",
    "SpectrumAnalyzerConfig",
    "VirtualInstrumentConfig",
    "VNAConfig",
    "WaveformGeneratorConfig",
    "scpi_schema",
]

_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    "AccuracySpec": ("pytestlab.config.accuracy", "AccuracySpec"),
    "BaseConfig": ("pytestlab.config.base", "BaseConfig"),
    "Config": ("pytestlab.config.config", "Config"),
    "DCActiveLoadConfig": ("pytestlab.config.dc_active_load_config", "DCActiveLoadConfig"),
    "InstrumentConfig": ("pytestlab.config.instrument_config", "InstrumentConfig"),
    "ConfigLoader": ("pytestlab.config.loader", "ConfigLoader"),
    "MultimeterConfig": ("pytestlab.config.multimeter_config", "MultimeterConfig"),
    "OscilloscopeConfig": ("pytestlab.config.oscilloscope_config", "OscilloscopeConfig"),
    "PowerMeterConfig": ("pytestlab.config.power_meter_config", "PowerMeterConfig"),
    "PowerSupplyConfig": ("pytestlab.config.power_supply_config", "PowerSupplyConfig"),
    "SpectrumAnalyzerConfig": ("pytestlab.config.spectrum_analyzer_config", "SpectrumAnalyzerConfig"),
    "VirtualInstrumentConfig": ("pytestlab.config.virtual_instrument_config", "VirtualInstrumentConfig"),
    "VNAConfig": ("pytestlab.config.vna_config", "VNAConfig"),
    "WaveformGeneratorConfig": ("pytestlab.config.waveform_generator_config", "WaveformGeneratorConfig"),
    "scpi_schema": ("pytestlab.config.scpi_schema", None),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_ATTRS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals().keys()))
