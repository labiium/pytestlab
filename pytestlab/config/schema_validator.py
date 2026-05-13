"""
Schema Validation Utility for pytestlab

This module provides functionality to:
1. Output JSON schemas for given device types
2. Validate YAML profiles against appropriate schemas
3. Ignore connection-specific fields (serial_number, address) during validation

This module is designed to be imported and used by the main pytestlab CLI.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..devices.registry import get_config_model
from ..devices.registry import get_config_registry
from ..devices.registry import load_import_path
from ..devices.registry import validate_config_model
from .dc_active_load_config import DCActiveLoadConfig
from .device_config import GenericDeviceConfig
from .multimeter_config import MultimeterConfig
from .oscilloscope_config import OscilloscopeConfig
from .power_supply_config import PowerSupplyConfig
from .waveform_generator_config import WaveformGeneratorConfig


@dataclass
class ValidationResult:
    """Result of schema validation."""

    is_valid: bool
    errors: list[str]
    warnings: list[str]
    schema_used: str
    device_type: str


class SchemaValidator:
    """Schema validation utility for device configurations."""

    DEVICE_MODELS = {
        "oscilloscope": OscilloscopeConfig,
        "waveform_generator": WaveformGeneratorConfig,
        "power_supply": PowerSupplyConfig,
        "dc_active_load": DCActiveLoadConfig,
        "multimeter": MultimeterConfig,
        # Aliases for common names
        "awg": WaveformGeneratorConfig,
        "psu": PowerSupplyConfig,
        "dmm": MultimeterConfig,
        "electronic_load": DCActiveLoadConfig,
    }

    def __init__(self):
        """Initialize the schema validator."""
        self._schemas_cache = {}

    def get_device_schema(self, device_type: str, format_output: bool = True) -> str:
        """
        Get the JSON schema for a given device type.

        Args:
            device_type: Type of device (e.g., 'oscilloscope', 'power_supply')
            format_output: Whether to format the JSON output with indentation

        Returns:
            JSON schema as a string

        Raises:
            ValueError: If device type is not supported
        """
        device_type = device_type.lower()

        model_class = self._resolve_model_class(device_type)
        if model_class is None:
            available_types = ", ".join(self.list_supported_devices())
            raise ValueError(
                f"Unsupported device type: {device_type}. "
                f"Available types: {available_types}"
            )

        # Generate schema
        if hasattr(model_class, "model_json_schema"):
            schema = model_class.model_json_schema()
        elif hasattr(model_class, "schema"):
            schema = model_class.schema()
        else:
            raise ValueError(
                f"Model class {model_class.__name__} does not support schema generation"
            )

        # Remove connection-specific fields from schema
        schema = self._remove_connection_fields(schema)

        # Convert to string
        if format_output:
            return json.dumps(schema, indent=2)
        else:
            return json.dumps(schema)

    def validate_yaml_profile(
        self, yaml_file_path: str | Path, device_type: str | None = None
    ) -> ValidationResult:
        """
        Validate a YAML profile against the appropriate device schema.

        Args:
            yaml_file_path: Path to the YAML profile file
            device_type: Optional device type override

        Returns:
            ValidationResult with validation details
        """
        yaml_path = Path(yaml_file_path)

        if not yaml_path.exists():
            return ValidationResult(
                is_valid=False,
                errors=[f"YAML file not found: {yaml_file_path}"],
                warnings=[],
                schema_used="",
                device_type="",
            )

        try:
            # Load YAML content
            with open(yaml_path) as f:
                yaml_content = yaml.safe_load(f)
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Error loading YAML file: {e}"],
                warnings=[],
                schema_used="",
                device_type="",
            )

        if device_type is None:
            device_type = self._detect_device_type(yaml_content)

        if not device_type:
            return ValidationResult(
                is_valid=False,
                errors=["Could not detect device type from YAML content"],
                warnings=[],
                schema_used="",
                device_type="",
            )

        model_class = None
        config_model_path = yaml_content.get("config_model")
        if isinstance(config_model_path, str):
            model_class = validate_config_model(load_import_path(config_model_path), config_model_path)
        if model_class is None:
            model_class = self._resolve_model_class(device_type)
        if model_class is None and yaml_content.get("driver"):
            model_class = GenericDeviceConfig
        if model_class is None:
            return ValidationResult(
                is_valid=False,
                errors=[f"Unsupported device type: {device_type}"],
                warnings=[],
                schema_used="",
                device_type=device_type,
            )

        # Remove connection-specific fields from YAML content
        validation_content = self._remove_connection_fields_from_data(yaml_content)

        # Validate against the model
        try:
            model_class(**validation_content)
            return ValidationResult(
                is_valid=True,
                errors=[],
                warnings=[],
                schema_used=device_type,
                device_type=device_type,
            )
        except ValidationError as e:
            return ValidationResult(
                is_valid=False,
                errors=[str(error) for error in e.errors()],
                warnings=[],
                schema_used=device_type,
                device_type=device_type,
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Unexpected error during validation: {e}"],
                warnings=[],
                schema_used=device_type,
                device_type=device_type,
            )

    def _detect_device_type(self, yaml_content: dict[str, Any]) -> str | None:
        """
        Detect device type from YAML content.

        Args:
            yaml_content: Parsed YAML content

        Returns:
            Detected device type or None if detection fails
        """
        # Check for explicit device_type field
        if "device_type" in yaml_content:
            device_type = yaml_content["device_type"].lower()
            if self._resolve_model_class(device_type) is not None or yaml_content.get("driver"):
                return device_type

            # Map common device types to our supported types
            if device_type in ["oscilloscope", "scope"]:
                return "oscilloscope"
            elif device_type in ["waveform_generator", "awg", "function_generator"]:
                return "waveform_generator"
            elif device_type in ["power_supply", "psu", "power_source"]:
                return "power_supply"
            elif device_type in ["dc_active_load", "electronic_load", "load"]:
                return "dc_active_load"
            elif device_type in ["multimeter", "dmm", "voltmeter"]:
                return "multimeter"

        # Check for model-specific indicators
        model = yaml_content.get("model", "").lower()
        if any(keyword in model for keyword in ["scope", "oscilloscope", "dso"]):
            return "oscilloscope"
        elif any(keyword in model for keyword in ["awg", "waveform", "function"]):
            return "waveform_generator"
        elif any(keyword in model for keyword in ["psu", "power", "supply"]):
            return "power_supply"
        elif any(keyword in model for keyword in ["load", "electronic"]):
            return "dc_active_load"
        elif any(keyword in model for keyword in ["dmm", "multimeter", "voltmeter"]):
            return "multimeter"

        return None

    def _remove_connection_fields(self, schema: dict[str, Any]) -> dict[str, Any]:
        """
        Remove connection-specific fields from a schema.

        Args:
            schema: Schema dictionary to process

        Returns:
            Schema with connection fields removed
        """
        schema_copy = schema.copy()

        # Remove connection fields from properties if they exist
        if "properties" in schema_copy:
            connection_fields = ["serial_number", "address"]
            for field in connection_fields:
                if field in schema_copy["properties"]:
                    del schema_copy["properties"][field]

            # Remove from required fields if present
            if "required" in schema_copy:
                schema_copy["required"] = [
                    field for field in schema_copy["required"] if field not in connection_fields
                ]

        return schema_copy

    def _remove_connection_fields_from_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Remove connection-specific fields from YAML data.

        Args:
            data: YAML data dictionary to process

        Returns:
            Data with connection fields removed
        """
        data_copy = data.copy()

        # Remove connection fields
        connection_fields = ["serial_number", "address"]
        for field in connection_fields:
            if field in data_copy:
                del data_copy[field]

        return data_copy

    def list_supported_devices(self) -> list[str]:
        """
        Get list of supported device types.

        Returns:
            List of supported device type names
        """
        supported = set(self.DEVICE_MODELS.keys())
        supported.update(get_config_registry().keys())
        return sorted(supported)

    def get_schema_info(self, device_type: str) -> dict[str, Any]:
        """
        Get information about a schema without the full schema content.

        Args:
            device_type: Type of device

        Returns:
            Dictionary with schema information
        """
        model_class = self._resolve_model_class(device_type)
        if model_class is None:
            raise ValueError(f"Unsupported device type: {device_type}")

        return {
            "device_type": device_type,
            "model_class": model_class.__name__,
            "module": model_class.__module__,
            "description": model_class.__doc__ or "No description available",
        }

    def _resolve_model_class(self, device_type: str):
        device_type = device_type.lower()
        return self.DEVICE_MODELS.get(device_type) or get_config_model(device_type)
