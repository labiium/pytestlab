from __future__ import annotations

# -*- coding: utf-8 -*-
"""
Module providing a high-level interface for Keysight EDU33210 Series
Trueform Arbitrary Waveform Generators.
"""

import re
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, Type, Self
from pydantic import validate_call # Added validate_call

import numpy as np

from .instrument import Instrument
from ..config import WaveformGeneratorConfig # This is V2 config
from ..errors import (
    InstrumentCommunicationError,
    InstrumentConfigurationError,
    InstrumentParameterError,
)
from ..common.enums import ( # Added Enums
    SCPIOnOff,
    WaveformType,
    OutputLoadImpedance,
    OutputPolarity,
    VoltageUnit,
    TriggerSlope,
    TriggerSource,
    SyncMode,
    ModulationSource,
    ArbFilterType,
    ArbAdvanceMode,
    SweepSpacing,
    BurstMode,
)

# Forward declarations for type hints within facade classes
class WaveformGenerator:
    pass

class WGChannelFacade:
    def __init__(self, wg: 'WaveformGenerator', channel_num: int):
        self._wg = wg
        self._channel = channel_num

    @validate_call
    def setup_sine(self, frequency: float, amplitude: float, offset: float = 0.0, phase: Optional[float] = None) -> Self:
        self._wg.set_function(self._channel, WaveformType.SINE)
        self._wg.set_frequency(self._channel, frequency)
        self._wg.set_amplitude(self._channel, amplitude)
        self._wg.set_offset(self._channel, offset)
        if phase is not None:
            self._wg.set_phase(self._channel, phase)
        return self

    @validate_call
    def setup_square(self, frequency: float, amplitude: float, offset: float = 0.0, duty_cycle: float = 50.0, phase: Optional[float] = None) -> Self:
        self._wg.set_function(self._channel, WaveformType.SQUARE, duty_cycle=duty_cycle)
        self._wg.set_frequency(self._channel, frequency)
        self._wg.set_amplitude(self._channel, amplitude)
        self._wg.set_offset(self._channel, offset)
        if phase is not None:
            self._wg.set_phase(self._channel, phase)
        return self

    @validate_call
    def setup_ramp(self, frequency: float, amplitude: float, offset: float = 0.0, symmetry: float = 50.0, phase: Optional[float] = None) -> Self:
        self._wg.set_function(self._channel, WaveformType.RAMP, symmetry=symmetry)
        self._wg.set_frequency(self._channel, frequency)
        self._wg.set_amplitude(self._channel, amplitude)
        self._wg.set_offset(self._channel, offset)
        if phase is not None:
            self._wg.set_phase(self._channel, phase)
        return self

    @validate_call
    def setup_pulse(self, frequency: float, amplitude: float, offset: float = 0.0, width: Optional[float] = None, duty_cycle: Optional[float] = None, transition_both: Optional[float] = None, phase: Optional[float] = None) -> Self:
        period = 1.0 / frequency if frequency > 0 else OutputLoadImpedance.MAXIMUM

        pulse_params = {"period": period}
        if width is not None:
            pulse_params["width"] = width
        elif duty_cycle is not None:
            pulse_params["duty_cycle"] = duty_cycle
        else:
            pulse_params["duty_cycle"] = 50.0

        if transition_both is not None:
            pulse_params["transition_both"] = transition_both

        self._wg.set_function(self._channel, WaveformType.PULSE, **pulse_params)
        self._wg.set_amplitude(self._channel, amplitude)
        self._wg.set_offset(self._channel, offset)
        if phase is not None:
            self._wg.set_phase(self._channel, phase)
        return self

    @validate_call
    def setup_arbitrary(self, arb_name: str, sample_rate: float, amplitude: float, offset: float = 0.0, phase: Optional[float] = None) -> Self:
        self._wg.set_function(self._channel, WaveformType.ARB)
        self._wg.select_arbitrary_waveform(self._channel, arb_name)
        self._wg.set_arbitrary_waveform_sample_rate(self._channel, sample_rate)
        self._wg.set_amplitude(self._channel, amplitude)
        self._wg.set_offset(self._channel, offset)
        if phase is not None:
            self._wg.set_phase(self._channel, phase)
        return self

    @validate_call
    def setup_dc(self, offset: float) -> Self:
        self._wg.set_function(self._channel, WaveformType.DC)
        self._wg.set_offset(self._channel, offset)
        return self

    @validate_call
    def enable(self) -> Self:
        self._wg.set_output_state(self._channel, SCPIOnOff.ON)
        return self

    @validate_call
    def disable(self) -> Self:
        self._wg.set_output_state(self._channel, SCPIOnOff.OFF)
        return self

    @validate_call
    def set_load_impedance(self, impedance: Union[float, OutputLoadImpedance, str]) -> Self:
        self._wg.set_output_load_impedance(self._channel, impedance)
        return self

    @validate_call
    def set_voltage_unit(self, unit: VoltageUnit) -> Self:
        self._wg.set_voltage_unit(self._channel, unit)
        return self


# Old constants for SCPI Parameters (lines 25-168) are removed as they are replaced by Enums.

# --- Data Classes ---
@dataclass
class WaveformConfigResult:
    """
    Data class storing the retrieved waveform configuration of a channel.

    Provides a structured way to access key parameters of the channel's current state,
    obtained by querying multiple SCPI commands.

    Attributes:
        channel (int): The channel number (1 or 2).
        function (str): The short SCPI name of the active waveform function (e.g., "SIN", "RAMP").
        frequency (float): The current frequency in Hz (or sample rate in Sa/s for ARB).
        amplitude (float): The current amplitude in the configured voltage units.
        offset (float): The current DC offset voltage in Volts.
        phase (Optional[float]): The current phase offset in the configured angle units (None if not applicable).
        symmetry (Optional[float]): The current symmetry percentage for RAMP/TRIANGLE (None otherwise).
        duty_cycle (Optional[float]): The current duty cycle percentage for SQUARE/PULSE (None otherwise).
        output_state (Optional[bool]): The current state of the main output (True=ON, False=OFF).
        load_impedance (Optional[Union[float, str]]): The configured load impedance (Ohms or "INFinity").
        voltage_unit (Optional[str]): The currently configured voltage unit ("VPP", "VRMS", "DBM").

    Note:
        Consider adding fields for active modulation/sweep/burst state if needed.
    """
    channel: int
    function: str
    frequency: float
    amplitude: float
    offset: float
    phase: Optional[float] = None
    symmetry: Optional[float] = None
    duty_cycle: Optional[float] = None
    output_state: Optional[bool] = None
    load_impedance: Optional[Union[float, str]] = None
    voltage_unit: Optional[str] = None

@dataclass
class FileSystemInfo:
    """
    Data class representing the results of a directory listing query (`list_directory`).

    Contains information about memory usage and the files/folders found in the queried path.

    Attributes:
        bytes_used (int): Total bytes used on the specified memory volume (INT or USB).
        bytes_free (int): Total bytes free on the specified memory volume.
        files (List[Dict[str, Any]]): A list of dictionaries, each representing a file or folder.
                                      Example entry: `{'name': 'f.txt', 'type': 'FILE', 'size': 1024}`.
                                      Type might be 'FILE', 'FOLDER', 'ARB', 'STAT', etc., depending on the file
                                      extension and instrument response. Size is in bytes.
    """
    bytes_used: int
    bytes_free: int
    files: List[Dict[str, Any]] = field(default_factory=list)


