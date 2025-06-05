from __future__ import annotations
import yaml
from pathlib import Path
from typing import Union, Dict, Any
from .bench_config import BenchConfigExtended

def load_bench_yaml(path_or_dict: Union[str, Path, dict]) -> BenchConfigExtended:
    """Load and validate a bench configuration from a YAML file or dictionary."""
    if isinstance(path_or_dict, (str, Path)):
        with open(path_or_dict, "r") as f:
            data = yaml.safe_load(f)
    elif isinstance(path_or_dict, dict):
        data = path_or_dict
    else:
        raise TypeError("Input must be a path or dict.")
    config = BenchConfigExtended.model_validate(data)
    return config

def build_validation_context(config: BenchConfigExtended) -> Dict[str, Any]:
    """Build a context dictionary for custom validation expressions."""
    context = {}
    for alias, entry in config.instruments.items():
        context[alias] = entry.model_dump()
    context["experiment"] = config.experiment.model_dump() if config.experiment else {}
    return context

def run_custom_validations(config: BenchConfigExtended, context: dict) -> None:
    """Run custom validation expressions and raise ValueError if any fail."""
    if not config.custom_validations:
        return
    for expr in config.custom_validations:
        try:
            if not eval(expr, {}, context):
                raise ValueError(f"Custom validation failed: {expr}")
        except Exception as e:
            raise ValueError(f"Error evaluating custom validation '{expr}': {e}")
