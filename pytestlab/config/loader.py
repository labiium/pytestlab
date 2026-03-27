from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .instrument_config import InstrumentConfig


# --- DUMMY ConfigLoader for mkdocstrings compatibility ---
class ConfigLoader:
    """
    Dummy ConfigLoader class for documentation compatibility.
    This is not used in runtime code, but allows mkdocstrings to resolve
    'pytestlab.config.ConfigLoader' for API docs.
    """

    pass


# Global cache for discovered models to avoid re-discovering on every call
_MODEL_REGISTRY_CACHE: dict[str, type[InstrumentConfig]] | None = None

_MODEL_SPECS: dict[str, tuple[str, str]] = {
    "oscilloscope": ("pytestlab.config.oscilloscope_config", "OscilloscopeConfig"),
    "waveform_generator": (
        "pytestlab.config.waveform_generator_config",
        "WaveformGeneratorConfig",
    ),
    "power_supply": ("pytestlab.config.power_supply_config", "PowerSupplyConfig"),
    "dc_active_load": ("pytestlab.config.dc_active_load_config", "DCActiveLoadConfig"),
    "multimeter": ("pytestlab.config.multimeter_config", "MultimeterConfig"),
    "vna": ("pytestlab.config.vna_config", "VNAConfig"),
    "spectrum_analyzer": (
        "pytestlab.config.spectrum_analyzer_config",
        "SpectrumAnalyzerConfig",
    ),
    "power_meter": ("pytestlab.config.power_meter_config", "PowerMeterConfig"),
    "virtual_instrument": (
        "pytestlab.config.virtual_instrument_config",
        "VirtualInstrumentConfig",
    ),
}


def _discover_models() -> dict[str, type[InstrumentConfig]]:
    registry: dict[str, type[InstrumentConfig]] = {}
    for device_type, (module_name, attr_name) in _MODEL_SPECS.items():
        module = import_module(module_name)
        model_cls = getattr(module, attr_name)
        registry[device_type] = model_cls
    return registry


def get_model_registry() -> dict[str, type[InstrumentConfig]]:
    global _MODEL_REGISTRY_CACHE
    if _MODEL_REGISTRY_CACHE is None:
        _MODEL_REGISTRY_CACHE = _discover_models()
    return _MODEL_REGISTRY_CACHE


def resolve_profile_key_to_path(key: str) -> Path:
    """Resolves a profile key to the full path of the corresponding profile YAML file.

    This function searches for profiles in the ``pytestlab/profiles`` directory.

    Args:
        key: The profile key, e.g., ``"keysight/DSOX1204G"``.

    Returns:
        The full path to the profile YAML file.

    Raises:
        FileNotFoundError: If the profile file cannot be found.
    """
    # This assumes that loader.py is at pytestlab/config/loader.py,
    # so two levels up is the pytestlab directory.
    profiles_dir = Path(__file__).parent.parent / "profiles"
    profile_path = (profiles_dir / key).with_suffix(".yaml")

    if not profile_path.is_file():
        raise FileNotFoundError(
            f"Profile with key '{key}' not found. " f"Looked for '{profile_path}'."
        )
    return profile_path


def load_profile(key_or_path_or_dict: str | Path | dict[str, Any]) -> InstrumentConfig:
    """Loads an instrument profile from a key, file path, or dictionary.

    This is the single entry-point for loading profiles. Drivers should never
    read YAML themselves.

    Args:
        key_or_path_or_dict: A profile key, a path to a profile file, or a
            dictionary containing profile data.

    Returns:
        An ``InstrumentConfig`` object.

    Raises:
        TypeError: If the input is not a string, Path, or dictionary.
        ValueError: If the loaded profile data is not a dictionary or is
            missing the ``device_type`` field.
        FileNotFoundError: If the profile key cannot be resolved to a file.
    """
    data: dict[str, Any]

    if isinstance(key_or_path_or_dict, dict):
        data = key_or_path_or_dict
    elif isinstance(key_or_path_or_dict, Path):
        with open(key_or_path_or_dict) as f:
            data = yaml.safe_load(f)
    elif isinstance(key_or_path_or_dict, str):
        potential_path = Path(key_or_path_or_dict)
        if potential_path.suffix in [".yaml", ".yml"] and potential_path.is_file():
            with open(potential_path) as f:
                data = yaml.safe_load(f)
        else:
            profile_path = resolve_profile_key_to_path(key_or_path_or_dict)
            with open(profile_path) as f:
                data = yaml.safe_load(f)
    else:
        raise TypeError("Input must be a profile key (str), a Path object, or a dictionary.")

    if not isinstance(data, dict):
        raise ValueError("Loaded profile data is not a dictionary.")

    device_type = data.get("device_type")
    if not device_type:
        raise ValueError("Profile data must contain a 'device_type' field.")

    model_registry = get_model_registry()
    model_cls = model_registry.get(device_type)

    if model_cls is None:
        raise ValueError(
            f"No Pydantic model found for device_type '{device_type}'. "
            f"Discovered models: {list(model_registry.keys())}"
        )

    # Pop simulation-specific fields before validation, as they're not part of the config model
    if "simulation" in data:
        data.pop("simulation")
    if "identification" in data:
        data.pop("identification")

    try:
        validated_model = model_cls.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise ValueError(f"Profile for device_type '{device_type}' is invalid: {e}") from e

    if not isinstance(validated_model, InstrumentConfig):
        raise TypeError(
            f"Validated model for {device_type} is not an instance of InstrumentConfig."
        )

    return validated_model
