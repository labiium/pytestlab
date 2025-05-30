from __future__ import annotations
import yaml
from typing import Type, Dict # For type hint of model_cls

# Import the legacy instrument config classes (not Pydantic)
from .instrument_config import InstrumentConfig # Base legacy InstrumentConfig
from .oscilloscope_config_legacy import OscilloscopeConfig  # Legacy version with proper ChannelsConfig conversion
from .power_supply_config import PowerSupplyConfig
from .multimeter_config import MultimeterConfig
from .waveform_generator_config import WaveformGeneratorConfig
from .dc_active_load_config import DCActiveLoadConfig
# Add other specific instrument config imports as they are refactored

# Registry mapping device_type string to the legacy config class
# Ensure device_type strings match what's in the YAML files (e.g., "oscilloscope", "psu")
_instrument_model_registry: Dict[str, Type[InstrumentConfig]] = {
    "oscilloscope": OscilloscopeConfig,
    "power_supply": PowerSupplyConfig,
    "multimeter": MultimeterConfig,
    "waveform_generator": WaveformGeneratorConfig,
    "dc_active_load": DCActiveLoadConfig,
    # Populate with other device_type keys and their legacy config classes
}

def load_config(config_source: str | Dict) -> InstrumentConfig:
    """
    Loads and validates an instrument configuration from a YAML file path or a dict.
    The 'device_type' key in the data is used to determine the specific legacy config class.
    """
    if isinstance(config_source, str):
        with open(config_source, 'r') as f:
            data = yaml.safe_load(f)
    elif isinstance(config_source, dict):
        data = config_source
    else:
        raise TypeError("config_source must be a file path (str) or a dict")

    device_type = data.get("device_type")
    if not device_type:
        raise ValueError("Configuration data must contain a 'device_type' key.")

    model_cls = _instrument_model_registry.get(device_type)
    if not model_cls:
        raise ValueError(f"Unknown device_type: '{device_type}'. Not found in registry.")

    # Use legacy constructor pattern: pass the entire data dictionary as **kwargs
    return model_cls(**data)