# --- Function Parameter Mapping ---
# Maps short SCPI function names to supported keyword args and SCPI command lambdas.
# Used by set_function to apply function-specific parameters.
# Maps WaveformType enum members to supported keyword args and SCPI command lambdas.
# Used by set_function to apply function-specific parameters.
WAVEFORM_PARAM_COMMANDS: Dict[WaveformType, Dict[str, Callable[[int, Any], str]]] = {
    WaveformType.PULSE: {
        "duty_cycle": lambda ch, v_float: f"SOUR{ch}:FUNC:PULS:DCYCle {v_float}",
        "period": lambda ch, v_float: f"SOUR{ch}:FUNC:PULS:PERiod {v_float}",
        "width": lambda ch, v_float: f"SOUR{ch}:FUNC:PULS:WIDTh {v_float}",
        "transition_both": lambda ch, v_float: f"SOUR{ch}:FUNC:PULS:TRANsition:BOTH {v_float}",
        "transition_leading": lambda ch, v_float: f"SOUR{ch}:FUNC:PULS:TRANsition:LEADing {v_float}",
        "transition_trailing": lambda ch, v_float: f"SOUR{ch}:FUNC:PULS:TRANsition:TRAiling {v_float}",
        "hold_mode": lambda ch, v_str_hold: f"SOUR{ch}:FUNC:PULS:HOLD {v_str_hold.upper()}", # Expects "WIDT" or "DCYC" string
    },
    WaveformType.SQUARE: {
        "duty_cycle": lambda ch, v_float: f"SOUR{ch}:FUNC:SQUare:DCYCle {v_float}",
        "period": lambda ch, v_float: f"SOUR{ch}:FUNC:SQUare:PERiod {v_float}",
    },
    WaveformType.RAMP: {
        "symmetry": lambda ch, v_float: f"SOUR{ch}:FUNC:RAMP:SYMMetry {v_float}",
    },
    # TRIANGLE is often an alias for RAMP with 50% symmetry. If it's a distinct SCPI func, add to WaveformType.
    # For now, assuming RAMP symmetry covers TRIANGLE if it's the same SCPI command.
    WaveformType.SINE: {},
    # PRBS is not in WaveformType enum. If needed, add to enum and here.
    WaveformType.NOISE: {
        "bandwidth": lambda ch, v_float: f"SOUR{ch}:FUNC:NOISe:BANDwidth {v_float}",
    },
    WaveformType.ARB: {
        "sample_rate": lambda ch, v_float: f"SOUR{ch}:FUNC:ARB:SRATe {v_float}",
        "filter": lambda ch, arb_filter_enum_val: f"SOUR{ch}:FUNC:ARB:FILTer {arb_filter_enum_val}", # Expects ArbFilterType.value
        "advance_mode": lambda ch, arb_adv_enum_val: f"SOUR{ch}:FUNC:ARB:ADVance {arb_adv_enum_val}", # Expects ArbAdvanceMode.value
        "frequency": lambda ch, v_float: f"SOUR{ch}:FUNC:ARB:FREQ {v_float}",
        "period": lambda ch, v_float: f"SOUR{ch}:FUNC:ARB:PER {v_float}",
        "ptpeak_voltage": lambda ch, v_float: f"SOUR{ch}:FUNC:ARB:PTP {v_float}",
    },
    WaveformType.DC: {}
}


