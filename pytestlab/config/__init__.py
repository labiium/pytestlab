from . import scpi_schema
from .accuracy import AccuracySpec
from .base import BaseConfig
from .config import Config
from .dc_active_load_config import DCActiveLoadConfig
from .device_config import DeviceConfig
from .device_config import DeviceRole
from .device_config import GenericDeviceConfig
from .instrument_config import InstrumentConfig
from .multimeter_config import MultimeterConfig
from .oscilloscope_config import OscilloscopeConfig
from .power_meter_config import PowerMeterConfig
from .power_supply_config import PowerSupplyConfig
from .spectrum_analyzer_config import SpectrumAnalyzerConfig
from .virtual_instrument_config import VirtualInstrumentConfig
from .vna_config import VNAConfig
from .waveform_generator_config import WaveformGeneratorConfig

__all__ = [
    "AccuracySpec",
    "BaseConfig",
    "Config",
    "DCActiveLoadConfig",
    "DeviceConfig",
    "DeviceRole",
    "GenericDeviceConfig",
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


def __getattr__(name: str):
    if name == "ConfigLoader":
        from .loader import ConfigLoader

        return ConfigLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
