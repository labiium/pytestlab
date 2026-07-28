"""Public configuration API with lazy attribute loading.

Importing a narrow configuration module should not initialize every concrete
instrument model or the uncertainty stack.  The mapping below preserves the
package-level API while deferring each dependency until that name is used.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

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


_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    "AccuracySpec": ("pytestlab.uncertainty.specs", "AccuracySpec"),
    "AccuracyModel": ("pytestlab.uncertainty.specs", "AccuracyModel"),
    "BandAccuracySpec": ("pytestlab.uncertainty.specs", "BandAccuracySpec"),
    "BaseConfig": ("pytestlab.config.base", "BaseConfig"),
    "CompositeBudgetSpec": ("pytestlab.uncertainty.specs", "CompositeBudgetSpec"),
    "Config": ("pytestlab.config.config", "Config"),
    "ConfigLoader": ("pytestlab.config.loader", "ConfigLoader"),
    "DCActiveLoadConfig": ("pytestlab.config.dc_active_load_config", "DCActiveLoadConfig"),
    "DeviceConfig": ("pytestlab.config.device_config", "DeviceConfig"),
    "DeviceRole": ("pytestlab.config.device_config", "DeviceRole"),
    "ExpressionAccuracySpec": ("pytestlab.uncertainty.specs", "ExpressionAccuracySpec"),
    "GenericDeviceConfig": ("pytestlab.config.device_config", "GenericDeviceConfig"),
    "InstrumentConfig": ("pytestlab.config.instrument_config", "InstrumentConfig"),
    "MeasurementQuantity": ("pytestlab.uncertainty", "Quantity"),
    "MonteCarloAccuracySpec": ("pytestlab.uncertainty.specs", "MonteCarloAccuracySpec"),
    "MultimeterConfig": ("pytestlab.config.multimeter_config", "MultimeterConfig"),
    "OscilloscopeConfig": ("pytestlab.config.oscilloscope_config", "OscilloscopeConfig"),
    "PowerMeterConfig": ("pytestlab.config.power_meter_config", "PowerMeterConfig"),
    "PowerSupplyConfig": ("pytestlab.config.power_supply_config", "PowerSupplyConfig"),
    "RepeatabilityAccuracySpec": (
        "pytestlab.uncertainty.specs",
        "RepeatabilityAccuracySpec",
    ),
    "SpectrumAnalyzerConfig": (
        "pytestlab.config.spectrum_analyzer_config",
        "SpectrumAnalyzerConfig",
    ),
    "SwitchMatrixConfig": ("pytestlab.config.switch_matrix_config", "SwitchMatrixConfig"),
    "UncertaintyBudget": ("pytestlab.uncertainty", "UncertaintyBudget"),
    "UncertaintyContext": ("pytestlab.uncertainty.specs", "UncertaintyContext"),
    "UncertaintyDistribution": ("pytestlab.uncertainty", "Distribution"),
    "UnitCompatibilityError": ("pytestlab.uncertainty", "UnitCompatibilityError"),
    "evaluate_uncertainty_model": ("pytestlab.uncertainty.specs", "evaluate_quantity"),
    "VirtualInstrumentConfig": (
        "pytestlab.config.virtual_instrument_config",
        "VirtualInstrumentConfig",
    ),
    "VNAConfig": ("pytestlab.config.vna_config", "VNAConfig"),
    "WaveformGeneratorConfig": (
        "pytestlab.config.waveform_generator_config",
        "WaveformGeneratorConfig",
    ),
    "scpi_schema": ("pytestlab.config.scpi_schema", None),
}


def __getattr__(name: str) -> Any:
    """Resolve package-level exports without eager transitive imports."""
    try:
        module_name, attr_name = _LAZY_ATTRS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include lazy public names in introspection."""
    return sorted(set(__all__) | set(globals()))