class WaveformGenerator(Instrument[WaveformGeneratorConfig]):
    """
    Provides a high-level Python interface for controlling Keysight EDU33210
    Series Trueform Arbitrary Waveform Generators via SCPI commands.
    """
    config: WaveformGeneratorConfig # Type hint for validated config
    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, config: WaveformGeneratorConfig, debug_mode: bool = False, **kwargs: Any) -> None:
        """
        Initializes the WaveformGenerator instance.
        """
        super().__init__(config=config, debug_mode=debug_mode, **kwargs) # Pass kwargs to base
        # self.config is already set by base Instrument's __init__ due to Generic type

        # Determine channel count from the length of the channels list in the config
        if hasattr(self.config, 'channels') and isinstance(self.config.channels, list):
            self._channel_count = len(self.config.channels)
        else:
            # This case should ideally be caught by Pydantic validation of WaveformGeneratorConfig
            self._logger.warning("config.channels is not a list. Defaulting channel count to 0.")
            self._channel_count = 0

        if self._channel_count <= 0:
            self._logger.warning(f"Channel count determined as {self._channel_count}. Check instrument configuration.")
            # Consider if raising an error is more appropriate if channel_count is essential and expected to be > 0
            # For now, logging a warning to allow flexibility if some AWGs might be configured with 0 channels initially.

        self._logger.debug(f"Detected {self._channel_count} channels from configuration.")

    def _log(self, message: str, level: str = "debug") -> None:
        """
        Helper method for logging messages at different levels.

        Args:
            message: The message to log
            level: The logging level ('debug', 'info', 'warning', 'error')
        """
        level_lower = level.lower()
        if level_lower == "debug":
            self._logger.debug(message)
        elif level_lower == "info":
            self._logger.info(message)
        elif level_lower == "warning":
            self._logger.warning(message)
        elif level_lower == "error":
            self._logger.error(message)
        else:
            self._logger.debug(message)  # fallback to debug

    @property
    def channel_count(self) -> int:
        """
        Returns the number of output channels supported by this instrument, based on configuration.
        """
        return self._channel_count


    @classmethod
    @validate_call
    def from_config(cls: Type['WaveformGenerator'], config: WaveformGeneratorConfig, debug_mode: bool = False, **kwargs: Any) -> 'WaveformGenerator':
        return cls(config=config, debug_mode=debug_mode, **kwargs)

    def _validate_channel(self, channel: Union[int, str]) -> int:
        """
        Validates the provided channel identifier and returns the integer channel number (1-based).
        """
        ch_num: int
        if isinstance(channel, str):
            ch_str = channel.strip().upper()
            if ch_str.startswith("CH"):
                match = re.match(r"CH(?:ANNEL)?(\d+)", ch_str)
                if match:
                    try:
                        ch_num = int(match.group(1))
                    except ValueError as e:
                        raise InstrumentParameterError(
                            parameter="channel",
                            value=channel,
                            message="Could not parse channel number from string.",
                        ) from e
                else:
                    raise InstrumentParameterError(
                        parameter="channel",
                        value=channel,
                        message="Invalid channel string format. Use integer, 'CHx', or 'CHANNELx'.",
                    )
            else:
                try:
                    ch_num = int(channel)
                except ValueError:
                    raise InstrumentParameterError(
                        parameter="channel",
                        value=channel,
                        message="Invalid channel string format. Use integer, 'CHx', or 'CHANNELx'.",
                    )
        elif isinstance(channel, int):
            ch_num = channel
        else:
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                message=f"Invalid channel type: {type(channel)}. Expected int or str.",
            )

        # Validate against the number of channels defined in the config
        # self.config.channels is List[AWGChannelConfig]
        if not (1 <= ch_num <= self.channel_count): # Use self.channel_count which is derived from len(self.config.channels)
            raise InstrumentParameterError(
                parameter="channel",
                value=ch_num,
                valid_range=(1, self.channel_count),
                message="Channel number is out of range.",
            )
        return ch_num

    def _get_scpi_function_name(self, user_function_name: Union[str, WaveformType]) -> str:
        """
        Translates a user-friendly function name or WaveformType enum to the canonical short SCPI name (e.g., "SIN", "SQU").
        Validates against the instrument's configured built_in waveforms.
        """
        if not hasattr(self.config, 'waveforms') or not hasattr(self.config.waveforms, 'built_in'):
            # This should be caught by Pydantic validation of WaveformGeneratorConfig
            raise InstrumentConfigurationError(
                self.config.model,
                "Configuration error: Missing 'waveforms.built_in' list in config.",
            )

        # self.config.waveforms.built_in is List[str] of SCPI values (e.g., ["SIN", "SQU", "RAMP"])
        supported_scpi_values_from_config = [str(val).upper() for val in self.config.waveforms.built_in]

        scpi_to_check: str
        if isinstance(user_function_name, WaveformType):
            scpi_to_check = user_function_name.value # This is already the SCPI value like "SIN"
        elif isinstance(user_function_name, str):
            lookup_key = user_function_name.strip().upper()
            # Attempt to map common friendly names to their SCPI enum values
            friendly_to_enum_scpi: Dict[str, str] = {
                "SINE": WaveformType.SINE.value, "SINUSOID": WaveformType.SINE.value,
                "SQUARE": WaveformType.SQUARE.value,
                "RAMP": WaveformType.RAMP.value,
                "PULSE": WaveformType.PULSE.value,
                "NOISE": WaveformType.NOISE.value,
                "ARBITRARY": WaveformType.ARB.value, "ARB": WaveformType.ARB.value,
                "DC": WaveformType.DC.value,
                # "TRIANGLE" and "PRBS" are not in WaveformType enum, so they won't map here.
                # If user passes "TRIANGLE" or "PRBS" as string, it will be checked against config directly.
            }
            scpi_to_check = friendly_to_enum_scpi.get(lookup_key, lookup_key) # Fallback to lookup_key if not in map
        else:
            raise InstrumentParameterError(
                parameter="function_type",
                value=user_function_name,
                message="Invalid function_type. Expected WaveformType enum or string.",
            )

        if scpi_to_check.upper() in supported_scpi_values_from_config:
            return scpi_to_check.upper() # Return the validated SCPI string
        else:
            # If user_function_name was a string and didn't map via friendly_to_enum_scpi,
            # but its uppercase version is in the supported list (e.g. user passed "TRI" and "TRI" is in built_in)
            if isinstance(user_function_name, str) and user_function_name.strip().upper() in supported_scpi_values_from_config:
                return user_function_name.strip().upper()

            raise InstrumentParameterError(
                parameter="function_type",
                value=user_function_name,
                valid_range=self.config.waveforms.built_in,
                message=f"Waveform function (resolved to SCPI '{scpi_to_check}') is not supported by this instrument configuration.",
            )


    def _format_value_min_max_def(self, value: Union[float, int, str, OutputLoadImpedance]) -> str:
        """
        Formats numeric values or special string/enum keywords for SCPI commands.
        """
        if isinstance(value, OutputLoadImpedance):
            return value.value
        if isinstance(value, str):
            val_upper = value.upper().strip()
            if val_upper in {"MIN", "MINIMUM"}: return OutputLoadImpedance.MINIMUM.value
            if val_upper in {"MAX", "MAXIMUM"}: return OutputLoadImpedance.MAXIMUM.value
            if val_upper in {"DEF", "DEFAULT"}: return OutputLoadImpedance.DEFAULT.value
            if val_upper in {"INF", "INFINITY"}: return OutputLoadImpedance.INFINITY.value
            try:
                num_val = float(value)
                return f"{num_val:.12G}"
            except ValueError:
                raise InstrumentParameterError(
                    parameter="value",
                    value=value,
                    message="Invalid parameter string. Expected a number, specific keywords (MIN/MAX/DEF/INF), or a valid OutputLoadImpedance enum.",
                )
        elif isinstance(value, (int, float)):
            return f"{float(value):.12G}"
        else:
            raise InstrumentParameterError(
                parameter="value",
                value=value,
                message=f"Invalid parameter type: {type(value)}. Expected number, string, or OutputLoadImpedance enum.",
            )

    @validate_call
    def set_function(self, channel: Union[int, str], function_type: Union[WaveformType, str], **kwargs: Any) -> None:
        """
        Sets the primary waveform function and associated parameters for a channel.
        """
        ch = self._validate_channel(channel)
        scpi_func_short = self._get_scpi_function_name(function_type)

        standard_params_set: Dict[str, bool] = {}
        # Assuming FUNC_ARB should be WaveformType.ARB.value
        if 'frequency' in kwargs and scpi_func_short != WaveformType.ARB.value:
            self.set_frequency(ch, kwargs.pop('frequency'))
            standard_params_set['frequency'] = True
        if 'amplitude' in kwargs:
            self.set_amplitude(ch, kwargs.pop('amplitude'))
            standard_params_set['amplitude'] = True
        if 'offset' in kwargs:
            self.set_offset(ch, kwargs.pop('offset'))
            standard_params_set['offset'] = True

        self._send_command(f"SOUR{ch}:FUNC {scpi_func_short}")
        self._logger.debug(f"Channel {ch}: Function set to {function_type} (SCPI: {scpi_func_short})")
        self._error_check()

        if kwargs:
            # Ensure WAVEFORM_PARAM_COMMANDS keys are WaveformType enum members
            # And scpi_func_short is mapped to its corresponding WaveformType enum member if it's a string
            func_enum_key: Optional[WaveformType] = None
            if isinstance(function_type, WaveformType):
                func_enum_key = function_type
            elif isinstance(function_type, str):
                try:
                    # First try to convert SCPI string directly to enum member
                    func_enum_key = WaveformType(scpi_func_short)
                except ValueError:
                    # If that fails, try to map profile config values to enum members
                    scpi_to_enum_map = {
                        "SINUSOID": WaveformType.SINE,
                        "SQUARE": WaveformType.SQUARE,
                        "RAMP": WaveformType.RAMP,
                        "PULSE": WaveformType.PULSE,
                        "NOISE": WaveformType.NOISE,
                        "DC": WaveformType.DC,
                        "ARB": WaveformType.ARB,
                        "ARBITRARY": WaveformType.ARB,
                        # Add enum values as fallback
                        "SIN": WaveformType.SINE,
                        "SQU": WaveformType.SQUARE,
                        "PULS": WaveformType.PULSE,
                        "NOIS": WaveformType.NOISE,
                    }
                    func_enum_key = scpi_to_enum_map.get(scpi_func_short.upper())
                    if func_enum_key is None:
                        self._logger.warning(f"SCPI function '{scpi_func_short}' not mappable to WaveformType enum for parameter lookup.")

            param_cmds_for_func = WAVEFORM_PARAM_COMMANDS.get(func_enum_key) if func_enum_key else None

            if not param_cmds_for_func:
                self._logger.warning(f"No specific parameters defined for function '{function_type}' (SCPI: {scpi_func_short}). "
                          f"Ignoring remaining kwargs: {kwargs}")
                if any(k not in standard_params_set for k in kwargs):
                    raise InstrumentParameterError(
                        message=f"Unknown parameters {list(kwargs.keys())} passed for function {function_type}."
                    )
                return

            for param_name, value in kwargs.items():
                if param_name in param_cmds_for_func:
                    try:
                        if param_name in ["duty_cycle", "symmetry"] and isinstance(value, (int, float)):
                            if not (0 <= float(value) <= 100):
                                self._logger.warning(f"Parameter '{param_name}' value {value}% is outside the "
                                          f"typical 0-100 range. Instrument validation will apply.")

                        value_to_format = value
                        if isinstance(value, (ArbFilterType, ArbAdvanceMode)): # Pass enum value for formatting
                            value_to_format = value.value

                        formatted_value = self._format_value_min_max_def(value_to_format)
                        cmd_lambda = param_cmds_for_func[param_name]
                        cmd = cmd_lambda(ch, formatted_value)

                        self._send_command(cmd)
                        self._logger.debug(f"Channel {ch}: Parameter '{param_name}' set to {value}")
                        self._error_check()
                    except InstrumentParameterError as ipe:
                        raise InstrumentParameterError(
                            parameter=param_name,
                            value=value,
                            message=f"Invalid value for function '{function_type}'. Cause: {ipe}",
                        ) from ipe
                    except InstrumentCommunicationError:
                        raise
                    except Exception as e:
                        self._logger.error(f"Error setting parameter '{param_name}' for function '{scpi_func_short}': {e}")
                        raise InstrumentCommunicationError(
                            instrument=self.config.model,
                            command=cmd,
                            message=f"Failed to set parameter {param_name}",
                        ) from e
                else:
                    raise InstrumentParameterError(
                        parameter=param_name,
                        message=f"Parameter is not supported for function '{function_type}' ({scpi_func_short}). Supported: {list(param_cmds_for_func.keys())}",
                    )

    def get_function(self, channel: Union[int, str]) -> str:
        ch = self._validate_channel(channel)
        scpi_func = (self._query(f"SOUR{ch}:FUNC?")).strip()
        self._logger.debug(f"Channel {ch}: Current function is {scpi_func}")
        return scpi_func

    @validate_call
    def set_frequency(self, channel: Union[int, str], frequency: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        freq_cmd_val = self._format_value_min_max_def(frequency)
        if isinstance(frequency, (int, float)):
            if 0 <= (ch - 1) < len(self.config.channels):
                channel_config_model = self.config.channels[ch - 1]
                channel_config_model.frequency.assert_in_range(float(frequency), name=f"Frequency for CH{ch}")
        self._send_command(f"SOUR{ch}:FREQ {freq_cmd_val}")
        self._logger.debug(f"Channel {ch}: Frequency set to {frequency} Hz (using SCPI value: {freq_cmd_val})")
        self._error_check()

    @validate_call
    def get_frequency(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> float:
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:FREQ?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} limit)"
        response = (self._query(cmd)).strip()
        try:
            freq = float(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse frequency float from response: '{response}'",
            )
        self._logger.debug(f"Channel {ch}: Frequency{type_str} is {freq} Hz")
        return freq

    @validate_call
    def set_amplitude(self, channel: Union[int, str], amplitude: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        amp_cmd_val = self._format_value_min_max_def(amplitude)
        if isinstance(amplitude, (int, float)):
            if 0 <= (ch - 1) < len(self.config.channels):
                channel_config_model = self.config.channels[ch-1]
                channel_config_model.amplitude.assert_in_range(float(amplitude), name=f"Amplitude for CH{ch}")
        self._send_command(f"SOUR{ch}:VOLTage {amp_cmd_val}")
        unit = self.get_voltage_unit(ch)
        self._logger.debug(f"Channel {ch}: Amplitude set to {amplitude} (in current unit: {unit.value}, using SCPI value: {amp_cmd_val})")
        self._error_check()

    @validate_call
    def get_amplitude(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> float:
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} limit)"
        response = (self._query(cmd)).strip()
        try:
            amp = float(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse amplitude float from response: '{response}'",
            )
        unit = self.get_voltage_unit(ch)
        self._logger.debug(f"Channel {ch}: Amplitude{type_str} is {amp} {unit.value}")
        return amp

    @validate_call
    def set_offset(self, channel: Union[int, str], offset: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        offset_cmd_val = self._format_value_min_max_def(offset)
        self._send_command(f"SOUR{ch}:VOLTage:OFFSet {offset_cmd_val}")
        self._logger.debug(f"Channel {ch}: Offset set to {offset} V")
        self._error_check()

    @validate_call
    def get_offset(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> float:
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage:OFFSet?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} limit)"
        response = (self._query(cmd)).strip()
        try:
            offs = float(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse offset float from response: '{response}'",
            )
        self._logger.debug(f"Channel {ch}: Offset{type_str} is {offs} V")
        return offs

    @validate_call
    def set_phase(self, channel: Union[int, str], phase: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        phase_cmd_val = self._format_value_min_max_def(phase)
        if isinstance(phase, (int, float)):
            if 0 <= (ch - 1) < len(self.config.channels):
                channel_config_model = self.config.channels[ch-1]
                channel_config_model.phase.assert_in_range(float(phase), name=f"Phase for CH{ch}")
        self._send_command(f"SOUR{ch}:PHASe {phase_cmd_val}")
        unit = self.get_angle_unit()
        self._logger.debug(f"Channel {ch}: Phase set to {phase} (in current unit: {unit}, using SCPI value: {phase_cmd_val})")
        self._error_check()

    @validate_call
    def get_phase(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> float:
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:PHASe?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} limit)"
        response = (self._query(cmd)).strip()
        try:
            ph = float(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse phase float from response: '{response}'",
            )
        unit = self.get_angle_unit()
        self._logger.debug(f"Channel {ch}: Phase{type_str} is {ph} {unit}")
        return ph

    @validate_call
    def set_phase_reference(self, channel: Union[int, str]) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:PHASe:REFerence")
        self._logger.debug(f"Channel {ch}: Phase reference reset (current phase defined as 0).")
        self._error_check()

    @validate_call
    def synchronize_phase_all_channels(self) -> None:
        if self.channel_count < 2:
            self._logger.warning("Warning: Phase synchronization command sent, but primarily intended for multi-channel instruments.")
        self._send_command("PHASe:SYNChronize")
        self._logger.debug("All channels/internal phase generators synchronized.")
        self._error_check()

    @validate_call
    def set_phase_unlock_error_state(self, state: SCPIOnOff) -> None:
        self._send_command(f"SOUR1:PHASe:UNLock:ERRor:STATe {state.value}")
        self._logger.debug(f"Phase unlock error state set to {state.value}")
        self._error_check()

    @validate_call
    def get_phase_unlock_error_state(self) -> SCPIOnOff:
        response = (self._query("SOUR1:PHASe:UNLock:ERRor:STATe?")).strip()
        state = SCPIOnOff.ON if response == "1" else SCPIOnOff.OFF
        self._logger.debug(f"Phase unlock error state is {state.value}")
        return state

    @validate_call # Duplicated @validate_call removed
    def set_output_state(self, channel: Union[int, str], state: SCPIOnOff) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"OUTPut{ch}:STATe {state.value}")
        self._logger.debug(f"Channel {ch}: Output state set to {state.value}")
        self._error_check()

    @validate_call
    def get_output_state(self, channel: Union[int, str]) -> SCPIOnOff:
        ch = self._validate_channel(channel)
        response = (self._query(f"OUTPut{ch}:STATe?")).strip()
        state = SCPIOnOff.ON if response == "1" else SCPIOnOff.OFF
        self._logger.debug(f"Channel {ch}: Output state is {state.value}")
        return state

    @validate_call
    def set_output_load_impedance(self, channel: Union[int, str], impedance: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_impedance = self._format_value_min_max_def(impedance)
        if isinstance(impedance, (int, float)):
            if 0 <= (ch - 1) < len(self.config.channels):
                channel_config_model = self.config.channels[ch-1]
                if hasattr(channel_config_model, 'output') and hasattr(channel_config_model.output, 'load_impedance'):
                    channel_config_model.output.load_impedance.assert_in_range(float(impedance), name=f"Load impedance for CH{ch}")
        self._send_command(f"OUTPut{ch}:LOAD {cmd_impedance}")
        self._logger.debug(f"Channel {ch}: Output load impedance setting updated to {impedance} (using SCPI value: {cmd_impedance})")
        self._error_check()

    @validate_call
    def get_output_load_impedance(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> Union[float, OutputLoadImpedance]:
        ch = self._validate_channel(channel)
        cmd = f"OUTPut{ch}:LOAD?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} limit)"
        response = (self._query(cmd)).strip()
        self._logger.debug(f"Channel {ch}: Raw impedance response{type_str} is '{response}'")
        try:
            numeric_response = float(response)
            if abs(numeric_response - 9.9e37) < 1e30: return OutputLoadImpedance.INFINITY
            else: return numeric_response
        except ValueError:
            if response.upper() == OutputLoadImpedance.INFINITY.value.upper(): return OutputLoadImpedance.INFINITY
            for enum_member in OutputLoadImpedance:
                if response.upper() == enum_member.value.upper(): return enum_member
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Could not parse impedance response: '{response}'",
            )

    @validate_call
    def set_output_polarity(self, channel: Union[int, str], polarity: OutputPolarity) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"OUTPut{ch}:POLarity {polarity.value}")
        self._logger.debug(f"Channel {ch}: Output polarity set to {polarity.value}")
        self._error_check()

    @validate_call
    def get_output_polarity(self, channel: Union[int, str]) -> OutputPolarity:
        ch = self._validate_channel(channel)
        response = (self._query(f"OUTPut{ch}:POLarity?")).strip().upper()
        try:
            return OutputPolarity(response)
        except ValueError:
            if response == "NORM": return OutputPolarity.NORMAL
            if response == "INV": return OutputPolarity.INVERTED
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=f"OUTPut{ch}:POLarity?",
                message=f"Unexpected polarity response from instrument: {response}",
            )

    @validate_call
    def set_voltage_unit(self, channel: Union[int, str], unit: VoltageUnit) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:VOLTage:UNIT {unit.value}")
        self._logger.debug(f"Channel {ch}: Voltage unit set to {unit.value}")
        self._error_check()

    @validate_call
    def get_voltage_unit(self, channel: Union[int, str]) -> VoltageUnit:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:VOLTage:UNIT?")).strip().upper()
        try:
            return VoltageUnit(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=f"SOUR{ch}:VOLTage:UNIT?",
                message=f"Unexpected voltage unit response from instrument: {response}",
            )

    @validate_call
    def set_voltage_limits_state(self, channel: Union[int, str], state: SCPIOnOff) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:STATe {state.value}")
        self._logger.debug(f"Channel {ch}: Voltage limits state set to {state.value}")
        self._error_check()

    @validate_call
    def get_voltage_limits_state(self, channel: Union[int, str]) -> SCPIOnOff:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:VOLTage:LIMit:STATe?")).strip()
        state = SCPIOnOff.ON if response == "1" else SCPIOnOff.OFF
        self._logger.debug(f"Channel {ch}: Voltage limits state is {state.value}")
        return state

    @validate_call
    def set_voltage_limit_high(self, channel: Union[int, str], voltage: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(voltage)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:HIGH {cmd_val}")
        self._logger.debug(f"Channel {ch}: Voltage high limit set to {voltage} V (using SCPI value: {cmd_val})")
        self._error_check()

    @validate_call
    def get_voltage_limit_high(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> float:
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage:LIMit:HIGH?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} possible)"
        response = (self._query(cmd)).strip()
        try:
            val = float(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse high limit float from response: '{response}'",
            )
        self._logger.debug(f"Channel {ch}: Voltage high limit{type_str} is {val} V")
        return val

    @validate_call
    def set_voltage_limit_low(self, channel: Union[int, str], voltage: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(voltage)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:LOW {cmd_val}")
        self._logger.debug(f"Channel {ch}: Voltage low limit set to {voltage} V (using SCPI value: {cmd_val})")
        self._error_check()

    @validate_call
    def get_voltage_limit_low(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> float:
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage:LIMit:LOW?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} possible)"
        response = (self._query(cmd)).strip()
        try:
            val = float(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse low limit float from response: '{response}'",
            )
        self._logger.debug(f"Channel {ch}: Voltage low limit{type_str} is {val} V")
        return val

    @validate_call
    def set_voltage_autorange_state(self, channel: Union[int, str], state: SCPIOnOff) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:VOLTage:RANGe:AUTO {state.value}")
        self._logger.debug(f"Channel {ch}: Voltage autorange state set to {state.value}")
        self._error_check()

    @validate_call
    def get_voltage_autorange_state(self, channel: Union[int, str]) -> SCPIOnOff:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:VOLTage:RANGe:AUTO?")).strip()
        state = SCPIOnOff.ON if response == "1" else SCPIOnOff.OFF
        self._logger.debug(f"Channel {ch}: Voltage autorange state is {state.value} (Query response: {response})")
        return state

    @validate_call
    def set_sync_output_state(self, state: SCPIOnOff) -> None:
        self._send_command(f"OUTPut:SYNC:STATe {state.value}")
        self._logger.debug(f"Sync output state set to {state.value}")
        self._error_check()

    @validate_call
    def get_sync_output_state(self) -> SCPIOnOff:
        response = (self._query("OUTPut:SYNC:STATe?")).strip()
        state = SCPIOnOff.ON if response == "1" else SCPIOnOff.OFF
        self._logger.debug(f"Sync output state is {state.value}")
        return state

    @validate_call
    def set_sync_output_mode(self, channel: Union[int, str], mode: SyncMode) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"OUTPut{ch}:SYNC:MODE {mode.value}")
        self._logger.debug(f"Channel {ch}: Sync output mode set to {mode.value}")
        self._error_check()

    @validate_call
    def get_sync_output_mode(self, channel: Union[int, str]) -> SyncMode:
        ch = self._validate_channel(channel)
        response = (self._query(f"OUTPut{ch}:SYNC:MODE?")).strip().upper()
        try:
            return SyncMode(response)
        except ValueError:
            if response == "NORM": return SyncMode.NORMAL
            if response == "CARR": return SyncMode.CARRIER
            if response == "MARK": return SyncMode.MARKER
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=f"OUTPut{ch}:SYNC:MODE?",
                message=f"Unexpected sync mode response from instrument: {response}",
            )

    @validate_call
    def set_sync_output_polarity(self, channel: Union[int, str], polarity: OutputPolarity) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"OUTPut{ch}:SYNC:POLarity {polarity.value}")
        self._logger.debug(f"Channel {ch}: Sync output polarity set to {polarity.value}")
        self._error_check()

    @validate_call
    def get_sync_output_polarity(self, channel: Union[int, str]) -> OutputPolarity:
        ch = self._validate_channel(channel)
        response = (self._query(f"OUTPut{ch}:SYNC:POLarity?")).strip().upper()
        try:
            return OutputPolarity(response)
        except ValueError:
            if response == "NORM": return OutputPolarity.NORMAL
            if response == "INV": return OutputPolarity.INVERTED
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=f"OUTPut{ch}:SYNC:POLarity?",
                message=f"Unexpected sync polarity response from instrument: {response}",
            )

    @validate_call
    def set_sync_output_source(self, source_channel: int) -> None:
        ch_to_set = self._validate_channel(source_channel)
        self._send_command(f"OUTPut:SYNC:SOURce CH{ch_to_set}")
        self._logger.debug(f"Sync output source set to CH{ch_to_set}")
        self._error_check()

    @validate_call
    def get_sync_output_source(self) -> int:
        response = (self._query("OUTPut:SYNC:SOURce?")).strip().upper()
        match = re.match(r"CH(\d+)", response)
        if match:
            src_ch = int(match.group(1))
            self._logger.debug(f"Sync output source is CH{src_ch}")
            return src_ch
        else:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command="OUTPut:SYNC:SOURce?",
                message=f"Unexpected response querying Sync source: '{response}'",
            )

    @validate_call
    def select_arbitrary_waveform(self, channel: Union[int, str], arb_name: str) -> None:
        ch = self._validate_channel(channel)
        if not arb_name:
            raise InstrumentParameterError(
                parameter="arb_name", message="Arbitrary waveform name cannot be empty."
            )
        if '"' in arb_name or "'" in arb_name:
            raise InstrumentParameterError(
                parameter="arb_name",
                value=arb_name,
                message="Arbitrary waveform name cannot contain quotes.",
            )
        quoted_arb_name = f'"{arb_name}"'
        self._send_command(f"SOUR{ch}:FUNC:ARBitrary {quoted_arb_name}")
        self._logger.debug(f"Channel {ch}: Active arbitrary waveform selection set to '{arb_name}'")
        self._error_check()

    @validate_call
    def get_selected_arbitrary_waveform_name(self, channel: Union[int, str]) -> str:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:ARBitrary?")).strip()
        if response.startswith('"') and response.endswith('"'): response = response[1:-1]
        self._logger.debug(f"Channel {ch}: Currently selected arbitrary waveform is '{response}'")
        return response

    @validate_call
    def set_arbitrary_waveform_sample_rate(self, channel: Union[int, str], sample_rate: Union[float, OutputLoadImpedance, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sample_rate)
        if isinstance(sample_rate, (int, float)):
            if 0 <= (ch - 1) < len(self.config.channels):
                channel_config_model = self.config.channels[ch-1]
                if hasattr(channel_config_model, 'arbitrary') and hasattr(channel_config_model.arbitrary, 'sampling_rate'):
                    channel_config_model.arbitrary.sampling_rate.assert_in_range(float(sample_rate), name=f"Arbitrary sample rate for CH{ch}")
        self._send_command(f"SOUR{ch}:FUNC:ARB:SRATe {cmd_val}")
        self._logger.debug(f"Channel {ch}: Arbitrary waveform sample rate set to {sample_rate} Sa/s (using SCPI value: {cmd_val})")
        self._error_check()

    @validate_call
    def get_arbitrary_waveform_sample_rate(self, channel: Union[int, str], query_type: Optional[OutputLoadImpedance] = None) -> float:
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:FUNC:ARB:SRATe?"
        type_str = ""
        if query_type: cmd += f" {query_type.value}"; type_str = f" ({query_type.name} limit)"
        response = (self._query(cmd)).strip()
        try:
            sr = float(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse sample rate float from response: '{response}'",
            )
        self._logger.debug(f"Channel {ch}: Arbitrary waveform sample rate{type_str} is {sr} Sa/s")
        return sr

    @validate_call
    def get_arbitrary_waveform_points(self, channel: Union[int, str]) -> int:
        ch = self._validate_channel(channel)
        try:
            response = (self._query(f"SOUR{ch}:FUNC:ARB:POINts?")).strip()
            points = int(response)
            self._logger.debug(f"Channel {ch}: Currently selected arbitrary waveform has {points} points")
            return points
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=f"SOUR{ch}:FUNC:ARB:POINts?",
                message=f"Failed to parse integer points from response: '{response}'",
            )
        except InstrumentCommunicationError as e:
            code, msg = self.get_error()
            if code != 0:
                self._logger.warning(f"Query SOUR{ch}:FUNC:ARB:POINts? failed. Inst Err {code}: {msg}. Returning 0.")
                return 0
            else:
                raise e

    def download_arbitrary_waveform_data(self, channel: Union[int, str], arb_name: str, data_points: Union[List[int], List[float], np.ndarray], data_type: str = "DAC", use_binary: bool = True, is_dual_channel_data: bool = False, dual_data_format: Optional[str] = None) -> None:
        if use_binary:
            self.download_arbitrary_waveform_data_binary(channel, arb_name, data_points, data_type, is_dual_channel_data=is_dual_channel_data, dual_data_format=dual_data_format)
        else:
            self.download_arbitrary_waveform_data_csv(channel, arb_name, data_points, data_type)

    def download_arbitrary_waveform_data_csv(self, channel: Union[int, str], arb_name: str, data_points: Union[List[int], List[float], np.ndarray], data_type: str = "DAC") -> None:
        ch = self._validate_channel(channel)
        if not re.match(r"^[a-zA-Z0-9_]{1,12}$", arb_name):
            raise InstrumentParameterError(
                parameter="arb_name",
                value=arb_name,
                message="Arbitrary waveform name is invalid.",
            )
        data_type_upper = data_type.upper().strip()
        if data_type_upper not in ["DAC", "NORM"]:
            raise InstrumentParameterError(
                parameter="data_type",
                value=data_type,
                valid_range=["DAC", "NORM"],
                message="Invalid data_type.",
            )
        np_data = np.asarray(data_points)
        if np_data.ndim != 1 or np_data.size == 0:
            raise InstrumentParameterError(
                parameter="data_points", message="data_points must be a non-empty 1D sequence."
            )
        if 0 <= (ch - 1) < len(self.config.channels):
            channel_conf = self.config.channels[ch-1]
            if hasattr(channel_conf, 'arbitrary') and hasattr(channel_conf.arbitrary, 'max_points') and np_data.size > channel_conf.arbitrary.max_points:
                self._logger.warning(f"Number of data points ({np_data.size}) exceeds configured max_points ({channel_conf.arbitrary.max_points}) for CH{ch}.")
        formatted_data: str
        scpi_suffix: str
        if data_type_upper == "DAC":
            if not np.issubdtype(np_data.dtype, np.integer):
                self._logger.warning("DAC data not integer, converting to int16.")
                try:
                    np_data = np_data.astype(np.int16)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert DAC data to int16.",
                    ) from e
            dac_min, dac_max = getattr(self.config.waveforms, 'arbitrary_dac_range', (-32768, 32767))
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"DAC data out of range [{dac_min}, {dac_max}].",
                )
            formatted_data = ','.join(map(str, np_data))
            scpi_suffix = ":DAC"
        else: # NORM
            if not np.issubdtype(np_data.dtype, np.floating):
                self._logger.warning("Normalized data not float, converting to float32.")
                try:
                    np_data = np_data.astype(np.float32)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert Normalized data to floats.",
                    ) from e
            norm_min, norm_max = -1.0, 1.0
            tolerance = 1e-9
            if np.any(np_data < norm_min - tolerance) or np.any(
                np_data > norm_max + tolerance
            ):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"Normalized data out of range [{norm_min}, {norm_max}].",
                )
            np_data = np.clip(np_data, norm_min, norm_max)
            formatted_data = ','.join(map(lambda x: f"{x:.8G}", np_data))
            scpi_suffix = ""
        cmd = f"SOUR{ch}:DATA:ARBitrary{scpi_suffix} {arb_name},{formatted_data}"
        max_cmd_len = getattr(self.config, 'max_scpi_command_length', 10000)
        if len(cmd) > max_cmd_len: self._logger.warning(f"SCPI command length ({len(cmd)}) large. Consider binary transfer.")
        try:
            self._send_command(cmd)
            self._logger.debug(f"Channel {ch}: Downloaded arb '{arb_name}' via CSV ({np_data.size} points, type: {data_type_upper})")
            self._error_check()
        except InstrumentCommunicationError as e:
            self._logger.error(f"Error during CSV arb download for '{arb_name}'.")
            code, msg = self.get_error()
            if code == -113:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"SCPI Syntax Error (-113) for '{arb_name}'.",
                ) from e
            elif code == 786:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Arb Name Conflict (786) for '{arb_name}'.",
                ) from e
            elif code == 781:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Out of Memory (781) for '{arb_name}'.",
                ) from e
            elif code == -102:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"SCPI Syntax Error (-102) for '{arb_name}'.",
                ) from e
            elif code != 0:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Arb download for '{arb_name}' failed. Inst Err {code}: {msg}",
                ) from e
            else:
                raise e

    def download_arbitrary_waveform_data_binary(self, channel: Union[int, str], arb_name: str, data_points: Union[List[int], List[float], np.ndarray], data_type: str = "DAC", is_dual_channel_data: bool = False, dual_data_format: Optional[str] = None) -> None:
        ch = self._validate_channel(channel)
        if not re.match(r"^[a-zA-Z0-9_]{1,12}$", arb_name):
            raise InstrumentParameterError(
                parameter="arb_name",
                value=arb_name,
                message="Arbitrary waveform name is invalid.",
            )
        data_type_upper = data_type.upper().strip()
        if data_type_upper not in ["DAC", "NORM"]:
            raise InstrumentParameterError(
                parameter="data_type",
                value=data_type,
                valid_range=["DAC", "NORM"],
                message="Invalid data_type.",
            )
        np_data = np.asarray(data_points)
        if np_data.ndim != 1 or np_data.size == 0:
            raise InstrumentParameterError(
                parameter="data_points", message="data_points must be a non-empty 1D sequence."
            )
        num_points_total = np_data.size
        num_points_per_channel = num_points_total
        arb_cmd_node = "ARBitrary"
        if is_dual_channel_data:
            if self.channel_count < 2:
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Dual channel download requires 2-channel instrument.",
                )
            arb_cmd_node = "ARBitrary2"
            if num_points_total % 2 != 0:
                raise InstrumentParameterError(
                    parameter="data_points",
                    message="Total data_points must be even for dual channel.",
                )
            num_points_per_channel = num_points_total // 2
            if dual_data_format:
                fmt_upper = dual_data_format.upper().strip()
                if fmt_upper not in ["AABB", "ABAB"]:
                    raise InstrumentParameterError(
                        parameter="dual_data_format",
                        value=dual_data_format,
                        valid_range=["AABB", "ABAB"],
                        message="Invalid dual_data_format.",
                    )
                self._send_command(f"SOUR{ch}:DATA:{arb_cmd_node}:FORMat {fmt_upper}")
                self._error_check()
                self._logger.debug(f"Channel {ch}: Dual arb data format set to {fmt_upper}")
        binary_data: bytes
        scpi_suffix: str
        transfer_type_log_msg: str = "Binary Block"
        if data_type_upper == "DAC":
            scpi_suffix = ":DAC"
            if not np.issubdtype(np_data.dtype, np.integer):
                self._logger.warning("Warning: DAC data not integer, converting to int16.")
                try:
                    np_data = np_data.astype(np.int16)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert DAC data to int16.",
                    ) from e
            dac_min, dac_max = getattr(self.config.waveforms, 'arbitrary_dac_range', (-32768, 32767))
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"DAC data out of range [{dac_min}, {dac_max}].",
                )
            binary_data = np_data.astype('<h').tobytes()
        else: # NORM
            scpi_suffix = ""
            if not np.issubdtype(np_data.dtype, np.floating):
                self._logger.warning("Warning: Normalized data not float, converting to float32.")
                try:
                    np_data = np_data.astype(np.float32)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert Normalized data to float32.",
                    ) from e
            norm_min, norm_max = -1.0, 1.0
            tolerance = 1e-6
            if np.any(np_data < norm_min - tolerance) or np.any(
                np_data > norm_max + tolerance
            ):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"Normalized data out of range [{norm_min}, {norm_max}].",
                )
            np_data = np.clip(np_data, norm_min, norm_max)
            binary_data = np_data.astype('<f').tobytes()
        cmd_prefix = f"SOUR{ch}:DATA:{arb_cmd_node}{scpi_suffix} {arb_name},"
        try:
            self._write_binary(cmd_prefix, binary_data) # Assumed async
            transfer_type_log_msg = "IEEE 488.2 Binary Block via _write_binary"
            self._logger.debug(f"Channel {ch}: Downloaded arb '{arb_name}' via {transfer_type_log_msg} ({num_points_per_channel} pts/ch, {len(binary_data)} bytes, type: {data_type_upper})")
            self._error_check()
        except InstrumentCommunicationError as e:
            self._logger.error(f"Error during {transfer_type_log_msg} arb download for '{arb_name}'.")
            code, msg = self.get_error()
            if code == 786:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"Arb Name Conflict (786) for '{arb_name}'.",
                ) from e
            elif code == 781:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"Out of Memory (781) for '{arb_name}'.",
                ) from e
            elif code == -113:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"SCPI Syntax Error (-113) for '{arb_name}'.",
                ) from e
            elif code != 0:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"Arb download for '{arb_name}' failed. Inst Err {code}: {msg}",
                ) from e
            else:
                raise e
        except Exception as e:
            self._logger.error(f"Unexpected error during binary arb download for '{arb_name}': {e}")
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd_prefix,
                message=f"Unexpected failure downloading arb '{arb_name}'",
            ) from e

    @validate_call
    def clear_volatile_arbitrary_waveforms(self, channel: Union[int, str]) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:DATA:VOLatile:CLEar")
        self._logger.debug(f"Channel {ch}: Cleared volatile arbitrary waveform memory.")
        self._error_check()

    @validate_call
    def get_free_volatile_arbitrary_memory(self, channel: Union[int, str]) -> int:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:DATA:VOLatile:FREE?")).strip()
        try:
            free_points = int(response)
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=f"SOUR{ch}:DATA:VOLatile:FREE?",
                message=f"Unexpected non-integer response: {response}",
            )
        self._logger.debug(f"Channel {ch}: Free volatile arbitrary memory: {free_points} points")
        return free_points

    @validate_call
    def get_pulse_duty_cycle(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:PULS:DCYCle?")).strip()
        return float(response)

    @validate_call
    def get_pulse_period(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:PULS:PERiod?")).strip()
        return float(response)

    @validate_call
    def get_pulse_width(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:PULS:WIDTh?")).strip()
        return float(response)

    @validate_call
    def get_pulse_transition_leading(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:PULS:TRANsition:LEADing?")).strip()
        return float(response)

    @validate_call
    def get_pulse_transition_trailing(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:PULS:TRANsition:TRAiling?")).strip()
        return float(response)

    @validate_call
    def get_pulse_transition_both(self, channel: Union[int, str]) -> float:
        warnings.warn("Querying PULS:TRAN:BOTH; specific query may not exist or might return leading edge time.", UserWarning, stacklevel=2)
        return self.get_pulse_transition_leading(channel)

    @validate_call
    def get_pulse_hold_mode(self, channel: Union[int, str]) -> str:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:PULS:HOLD?")).strip().upper()
        return response

    @validate_call
    def get_square_duty_cycle(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:SQUare:DCYCle?")).strip()
        return float(response)

    @validate_call
    def get_square_period(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:SQUare:PERiod?")).strip()
        return float(response)

    @validate_call
    def get_ramp_symmetry(self, channel: Union[int, str]) -> float:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:FUNC:RAMP:SYMMetry?")).strip()
        return float(response)

    @validate_call
    def set_angle_unit(self, unit: str) -> None:
        unit_upper = unit.upper().strip()
        valid_scpi_units = {"DEGREE", "RADIAN", "SECOND", "DEG", "RAD", "SEC"}
        map_to_scpi_preferred = {"DEG": "DEGREE", "DEGREES": "DEGREE", "RAD": "RADIAN", "RADIANS": "RADIAN", "SEC": "SECOND", "SECONDS": "SECOND"}
        scpi_to_send = map_to_scpi_preferred.get(unit_upper, unit_upper)
        if scpi_to_send not in valid_scpi_units and unit_upper not in valid_scpi_units :
            raise InstrumentParameterError(
                parameter="unit",
                value=unit,
                valid_range=["DEGREE", "RADIAN", "SECONd"],
                message="Invalid angle unit.",
            )
        self._send_command(f"UNIT:ANGLe {scpi_to_send}")
        self._logger.debug(f"Global angle unit set to {scpi_to_send}")
        self._error_check()

    @validate_call
    def get_angle_unit(self) -> str:
        response = (self._query("UNIT:ANGLe?")).strip().upper()
        if response not in ["DEG", "RAD", "SEC"]: self._logger.warning(f"Warning: Unexpected angle unit response '{response}'.")
        self._logger.debug(f"Current global angle unit is {response}")
        return response

    @validate_call
    def apply_waveform_settings(self, channel: Union[int, str], function_type: Union[WaveformType, str], frequency: Union[float, OutputLoadImpedance, str] = OutputLoadImpedance.DEFAULT, amplitude: Union[float, OutputLoadImpedance, str] = OutputLoadImpedance.DEFAULT, offset: Union[float, OutputLoadImpedance, str] = OutputLoadImpedance.DEFAULT) -> None:
        ch = self._validate_channel(channel)
        scpi_short_name = self._get_scpi_function_name(function_type)
        apply_suffix_map: Dict[str, str] = { WaveformType.SINE.value: "SINusoid", WaveformType.SQUARE.value: "SQUare", WaveformType.RAMP.value: "RAMP", WaveformType.PULSE.value: "PULSe", WaveformType.NOISE.value: "NOISe", WaveformType.ARB.value: "ARBitrary", WaveformType.DC.value: "DC",}
        if scpi_short_name == "TRI" and "TRI" not in apply_suffix_map: apply_suffix_map["TRI"] = "TRIangle"
        apply_suffix = apply_suffix_map.get(scpi_short_name)
        if not apply_suffix:
            if scpi_short_name in apply_suffix_map:
                apply_suffix = apply_suffix_map[scpi_short_name]
            else:
                raise InstrumentParameterError(
                    parameter="function_type",
                    value=function_type,
                    message=f"Waveform function (SCPI: {scpi_short_name}) not supported by APPLy.",
                )
        params: List[str] = [self._format_value_min_max_def(frequency), self._format_value_min_max_def(amplitude), self._format_value_min_max_def(offset)]
        param_str = ",".join(params)
        cmd = f"SOUR{ch}:APPLy:{apply_suffix} {param_str}"
        self._send_command(cmd)
        self._logger.debug(f"Channel {ch}: Applied {apply_suffix} with params: Freq/SR={frequency}, Ampl={amplitude}, Offs={offset}")
        self._error_check()

    @validate_call
    def get_channel_configuration_summary(self, channel: Union[int, str]) -> str:
        ch = self._validate_channel(channel)
        response = (self._query(f"SOUR{ch}:APPLy?")).strip()
        self._logger.debug(f"Channel {ch}: Configuration summary (APPLy?) returned: {response}")
        if response.startswith('"') and response.endswith('"') and response.count('"') == 2 : return response[1:-1]
        return response

    @validate_call
    def get_complete_config(self, channel: Union[int, str]) -> WaveformConfigResult:
        ch_num = self._validate_channel(channel)
        self._logger.debug(f"Getting complete configuration snapshot for channel {ch_num}...")
        func_scpi_str = self.get_function(ch_num)
        freq = self.get_frequency(ch_num)
        ampl = self.get_amplitude(ch_num)
        offs = self.get_offset(ch_num)
        output_state_enum = self.get_output_state(ch_num)
        output_state_bool = True if output_state_enum == SCPIOnOff.ON else False
        load_impedance_val = self.get_output_load_impedance(ch_num)
        load_impedance_str: Union[str, float]
        if isinstance(load_impedance_val, OutputLoadImpedance) and load_impedance_val == OutputLoadImpedance.INFINITY:
            load_impedance_str = "INFinity"
        else:
            load_impedance_str = float(load_impedance_val)
        voltage_unit_enum = self.get_voltage_unit(ch_num)
        voltage_unit_str = voltage_unit_enum.value
        phase: Optional[float] = None
        if func_scpi_str not in [WaveformType.DC.value, WaveformType.NOISE.value]:
            try:
                phase = self.get_phase(ch_num)
            except InstrumentCommunicationError as e:
                self._log(f"Note: Phase query failed for CH{ch_num} (function: {func_scpi_str}): {e}", level="info")
        symmetry: Optional[float] = None
        duty_cycle: Optional[float] = None
        try:
            if func_scpi_str == WaveformType.RAMP.value:
                symmetry = self.get_ramp_symmetry(ch_num)
            elif func_scpi_str == WaveformType.SQUARE.value:
                duty_cycle = self.get_square_duty_cycle(ch_num)
            elif func_scpi_str == WaveformType.PULSE.value:
                duty_cycle = self.get_pulse_duty_cycle(ch_num)
        except InstrumentCommunicationError as e:
            self._log(f"Note: Query failed for function-specific parameter for CH{ch_num} func {func_scpi_str}: {e}", level="info")
        return WaveformConfigResult(channel=ch_num, function=func_scpi_str, frequency=freq, amplitude=ampl, offset=offs, phase=phase, symmetry=symmetry, duty_cycle=duty_cycle, output_state=output_state_bool, load_impedance=load_impedance_str, voltage_unit=voltage_unit_str)

    def enable_modulation(self, channel: Union[int, str], mod_type: str, state: bool) -> None:
        ch = self._validate_channel(channel)
        mod_upper = mod_type.upper().strip()
        valid_mods = {"AM", "FM", "PM", "PWM", "FSK", "BPSK", "SUM"}
        if mod_upper not in valid_mods:
            raise InstrumentParameterError(
                parameter="mod_type",
                value=mod_type,
                valid_range=valid_mods,
                message="Invalid modulation type.",
            )
        cmd_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        self._send_command(f"SOUR{ch}:{mod_upper}:STATe {cmd_state}")
        self._logger.log(f"Channel {ch}: {mod_upper} modulation state set to {cmd_state}")
        self._error_check()

    def set_am_depth(self, channel: Union[int, str], depth_percent: Union[float, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(depth_percent)
        if isinstance(depth_percent, (int, float)) and not (0 <= float(depth_percent) <= 120):
            self._log(f"Warning: AM depth {depth_percent}% is outside typical 0-120 range.", level="warning")
        self._send_command(f"SOUR{ch}:AM:DEPTh {cmd_val}")
        self._logger.log(f"Channel {ch}: AM depth set to {depth_percent}%")
        self._error_check()

    def set_am_source(self, channel: Union[int, str], source: ModulationSource) -> None:
        ch = self._validate_channel(channel)
        cmd_src = source.value
        if cmd_src == f"CH{ch}":
            raise InstrumentParameterError(
                parameter="source",
                value=source,
                message=f"Channel {ch} cannot be its own AM source.",
            )
        if cmd_src == ModulationSource.CH2.value and self.channel_count < 2:
            raise InstrumentParameterError(
                parameter="source",
                value=source,
                message="CH2 source invalid for 1-channel instrument.",
            )
        self._send_command(f"SOUR{ch}:AM:SOURce {cmd_src}")
        self._logger.log(f"Channel {ch}: AM source set to {cmd_src}")
        self._error_check()

    def set_fm_deviation(self, channel: Union[int, str], deviation_hz: Union[float, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(deviation_hz)
        self._send_command(f"SOUR{ch}:FM:DEViation {cmd_val}")
        self._logger.log(f"Channel {ch}: FM deviation set to {deviation_hz} Hz")
        self._error_check()

    def enable_sweep(self, channel: Union[int, str], state: bool) -> None:
        ch = self._validate_channel(channel)
        cmd_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        self._send_command(f"SOUR{ch}:SWEep:STATe {cmd_state}")
        self._logger.log(f"Channel {ch}: Sweep state set to {cmd_state}")
        self._error_check()

    def set_sweep_time(self, channel: Union[int, str], sweep_time_sec: Union[float, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sweep_time_sec)
        self._send_command(f"SOUR{ch}:SWEep:TIME {cmd_val}")
        self._logger.log(f"Channel {ch}: Sweep time set to {sweep_time_sec} s")
        self._error_check()

    def set_sweep_start_frequency(self, channel: Union[int, str], freq_hz: Union[float, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        self._send_command(f"SOUR{ch}:FREQuency:STARt {cmd_val}")
        self._logger.debug(f"Channel {ch}: Sweep start frequency set to {freq_hz} Hz")
        self._error_check()

    def set_sweep_stop_frequency(self, channel: Union[int, str], freq_hz: Union[float, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        self._send_command(f"SOUR{ch}:FREQuency:STOP {cmd_val}")
        self._logger.debug(f"Channel {ch}: Sweep stop frequency set to {freq_hz} Hz")
        self._error_check()

    def set_sweep_spacing(self, channel: Union[int, str], spacing: SweepSpacing) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:SWEep:SPACing {spacing.value}")
        self._logger.debug(f"Channel {ch}: Sweep spacing set to {spacing.value}")
        self._error_check()

    def enable_burst(self, channel: Union[int, str], state: bool) -> None:
        ch = self._validate_channel(channel)
        cmd_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        self._send_command(f"SOUR{ch}:BURSt:STATe {cmd_state}")
        self._logger.log(f"Channel {ch}: Burst state set to {cmd_state}")
        self._error_check()

    def set_burst_mode(self, channel: Union[int, str], mode: BurstMode) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:BURSt:MODE {mode.value}")
        self._logger.log(f"Channel {ch}: Burst mode set to {mode.value}")
        self._error_check()

    def set_burst_cycles(self, channel: Union[int, str], n_cycles: Union[int, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val: str
        log_val: Union[int, str] = n_cycles
        if isinstance(n_cycles, str):
            nc_upper = n_cycles.upper().strip()
            if nc_upper in {"MIN", "MINIMUM"}:
                cmd_val = OutputLoadImpedance.MINIMUM.value
            elif nc_upper in {"MAX", "MAXIMUM"}:
                cmd_val = OutputLoadImpedance.MAXIMUM.value
            elif nc_upper in {"INF", "INFINITY"}:
                cmd_val = "INFinity"
            else:
                raise InstrumentParameterError(
                    parameter="n_cycles",
                    value=n_cycles,
                    message="Invalid string for burst cycles.",
                )
        elif isinstance(n_cycles, int):
            if n_cycles < 1:
                raise InstrumentParameterError(
                    parameter="n_cycles",
                    value=n_cycles,
                    message="Burst cycle count must be positive.",
                )
            inst_max_cycles = 100_000_000
            if n_cycles > inst_max_cycles:
                self._log(f"Warning: Burst cycles {n_cycles} > typical max ({inst_max_cycles}).", level="warning")
            cmd_val = str(n_cycles)
        else:
            raise InstrumentParameterError(
                parameter="n_cycles",
                value=n_cycles,
                message=f"Invalid type '{type(n_cycles)}' for burst cycles.",
            )
        self._send_command(f"SOUR{ch}:BURSt:NCYCles {cmd_val}")
        self._logger.log(f"Channel {ch}: Burst cycles set to {log_val}")
        self._error_check()

    def set_burst_period(self, channel: Union[int, str], period_sec: Union[float, str]) -> None:
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(period_sec)
        self._send_command(f"SOUR{ch}:BURSt:INTernal:PERiod {cmd_val}")
        self._logger.log(f"Channel {ch}: Internal burst period set to {period_sec} s")
        self._error_check()

    def set_trigger_source(self, channel: Union[int, str], source: TriggerSource) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"TRIGger{ch}:SOURce {source.value}")
        self._logger.log(f"Channel {ch}: Trigger source set to {source.value}")
        self._error_check()

    def set_trigger_slope(self, channel: Union[int, str], slope: TriggerSlope) -> None:
        ch = self._validate_channel(channel)
        self._send_command(f"TRIGger{ch}:SLOPe {slope.value}")
        self._logger.log(f"Channel {ch}: Trigger slope set to {slope.value}")
        self._error_check()

    def trigger_now(self, channel: Optional[Union[int, str]] = None) -> None:
        if channel is not None:
            ch = self._validate_channel(channel)
            self._send_command(f"TRIGger{ch}")
            self._logger.log(f"Sent immediate channel-specific trigger command TRIGger{ch}")
        else:
            self._send_command("*TRG")
            self._logger.log("Sent general bus trigger command *TRG")
        self._error_check()

    def list_directory(self, path: str = "") -> FileSystemInfo:
        path_scpi = f' "{path}"' if path else ""
        cmd = f"MMEMory:CATalog:ALL?{path_scpi}"
        response = (self._query(cmd)).strip()
        try:
            parts = response.split(',', 2)
            if len(parts) < 2:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Unexpected response format from MMEM:CAT?: {response}",
                )
            bytes_used = int(parts[0])
            bytes_free = int(parts[1])
            info = FileSystemInfo(bytes_used=bytes_used, bytes_free=bytes_free)
            if len(parts) > 2 and parts[2]:
                file_pattern = r'"([^"]+),([^"]*),(\d+)"'
                listings = re.findall(file_pattern, parts[2])
                for name, ftype, size_str in listings:
                    file_type = ftype if ftype else 'FILE'
                    try:
                        size = int(size_str)
                    except ValueError:
                        self._log(f"Warning: Could not parse size '{size_str}' for file '{name}'.", level="warning")
                        continue
                    info.files.append({'name': name, 'type': file_type.upper(), 'size': size})
            self._logger.log(f"Directory listing for '{path or 'current dir'}': Used={info.bytes_used}, Free={info.bytes_free}, Items={len(info.files)}")
            return info
        except (ValueError, IndexError) as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse MMEM:CAT? response: '{response}'. Error: {e}",
            ) from e

    def delete_file_or_folder(self, path: str) -> None:
        if not path:
            raise InstrumentParameterError(
                parameter="path", message="Path cannot be empty for deletion."
            )
        path_scpi = f'"{path}"'
        cmd = f"MMEMory:DELete {path_scpi}"
        try:
            self._send_command(cmd)
            self._logger.log(f"Attempted to delete file/folder: '{path}' using MMEM:DELete")
            self._error_check()
        except InstrumentCommunicationError as e:
            code, msg = self.get_error()
            if code != 0:
                if "Directory not empty" in msg or "folder" in msg.lower():
                    raise InstrumentCommunicationError(
                        instrument=self.config.model,
                        command=cmd,
                        message=f"Failed to delete '{path}'. Non-empty folder? Inst Err {code}: {msg}",
                    ) from e
                else:
                    raise InstrumentCommunicationError(
                        instrument=self.config.model,
                        command=cmd,
                        message=f"Failed to delete '{path}'. Inst Err {code}: {msg}",
                    ) from e
            else:
                raise e

    @validate_call
    def channel(self, ch_num: Union[int,str]) -> WGChannelFacade:
        """
        Returns a facade for interacting with a specific channel.

        Args:
            ch_num (Union[int,str]): The channel number (1-based) or string identifier (e.g. "CH1").

        Returns:
            WGChannelFacade: A facade object for the specified channel.

        Raises:
            InstrumentParameterError: If channel number is invalid.
        """
        validated_ch_num = self._validate_channel(ch_num) # _validate_channel returns int
        return WGChannelFacade(self, validated_ch_num)
