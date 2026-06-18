from ..uncertainty import Distribution as UncertaintyDistribution
from ..uncertainty import Quantity as MeasurementQuantity
from ..uncertainty import UncertaintyBudget
from ..uncertainty import UnitCompatibilityError
from ..uncertainty.specs import AccuracyModel
from ..uncertainty.specs import AccuracySpec
from ..uncertainty.specs import BandAccuracySpec
from ..uncertainty.specs import CompositeBudgetSpec
from ..uncertainty.specs import ExpressionAccuracySpec
from ..uncertainty.specs import MonteCarloAccuracySpec
from ..uncertainty.specs import RepeatabilityAccuracySpec
from ..uncertainty.specs import UncertaintyContext
from ..uncertainty.specs import evaluate_quantity as evaluate_uncertainty_model
from . import scpi_schema
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
from .switch_matrix_config import SwitchMatrixConfig
from .virtual_instrument_config import VirtualInstrumentConfig
from .vna_config import VNAConfig
from .waveform_generator_config import WaveformGeneratorConfig

__all__ = [
    "AccuracySpec",
    "AccuracyModel",
    "BandAccuracySpec",
    "BaseConfig",
    "CompositeBudgetSpec",
    "Config",
    "DCActiveLoadConfig",
    "DeviceConfig",
    "DeviceRole",
    "GenericDeviceConfig",
    "InstrumentConfig",
    "ConfigLoader",
    "ExpressionAccuracySpec",
    "MeasurementQuantity",
    "MonteCarloAccuracySpec",
    "RepeatabilityAccuracySpec",
    "MultimeterConfig",
    "OscilloscopeConfig",
    "PowerMeterConfig",
    "PowerSupplyConfig",
    "SpectrumAnalyzerConfig",
    "SwitchMatrixConfig",
    "UncertaintyBudget",
    "UncertaintyContext",
    "UncertaintyDistribution",
    "UnitCompatibilityError",
    "evaluate_uncertainty_model",
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
