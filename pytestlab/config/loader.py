from __future__ import annotations
import yaml
from pydantic import BaseModel # Used for type hint in registry
from typing import Type, Dict # For type hint of model_cls

# Import the refactored Pydantic instrument config classes
from .instrument_config import InstrumentConfig # Base Pydantic InstrumentConfig
from .oscilloscope_config import OscilloscopeConfig
from .power_supply_config import PowerSupplyConfig
from .multimeter_config import MultimeterConfig
from .waveform_generator_config import WaveformGeneratorConfig
from .dc_active_load_config import DCActiveLoadConfig
# Add other specific instrument config imports as they are refactored

# Registry mapping device_type string to the Pydantic model class
# Ensure device_type strings match what's in the YAML files (e.g., "oscilloscope", "psu")
_instrument_model_registry: Dict[str, Type[InstrumentConfig]] = {
    "oscilloscope": OscilloscopeConfig,
    "power_supply": PowerSupplyConfig,
    "multimeter": MultimeterConfig,
    "waveform_generator": WaveformGeneratorConfig,
    "dc_active_load": DCActiveLoadConfig,
    # Populate with other device_type keys and their Pydantic model classes
}

def load_config(config_source: str | Dict) -> InstrumentConfig:
    """
    Loads and validates an instrument configuration from a YAML file path or a dict.
    The 'device_type' key in the data is used to determine the specific Pydantic model.
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

    # Pass the entire data dictionary, Pydantic will handle inherited fields.
    return model_cls.model_validate(data)