from __future__ import annotations

import importlib  # Changed from 'from importlib import import_module' for consistency
import inspect
import typing  # For get_origin, get_args
from pathlib import Path
from typing import Any  # Added Literal, Union
from typing import Literal  # Added Literal, Union
from typing import Union  # Added Literal, Union

import yaml
from pydantic import ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from ..devices.registry import get_config_model
from ..devices.registry import get_config_registry
from ..devices.registry import load_import_path
from ..devices.registry import register_config_model
from ..devices.registry import validate_config_model
from .device_config import DeviceConfig
from .device_config import GenericDeviceConfig
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
_MODEL_REGISTRY_CACHE: dict[str, type[DeviceConfig]] | None = None


def _discover_models() -> dict[str, type[DeviceConfig]]:
    pkg = importlib.import_module("pytestlab.config")
    registry: dict[str, type[DeviceConfig]] = {}

    for name, member in inspect.getmembers(pkg):
        if name.startswith("_"):
            continue

        if (
            inspect.isclass(member)
            and issubclass(member, InstrumentConfig)
            and member is not InstrumentConfig
        ):
            cls = member

            if "device_type" in cls.model_fields:
                field_info: FieldInfo = cls.model_fields["device_type"]

                possible_device_types = set()

                annotation = field_info.annotation

                origin_annotation = typing.get_origin(annotation)
                args_annotation = typing.get_args(annotation)

                if origin_annotation is Union:
                    for union_arg in args_annotation:
                        if typing.get_origin(union_arg) is Literal:
                            for literal_val in typing.get_args(union_arg):
                                if isinstance(literal_val, str):
                                    possible_device_types.add(literal_val)
                elif origin_annotation is Literal:
                    for literal_val in args_annotation:
                        if isinstance(literal_val, str):
                            possible_device_types.add(literal_val)

                if field_info.default is not PydanticUndefined and isinstance(
                    field_info.default, str
                ):
                    possible_device_types.add(field_info.default)

                for dt_str in possible_device_types:
                    if dt_str in registry and registry[dt_str] is not cls:
                        print(
                            f"Warning: Device type '{dt_str}' from {cls.__name__} conflicts with existing registration "
                            f"for {registry[dt_str].__name__}. Overwriting with {cls.__name__}."
                        )
                    registry[dt_str] = cls
    return registry


def get_model_registry() -> dict[str, type[DeviceConfig]]:
    registry = get_config_registry()
    registry.update(_discover_models())
    return registry


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


def load_device_profile(key_or_path_or_dict: str | Path | dict[str, Any]) -> DeviceConfig:
    """Loads a device profile from a key, file path, or dictionary.

    This is the single entry-point for loading profiles. Drivers should never
    read YAML themselves.

    Args:
        key_or_path_or_dict: A profile key, a path to a profile file, or a
            dictionary containing profile data.

    Returns:
        A ``DeviceConfig`` object.

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

    model_cls = None
    config_model_path = data.get("config_model")
    if isinstance(config_model_path, str):
        model_cls = validate_config_model(load_import_path(config_model_path), config_model_path)
        register_config_model(device_type, model_cls, replace=True)
    if model_cls is None:
        model_cls = get_config_model(device_type) or get_model_registry().get(device_type)

    if model_cls is None:
        if data.get("driver"):
            model_cls = GenericDeviceConfig
        else:
            model_registry = get_model_registry()
            raise ValueError(
                f"No Pydantic model found for device_type '{device_type}'. "
                "Provide 'config_model' or 'driver' for a custom device. "
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

    if not isinstance(validated_model, DeviceConfig):
        raise TypeError(
            f"Validated model for {device_type} is not an instance of DeviceConfig."
        )

    return validated_model
