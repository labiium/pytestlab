"""
Schema Validation Utility for pytestlab

This module provides functionality to:
1. Output JSON schemas for given instrument types
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

from .dc_active_load_config import DCActiveLoadConfig
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
    instrument_type: str


class SchemaValidator:
    """Schema validation utility for instrument configurations."""

    # Mapping of instrument types to their configuration classes
    INSTRUMENT_MODELS = {
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

    def get_instrument_schema(self, instrument_type: str, format_output: bool = True) -> str:
        """
        Get the JSON schema for a given instrument type.

        Args:
            instrument_type: Type of instrument (e.g., 'oscilloscope', 'power_supply')
            format_output: Whether to format the JSON output with indentation

        Returns:
            JSON schema as a string

        Raises:
            ValueError: If instrument type is not supported
        """
        instrument_type = instrument_type.lower()

        if instrument_type not in self.INSTRUMENT_MODELS:
            available_types = ", ".join(self.INSTRUMENT_MODELS.keys())
            raise ValueError(
                f"Unsupported instrument type: {instrument_type}. "
                f"Available types: {available_types}"
            )

        model_class = self.INSTRUMENT_MODELS[instrument_type]

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
        self, yaml_file_path: str | Path, instrument_type: str | None = None
    ) -> ValidationResult:
        """
        Validate a YAML profile against the appropriate instrument schema.

        Args:
            yaml_file_path: Path to the YAML profile file
            instrument_type: Optional instrument type override

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
                instrument_type="",
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
                instrument_type="",
            )

        # Detect instrument type if not provided
        if instrument_type is None:
            instrument_type = self._detect_instrument_type(yaml_content)

        if not instrument_type:
            return ValidationResult(
                is_valid=False,
                errors=["Could not detect instrument type from YAML content"],
                warnings=[],
                schema_used="",
                instrument_type="",
            )

        # Get the appropriate model class
        if instrument_type not in self.INSTRUMENT_MODELS:
            return ValidationResult(
                is_valid=False,
                errors=[f"Unsupported instrument type: {instrument_type}"],
                warnings=[],
                schema_used="",
                instrument_type=instrument_type,
            )

        model_class = self.INSTRUMENT_MODELS[instrument_type]

        # Remove connection-specific fields from YAML content
        validation_content = self._remove_connection_fields_from_data(yaml_content)

        # Validate against the model
        try:
            model_class(**validation_content)
            return ValidationResult(
                is_valid=True,
                errors=[],
                warnings=[],
                schema_used=instrument_type,
                instrument_type=instrument_type,
            )
        except ValidationError as e:
            return ValidationResult(
                is_valid=False,
                errors=[str(error) for error in e.errors()],
                warnings=[],
                schema_used=instrument_type,
                instrument_type=instrument_type,
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Unexpected error during validation: {e}"],
                warnings=[],
                schema_used=instrument_type,
                instrument_type=instrument_type,
            )

    def _detect_instrument_type(self, yaml_content: dict[str, Any]) -> str | None:
        """
        Detect instrument type from YAML content.

        Args:
            yaml_content: Parsed YAML content

        Returns:
            Detected instrument type or None if detection fails
        """
        # Check for explicit device_type field
        if "device_type" in yaml_content:
            device_type = yaml_content["device_type"].lower()

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

    def list_supported_instruments(self) -> list[str]:
        """
        Get list of supported instrument types.

        Returns:
            List of supported instrument type names
        """
        return list(self.INSTRUMENT_MODELS.keys())

    def get_schema_info(self, instrument_type: str) -> dict[str, Any]:
        """
        Get information about a schema without the full schema content.

        Args:
            instrument_type: Type of instrument

        Returns:
            Dictionary with schema information
        """
        if instrument_type not in self.INSTRUMENT_MODELS:
            raise ValueError(f"Unsupported instrument type: {instrument_type}")

        model_class = self.INSTRUMENT_MODELS[instrument_type]

        return {
            "instrument_type": instrument_type,
            "model_class": model_class.__name__,
            "module": model_class.__module__,
            "description": model_class.__doc__ or "No description available",
        }
