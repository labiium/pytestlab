"""
SCPI Command Validation Utilities

This module provides utilities to validate that required SCPI commands
are present in the configuration for specific functionality.
"""

import re
from dataclasses import dataclass
from typing import Any

from .instrument_config import SCPICommandSpec
from .instrument_config import SCPIParameterSpec


@dataclass
class SCPIValidationResult:
    """Result of SCPI command validation."""

    is_valid: bool
    missing_commands: list[str]
    warnings: list[str]
    errors: list[str]


@dataclass
class SCPIArgumentValidationResult:
    """Result of SCPI argument validation."""

    is_valid: bool
    missing_parameters: list[str]
    invalid_parameters: list[str]
    warnings: list[str]
    errors: list[str]


class SCPIValidator:
    """Validates SCPI command requirements against configuration."""

    @staticmethod
    def extract_parameters_from_template(template: str) -> list[str]:
        """
        Extract parameter names from a SCPI command template.

        Args:
            template: SCPI command template string (e.g., ":CHANnel{channel}:SCALe {scale}")

        Returns:
            List of parameter names found in the template
        """
        if not template:
            return []

        # Find all {parameter} placeholders
        pattern = r"\{([^}]+)\}"
        parameters = re.findall(pattern, template)
        return parameters

    @staticmethod
    def extract_parameters_from_sequence(sequence: list[str]) -> list[str]:
        """
        Extract parameter names from a sequence of SCPI commands.

        Args:
            sequence: List of SCPI command strings

        Returns:
            List of unique parameter names found in the sequence
        """
        if not sequence:
            return []

        all_parameters = []
        for cmd in sequence:
            params = SCPIValidator.extract_parameters_from_template(cmd)
            all_parameters.extend(params)

        # Remove duplicates while preserving order
        unique_params = []
        for param in all_parameters:
            if param not in unique_params:
                unique_params.append(param)

        return unique_params

    @staticmethod
    def validate_command_arguments(
        command_spec: SCPICommandSpec, command_name: str
    ) -> SCPIArgumentValidationResult:
        """
        Validate that a SCPI command has proper parameter specifications.

        Args:
            command_spec: The SCPI command specification
            command_name: Name of the command being validated

        Returns:
            SCPIArgumentValidationResult with validation details
        """
        result = SCPIArgumentValidationResult(
            is_valid=True, missing_parameters=[], invalid_parameters=[], warnings=[], errors=[]
        )

        # Check if command has parameters defined
        if not hasattr(command_spec, "parameters") or not command_spec.parameters:
            result.warnings.append(f"No parameters defined for command '{command_name}'")
            return result

        # Extract required parameters from template/sequence
        required_params = []
        if hasattr(command_spec, "template") and command_spec.template:
            required_params = SCPIValidator.extract_parameters_from_template(command_spec.template)
        elif hasattr(command_spec, "sequence") and command_spec.sequence:
            required_params = SCPIValidator.extract_parameters_from_sequence(command_spec.sequence)

        if not required_params:
            result.warnings.append(
                f"No parameters found in template/sequence for command '{command_name}'"
            )
            return result

        # Check if all required parameters are defined
        defined_params = set(command_spec.parameters.keys())
        missing_params = [param for param in required_params if param not in defined_params]

        if missing_params:
            result.missing_parameters = missing_params
            result.is_valid = False
            result.errors.append(
                f"Missing parameter definitions for command '{command_name}': {missing_params}"
            )

        # Validate each parameter specification
        for param_name, param_spec in command_spec.parameters.items():
            param_errors = SCPIValidator._validate_parameter_spec(param_spec, param_name)
            if param_errors:
                result.invalid_parameters.extend(param_errors)
                result.is_valid = False

        return result

    @staticmethod
    def _validate_parameter_spec(param_spec: SCPIParameterSpec, param_name: str) -> list[str]:
        """
        Validate a single parameter specification.

        Args:
            param_spec: The parameter specification to validate
            param_name: Name of the parameter being validated

        Returns:
            List of validation error messages
        """
        errors = []

        # Check required fields
        if not hasattr(param_spec, "name") or not param_spec.name:
            errors.append(f"Parameter '{param_name}' missing name attribute")

        if not hasattr(param_spec, "type") or not param_spec.type:
            errors.append(f"Parameter '{param_name}' missing type attribute")

        if not hasattr(param_spec, "required"):
            errors.append(f"Parameter '{param_name}' missing required attribute")

        # Check type-specific validations
        if hasattr(param_spec, "type") and param_spec.type:
            if param_spec.type == "int":
                if (
                    hasattr(param_spec, "min_value")
                    and param_spec.min_value is not None
                    and hasattr(param_spec, "max_value")
                    and param_spec.max_value is not None
                ):
                    if param_spec.min_value >= param_spec.max_value:
                        errors.append(
                            f"Parameter '{param_name}' has invalid range: "
                            f"min_value ({param_spec.min_value}) >= max_value ({param_spec.max_value})"
                        )

            elif param_spec.type == "float":
                if (
                    hasattr(param_spec, "min_value")
                    and param_spec.min_value is not None
                    and hasattr(param_spec, "max_value")
                    and param_spec.max_value is not None
                ):
                    if param_spec.min_value >= param_spec.max_value:
                        errors.append(
                            f"Parameter '{param_name}' has invalid range: "
                            f"min_value ({param_spec.min_value}) >= max_value ({param_spec.max_value})"
                        )

            elif param_spec.type == "enum":
                if not hasattr(param_spec, "values") or not param_spec.values:
                    errors.append(f"Parameter '{param_name}' of type 'enum' missing values list")

        return errors

    @staticmethod
    def validate_feature_requirements(
        config: Any,
        feature_name: str,
        required_commands: list[str],
        scpi_section: dict[str, Any] | None = None,
    ) -> SCPIValidationResult:
        """
        Validate that required SCPI commands are present for a specific feature.

        Args:
            config: Configuration object containing SCPI sections
            feature_name: Name of the feature being validated
            required_commands: List of required SCPI command names
            scpi_section: Optional SCPI section to validate against

        Returns:
            SCPIValidationResult with validation details
        """
        result = SCPIValidationResult(is_valid=True, missing_commands=[], warnings=[], errors=[])

        # If no SCPI section provided, try to get it from config
        if scpi_section is None:
            if hasattr(config, "scpi_commands"):
                scpi_section = config.scpi_commands
            else:
                result.is_valid = False
                result.errors.append(f"No SCPI section found for {feature_name}")
                return result

        # Collect all available commands
        available_commands = set()

        # Check direct commands
        if "commands" in scpi_section:
            available_commands.update(scpi_section["commands"].keys())

        # Check queries
        if "queries" in scpi_section:
            available_commands.update(scpi_section["queries"].keys())

        # Check variants
        if "variants" in scpi_section:
            for _variant_name, variant_data in scpi_section["variants"].items():
                if "commands" in variant_data:
                    available_commands.update(variant_data["commands"].keys())
                if "queries" in variant_data:
                    available_commands.update(variant_data["queries"].keys())

        # Find missing commands
        missing = [cmd for cmd in required_commands if cmd not in available_commands]

        if missing:
            result.missing_commands = missing
            result.is_valid = False
            result.errors.append(f"Missing required SCPI commands for {feature_name}: {missing}")
        else:
            result.warnings.append(f"All required SCPI commands present for {feature_name}")

        return result

    @staticmethod
    def validate_scpi_command_specifications(
        scpi_section: Any,
    ) -> dict[str, SCPIArgumentValidationResult]:
        """
        Validate all SCPI command specifications in a section.

        Args:
            scpi_section: The SCPI section to validate

        Returns:
            Dictionary mapping command names to validation results
        """
        results = {}

        # Validate commands
        if hasattr(scpi_section, "commands") and scpi_section.commands:
            for cmd_name, cmd_spec in scpi_section.commands.items():
                if isinstance(cmd_spec, SCPICommandSpec):
                    results[cmd_name] = SCPIValidator.validate_command_arguments(cmd_spec, cmd_name)

        # Validate queries
        if hasattr(scpi_section, "queries") and scpi_section.queries:
            for cmd_name, cmd_spec in scpi_section.queries.items():
                if isinstance(cmd_spec, SCPICommandSpec):
                    results[cmd_name] = SCPIValidator.validate_command_arguments(cmd_spec, cmd_name)

        # Validate variants
        if hasattr(scpi_section, "variants") and scpi_section.variants:
            for variant_name, variant_data in scpi_section.variants.items():
                variant_results = SCPIValidator.validate_scpi_command_specifications(variant_data)
                # Prefix variant name to command names
                for cmd_name, result in variant_results.items():
                    results[f"{variant_name}.{cmd_name}"] = result

        return results

    @staticmethod
    def validate_oscilloscope_config(config: Any) -> dict[str, SCPIValidationResult]:
        """
        Validate all SCPI command requirements for an oscilloscope configuration.

        Args:
            config: OscilloscopeConfig instance

        Returns:
            Dictionary mapping feature names to validation results
        """
        results = {}

        # Validate core functionality
        if hasattr(config, "core_scpi_commands"):
            results["core"] = SCPIValidator.validate_feature_requirements(
                config, "core functionality", config.core_scpi_commands
            )

        # Validate channel functionality
        if hasattr(config, "channel_scpi_commands"):
            results["channels"] = SCPIValidator.validate_feature_requirements(
                config, "channel operations", config.channel_scpi_commands
            )

        # Validate trigger functionality
        if hasattr(config, "trigger_scpi_commands"):
            results["trigger"] = SCPIValidator.validate_feature_requirements(
                config, "trigger operations", config.trigger_scpi_commands
            )

        # Validate acquisition functionality
        if hasattr(config, "acquisition_scpi_commands"):
            results["acquisition"] = SCPIValidator.validate_feature_requirements(
                config, "acquisition operations", config.acquisition_scpi_commands
            )

        # Validate measurement functionality
        if hasattr(config, "measurement_scpi_commands"):
            results["measurements"] = SCPIValidator.validate_feature_requirements(
                config, "measurement operations", config.measurement_scpi_commands
            )

        # Validate math functionality
        if hasattr(config, "math_scpi_commands"):
            results["math"] = SCPIValidator.validate_feature_requirements(
                config, "math operations", config.math_scpi_commands
            )

        # Validate cursor functionality
        if hasattr(config, "cursor_scpi_commands"):
            results["cursors"] = SCPIValidator.validate_feature_requirements(
                config, "cursor operations", config.cursor_scpi_commands
            )

        # Validate display functionality
        if hasattr(config, "display_scpi_commands"):
            results["display"] = SCPIValidator.validate_feature_requirements(
                config, "display operations", config.display_scpi_commands
            )

        # Validate system functionality
        if hasattr(config, "system_scpi_commands"):
            results["system"] = SCPIValidator.validate_feature_requirements(
                config, "system operations", config.system_scpi_commands
            )

        return results

    @staticmethod
    def validate_waveform_generator_config(config: Any) -> dict[str, SCPIValidationResult]:
        """
        Validate all SCPI command requirements for a waveform generator configuration.

        Args:
            config: WaveformGeneratorConfig instance

        Returns:
            Dictionary mapping feature names to validation results
        """
        results = {}

        # Validate core functionality
        if hasattr(config, "core_scpi_commands"):
            results["core"] = SCPIValidator.validate_feature_requirements(
                config, "core functionality", config.core_scpi_commands
            )

        # Validate channel functionality
        if hasattr(config, "channel_scpi_commands"):
            results["channels"] = SCPIValidator.validate_feature_requirements(
                config, "channel operations", config.channel_scpi_commands
            )

        # Validate waveform functionality
        if hasattr(config, "waveform_scpi_commands"):
            results["waveforms"] = SCPIValidator.validate_feature_requirements(
                config, "waveform operations", config.waveform_scpi_commands
            )

        # Validate modulation functionality
        if hasattr(config, "modulation_scpi_commands"):
            results["modulation"] = SCPIValidator.validate_feature_requirements(
                config, "modulation operations", config.modulation_scpi_commands
            )

        # Validate sweep functionality
        if hasattr(config, "sweep_scpi_commands"):
            results["sweep"] = SCPIValidator.validate_feature_requirements(
                config, "sweep operations", config.sweep_scpi_commands
            )

        # Validate burst functionality
        if hasattr(config, "burst_scpi_commands"):
            results["burst"] = SCPIValidator.validate_feature_requirements(
                config, "burst operations", config.burst_scpi_commands
            )

        # Validate system functionality
        if hasattr(config, "system_scpi_commands"):
            results["system"] = SCPIValidator.validate_feature_requirements(
                config, "system operations", config.system_scpi_commands
            )

        return results

    @staticmethod
    def validate_power_supply_config(config: Any) -> dict[str, SCPIValidationResult]:
        """
        Validate all SCPI command requirements for a power supply configuration.

        Args:
            config: PowerSupplyConfig instance

        Returns:
            Dictionary mapping feature names to validation results
        """
        results = {}

        # Validate core functionality
        if hasattr(config, "core_scpi_commands"):
            results["core"] = SCPIValidator.validate_feature_requirements(
                config, "core functionality", config.core_scpi_commands
            )

        # Validate channel functionality
        if hasattr(config, "channel_scpi_commands"):
            results["channels"] = SCPIValidator.validate_feature_requirements(
                config, "channel operations", config.channel_scpi_commands
            )

        # Validate output functionality
        if hasattr(config, "output_scpi_commands"):
            results["output"] = SCPIValidator.validate_feature_requirements(
                config, "output operations", config.output_scpi_commands
            )

        # Validate protection functionality
        if hasattr(config, "protection_scpi_commands"):
            results["protection"] = SCPIValidator.validate_feature_requirements(
                config, "protection operations", config.protection_scpi_commands
            )

        # Validate measurement functionality
        if hasattr(config, "measurement_scpi_commands"):
            results["measurements"] = SCPIValidator.validate_feature_requirements(
                config, "measurement operations", config.measurement_scpi_commands
            )

        # Validate system functionality
        if hasattr(config, "system_scpi_commands"):
            results["system"] = SCPIValidator.validate_feature_requirements(
                config, "system operations", config.system_scpi_commands
            )

        return results

    @staticmethod
    def validate_dc_active_load_config(config: Any) -> dict[str, SCPIValidationResult]:
        """
        Validate all SCPI command requirements for a DC active load configuration.

        Args:
            config: DCActiveLoadConfig instance

        Returns:
            Dictionary mapping feature names to validation results
        """
        results = {}

        # Validate core functionality
        if hasattr(config, "core_scpi_commands"):
            results["core"] = SCPIValidator.validate_feature_requirements(
                config, "core functionality", config.core_scpi_commands
            )

        # Validate channel functionality
        if hasattr(config, "channel_scpi_commands"):
            results["channels"] = SCPIValidator.validate_feature_requirements(
                config, "channel operations", config.channel_scpi_commands
            )

        # Validate load functionality
        if hasattr(config, "load_scpi_commands"):
            results["load"] = SCPIValidator.validate_feature_requirements(
                config, "load operations", config.load_scpi_commands
            )

        # Validate protection functionality
        if hasattr(config, "protection_scpi_commands"):
            results["protection"] = SCPIValidator.validate_feature_requirements(
                config, "protection operations", config.protection_scpi_commands
            )

        # Validate measurement functionality
        if hasattr(config, "measurement_scpi_commands"):
            results["measurements"] = SCPIValidator.validate_feature_requirements(
                config, "measurement operations", config.measurement_scpi_commands
            )

        # Validate system functionality
        if hasattr(config, "system_scpi_commands"):
            results["system"] = SCPIValidator.validate_feature_requirements(
                config, "system operations", config.system_scpi_commands
            )

        return results

    @staticmethod
    def validate_multimeter_config(config: Any) -> dict[str, SCPIValidationResult]:
        """
        Validate all SCPI command requirements for a multimeter configuration.

        Args:
            config: MultimeterConfig instance

        Returns:
            Dictionary mapping feature names to validation results
        """
        results = {}

        # Validate core functionality
        if hasattr(config, "core_scpi_commands"):
            results["core"] = SCPIValidator.validate_feature_requirements(
                config, "core functionality", config.core_scpi_commands
            )

        # Validate measurement functionality
        if hasattr(config, "measurement_scpi_commands"):
            results["measurements"] = SCPIValidator.validate_feature_requirements(
                config, "measurement operations", config.measurement_scpi_commands
            )

        # Validate range functionality
        if hasattr(config, "range_scpi_commands"):
            results["ranges"] = SCPIValidator.validate_feature_requirements(
                config, "range operations", config.range_scpi_commands
            )

        # Validate trigger functionality
        if hasattr(config, "trigger_scpi_commands"):
            results["trigger"] = SCPIValidator.validate_feature_requirements(
                config, "trigger operations", config.trigger_scpi_commands
            )

        # Validate calibration functionality
        if hasattr(config, "calibration_scpi_commands"):
            results["calibration"] = SCPIValidator.validate_feature_requirements(
                config, "calibration operations", config.calibration_scpi_commands
            )

        # Validate system functionality
        if hasattr(config, "system_scpi_commands"):
            results["system"] = SCPIValidator.validate_feature_requirements(
                config, "system operations", config.system_scpi_commands
            )

        return results

    @staticmethod
    def validate_instrument_config(config: Any) -> dict[str, SCPIValidationResult]:
        """
        Automatically detect instrument type and validate SCPI command requirements.

        Args:
            config: Any instrument configuration instance

        Returns:
            Dictionary mapping feature names to validation results
        """
        # Try to detect instrument type based on class name or attributes
        config_class = config.__class__.__name__

        if "Oscilloscope" in config_class:
            return SCPIValidator.validate_oscilloscope_config(config)
        elif "WaveformGenerator" in config_class:
            return SCPIValidator.validate_waveform_generator_config(config)
        elif "PowerSupply" in config_class:
            return SCPIValidator.validate_power_supply_config(config)
        elif "DCActiveLoad" in config_class:
            return SCPIValidator.validate_dc_active_load_config(config)
        elif "Multimeter" in config_class:
            return SCPIValidator.validate_multimeter_config(config)
        else:
            # Generic validation for unknown instrument types
            results = {}
            if hasattr(config, "scpi_commands"):
                results["generic"] = SCPIValidator.validate_feature_requirements(
                    config, "generic functionality", [], config.scpi_commands
                )
            return results

    @staticmethod
    def generate_feature_mapping_template() -> dict[str, list[str]]:
        """
        Generate a template for feature→SCPI mappings based on the DSOX1204G.scpi.json.

        Returns:
            Dictionary mapping feature names to SCPI command lists
        """
        return {
            "core_functionality": ["acquire_points", "set_channel_axis", "get_time_axis"],
            "channel_operations": ["channel_display", "probe_set"],
            "trigger_operations": ["configure_trigger"],
            "acquisition_operations": ["set_acquisition_mode", "get_acquisition_status"],
            "measurement_operations": ["configure_measurement", "get_measurement_value"],
            "math_operations": ["set_math_function", "get_math_result"],
            "cursor_operations": ["set_cursor_position", "get_cursor_value"],
            "display_operations": ["set_display_brightness", "get_display_status"],
            "system_operations": ["set_system_setting", "get_system_info"],
        }

    @staticmethod
    def load_scpi_file(scpi_file_path: str) -> dict[str, Any]:
        """
        Load and parse a SCPI JSON file.

        Args:
            scpi_file_path: Path to the SCPI JSON file

        Returns:
            Parsed SCPI data as a dictionary
        """
        import json

        try:
            with open(scpi_file_path) as f:
                scpi_data = json.load(f)
            return scpi_data
        except FileNotFoundError:
            raise FileNotFoundError(f"SCPI file not found: {scpi_file_path}") from None
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in SCPI file: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Error loading SCPI file: {e}") from e

    @staticmethod
    def validate_scpi_file_against_config(
        scpi_file_path: str, config: Any
    ) -> dict[str, SCPIValidationResult]:
        """
        Validate a SCPI file against a configuration object.

        Args:
            scpi_file_path: Path to the SCPI JSON file
            config: Configuration object to validate against

        Returns:
            Dictionary mapping feature names to validation results
        """
        # Load SCPI file
        SCPIValidator.load_scpi_file(scpi_file_path)

        # Validate against config
        return SCPIValidator.validate_instrument_config(config)
