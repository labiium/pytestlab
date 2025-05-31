from __future__ import annotations

import importlib # Changed from 'from importlib import import_module' for consistency
import inspect
from pathlib import Path
from typing import Any, Type, Literal, Union # Added Literal, Union
import typing # For get_origin, get_args
import yaml
from pydantic import BaseModel, PydanticUndefined # Added PydanticUndefined
from pydantic.fields import FieldInfo # Added FieldInfo

from .instrument_config import InstrumentConfig


# Global cache for discovered models to avoid re-discovering on every call
_MODEL_REGISTRY_CACHE: dict[str, Type[InstrumentConfig]] | None = None # Changed Type[BaseModel] to Type[InstrumentConfig]


def _discover_models() -> dict[str, Type[InstrumentConfig]]: # Changed return type
    pkg = importlib.import_module("pytestlab.config")
    registry: dict[str, Type[InstrumentConfig]] = {}

    for name, member in inspect.getmembers(pkg):
        if name.startswith("_"):
            continue

        if inspect.isclass(member) and issubclass(member, InstrumentConfig) and member is not InstrumentConfig:
            cls = member # member is a class, a subclass of InstrumentConfig, but not InstrumentConfig itself
            
            if "device_type" in cls.model_fields:
                field_info: FieldInfo = cls.model_fields["device_type"]
                
                possible_device_types = set()

                annotation = field_info.annotation
                
                # Handle Optional[Literal["a", "b"]] by checking Union types
                origin_annotation = typing.get_origin(annotation)
                args_annotation = typing.get_args(annotation)

                if origin_annotation is Union: # Covers Optional[Literal[...]]
                    for union_arg in args_annotation:
                        # Check if this part of the Union is a Literal
                        if typing.get_origin(union_arg) is Literal:
                            for literal_val in typing.get_args(union_arg):
                                if isinstance(literal_val, str):
                                    possible_device_types.add(literal_val)
                            # Assuming only one Literal in an Optional[Literal[...]] construct for device_type
                elif origin_annotation is Literal:
                     for literal_val in args_annotation:
                        if isinstance(literal_val, str):
                            possible_device_types.add(literal_val)
                
                # Also consider the default value of the field if it's a string
                # This covers cases like `device_type: str = Field("default_type", ...)`
                # or `device_type: Literal["a", "b"] = Field("a", ...)`
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


def get_model_registry() -> dict[str, Type[InstrumentConfig]]: # Changed return type
    global _MODEL_REGISTRY_CACHE
    if _MODEL_REGISTRY_CACHE is None:
        _MODEL_REGISTRY_CACHE = _discover_models()
    return _MODEL_REGISTRY_CACHE


def load_profile(key_or_path_or_dict: str | Path | dict[str, Any]) -> InstrumentConfig:
    """
    Loads an instrument profile from a key, file path, or dictionary.
    This is the single entry-point for loading profiles.
    Drivers should never read YAML themselves.
    """
    data: dict[str, Any]

    if isinstance(key_or_path_or_dict, dict):
        data = key_or_path_or_dict
    elif isinstance(key_or_path_or_dict, Path):
        with open(key_or_path_or_dict, 'r') as f:
            data = yaml.safe_load(f)
    elif isinstance(key_or_path_or_dict, str):
        # Assuming 'key' refers to a filename (without .yaml) in a predefined profile directory
        # This part might need adjustment based on how profile keys are resolved to file paths.
        # For example, if keys like "keysight/DSOX1204G" map to
        # "pytestlab/profiles/keysight/DSOX1204G.yaml"
        # This logic needs to be robust. For now, a simple placeholder:
        # This assumes keys are direct filenames in a specific profiles directory.
        # You'll need to define PROFILE_DIR_BASE_PATH or have a more sophisticated lookup.

        # Placeholder for profile key resolution logic:
        # This needs to be adapted to how your project resolves profile keys to paths.
        # Example: search in 'pytestlab/profiles/' + key + '.yaml'
        # or 'pytestlab/profiles/' + key.replace("/", os.path.sep) + '.yaml'

        # For now, let's assume the key might be a path string or a simple key.
        # If it looks like a path, treat it as one.
        potential_path = Path(key_or_path_or_dict)
        if potential_path.suffix in ['.yaml', '.yml'] and potential_path.is_file():
            with open(potential_path, 'r') as f:
                data = yaml.safe_load(f)
        else:
            # This is where the key-to-path logic would go.
            # For now, we'll raise an error if it's not a dict or valid path.
            # This part needs to be fully implemented based on project conventions.
            # Example:
            # profile_path = resolve_profile_key_to_path(key_or_path_or_dict)
            # with open(profile_path, 'r') as f:
            #     data = yaml.safe_load(f)
            raise NotImplementedError(
                f"Profile key resolution for '{key_or_path_or_dict}' is not fully implemented. "
                "Please provide a direct path or a dictionary."
            )
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

    # Using Pydantic V2's model_validate
    # The return type should be InstrumentConfig, so we assume model_cls will be
    # a subtype of InstrumentConfig or InstrumentConfig itself.
    validated_model = model_cls.model_validate(data)
    if not isinstance(validated_model, InstrumentConfig):
        # This check ensures type safety if InstrumentConfig is a base for various device configs.
        # If all models are expected to be InstrumentConfig instances directly, this might be redundant
        # but serves as a good safeguard.
        raise TypeError(f"Validated model for {device_type} is not an instance of InstrumentConfig.")

    return validated_model