from __future__ import annotations

import importlib # Changed from 'from importlib import import_module' for consistency
import inspect
from pathlib import Path
from typing import Any, Type, Literal, Union # Added Literal, Union
import typing # For get_origin, get_args
import yaml
from pydantic import BaseModel, ValidationError
import jsonschema
from pydantic_core import PydanticUndefined
from pydantic.fields import FieldInfo

from .instrument_config import InstrumentConfig


# Global cache for discovered models to avoid re-discovering on every call
_MODEL_REGISTRY_CACHE: dict[str, Type[InstrumentConfig]] | None = None


def _discover_models() -> dict[str, Type[InstrumentConfig]]:
    pkg = importlib.import_module("pytestlab.config")
    registry: dict[str, Type[InstrumentConfig]] = {}

    for name, member in inspect.getmembers(pkg):
        if name.startswith("_"):
            continue

        if inspect.isclass(member) and issubclass(member, InstrumentConfig) and member is not InstrumentConfig:
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
                
                if field_info.default is not PydanticUndefined and isinstance(field_info.default, str):
                    possible_device_types.add(field_info.default)

                for dt_str in possible_device_types:
                    if dt_str in registry and registry[dt_str] is not cls:
                        print(
                            f"Warning: Device type '{dt_str}' from {cls.__name__} conflicts with existing registration "
                            f"for {registry[dt_str].__name__}. Overwriting with {cls.__name__}."
                        )
                    registry[dt_str] = cls
    return registry


def get_model_registry() -> dict[str, Type[InstrumentConfig]]:
    global _MODEL_REGISTRY_CACHE
    if _MODEL_REGISTRY_CACHE is None:
        _MODEL_REGISTRY_CACHE = _discover_models()
    return _MODEL_REGISTRY_CACHE


def validate_profile(data: dict[str, Any], model_cls: Type[BaseModel]) -> None:
    """Validates profile data against the Pydantic model's JSON schema."""
    data_to_validate = data.copy()
    if 'simulation' in data_to_validate:
        data_to_validate.pop('simulation')
    try:
        schema = model_cls.model_json_schema()
        jsonschema.validate(instance=data_to_validate, schema=schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"Profile validation failed: {e.message}") from e
    except Exception as e:
        raise ValueError(f"An unexpected error occurred during profile validation: {e}") from e


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
            f"Profile with key '{key}' not found. "
            f"Looked for '{profile_path}'."
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
        raise TypeError(
            "Input must be a profile key (str), a Path object, or a dictionary."
        )

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

    # Pop the simulation section before validation, as it's not part of the config model
    if "simulation" in data:
        data.pop("simulation")

    try:
        validate_profile(data, model_cls)
        validated_model = model_cls.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise ValueError(f"Profile for device_type '{device_type}' is invalid: {e}") from e

    if not isinstance(validated_model, InstrumentConfig):
        raise TypeError(f"Validated model for {device_type} is not an instance of InstrumentConfig.")

    return validated_model