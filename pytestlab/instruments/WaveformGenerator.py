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
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, Type # Added Type and Callable

import numpy as np

from .instrument import Instrument
from ..config import WaveformGeneratorConfig
from ..errors import (
    InstrumentCommunicationError,
    InstrumentConfigurationError,
    InstrumentParameterError,
)

# --- Constants for SCPI Parameters ---

# Output Load Impedance
LOAD_INFINITY = "INFinity"
"""SCPI keyword for infinite (high-Z) load impedance."""
LOAD_MINIMUM = "MINimum"
"""SCPI keyword to query/set the minimum load impedance value."""
LOAD_MAXIMUM = "MAXimum"
"""SCPI keyword to query/set the maximum load impedance value."""
LOAD_DEFAULT = "DEFault"
"""SCPI keyword to query/set the default load impedance value."""
VALID_LOAD_STRINGS: set[str] = {LOAD_INFINITY, LOAD_MINIMUM, LOAD_MAXIMUM, LOAD_DEFAULT}
"""Set of valid string arguments for load impedance."""
LOAD_ABBREV_MAP: Dict[str, str] = {"INF": LOAD_INFINITY}
"""Mapping from common abbreviations to full SCPI load keywords."""

# Output Polarity
POLARITY_NORMAL = "NORMal"
"""SCPI keyword for normal output polarity."""
POLARITY_INVERTED = "INVerted"
"""SCPI keyword for inverted output polarity."""
VALID_POLARITIES: set[str] = {POLARITY_NORMAL, POLARITY_INVERTED}
"""Set of valid string arguments for output polarity."""
POLARITY_ABBREV_MAP: Dict[str, str] = {"NORM": POLARITY_NORMAL, "INV": POLARITY_INVERTED}
"""Mapping from common abbreviations to full SCPI polarity keywords."""

# Voltage Units
UNIT_VPP = "VPP"
"""SCPI keyword for Volts Peak-to-Peak unit."""
UNIT_VRMS = "VRMS"
"""SCPI keyword for Volts Root-Mean-Square unit."""
UNIT_DBM = "DBM"
"""SCPI keyword for decibel-milliwatts unit."""
VALID_VOLTAGE_UNITS: set[str] = {UNIT_VPP, UNIT_VRMS, UNIT_DBM}
"""Set of valid string arguments for voltage units."""

# General Boolean States
STATE_ON = "ON"
"""SCPI keyword for the ON state."""
STATE_OFF = "OFF"
"""SCPI keyword for the OFF state."""
VALID_BOOLEAN_STATES: set[str] = {STATE_ON, STATE_OFF}
"""Set of valid string arguments for boolean states (ON/OFF)."""

# Trigger Slope
SLOPE_POSITIVE = "POSitive"
"""SCPI keyword for a positive (rising) edge trigger slope."""
SLOPE_NEGATIVE = "NEGative"
"""SCPI keyword for a negative (falling) edge trigger slope."""
VALID_SLOPES: set[str] = {SLOPE_POSITIVE, SLOPE_NEGATIVE}
"""Set of valid string arguments for trigger slope."""
SLOPE_ABBREV_MAP: Dict[str, str] = {"POS": SLOPE_POSITIVE, "NEG": SLOPE_NEGATIVE}
"""Mapping from common abbreviations to full SCPI slope keywords."""

# Trigger Source
SOURCE_IMMEDIATE = "IMMediate"
"""SCPI keyword for the immediate (internal) trigger source."""
SOURCE_EXTERNAL = "EXTernal"
"""SCPI keyword for the external trigger source (Trig In connector)."""
SOURCE_TIMER = "TIMer"
"""SCPI keyword for the timer-based trigger source."""
SOURCE_BUS = "BUS"
"""SCPI keyword for the bus (software) trigger source (*TRG)."""
VALID_TRIGGER_SOURCES: set[str] = {SOURCE_IMMEDIATE, SOURCE_EXTERNAL, SOURCE_TIMER, SOURCE_BUS}
"""Set of valid string arguments for trigger source."""
SOURCE_ABBREV_MAP: Dict[str, str] = {"IMM": SOURCE_IMMEDIATE, "EXT": SOURCE_EXTERNAL, "TIM": SOURCE_TIMER}
"""Mapping from common abbreviations to full SCPI trigger source keywords."""

# Sync Output Mode
SYNC_MODE_NORMAL = "NORMal"
"""SCPI keyword for normal sync output mode (follows waveform/mod/sweep/burst envelope)."""
SYNC_MODE_CARRIER = "CARRier"
"""SCPI keyword for sync output following the carrier frequency."""
SYNC_MODE_MARKER = "MARKer"
"""SCPI keyword for sync output determined by marker settings."""
VALID_SYNC_MODES: set[str] = {SYNC_MODE_NORMAL, SYNC_MODE_CARRIER, SYNC_MODE_MARKER}
"""Set of valid string arguments for sync output mode."""
SYNC_MODE_ABBREV_MAP: Dict[str, str] = {"NORM": SYNC_MODE_NORMAL, "CARR": SYNC_MODE_CARRIER, "MARK": SYNC_MODE_MARKER}
"""Mapping from common abbreviations to full SCPI sync mode keywords."""

# Modulation Source
MOD_SOURCE_INTERNAL = "INTernal"
"""SCPI keyword for the internal modulation source."""
MOD_SOURCE_CH1 = "CH1"
"""SCPI keyword for using Channel 1 as the modulation source."""
MOD_SOURCE_CH2 = "CH2"
"""SCPI keyword for using Channel 2 as the modulation source."""
VALID_MOD_SOURCES: set[str] = {MOD_SOURCE_INTERNAL, MOD_SOURCE_CH1, MOD_SOURCE_CH2}
"""Set of valid string arguments for modulation source."""
MOD_SOURCE_ABBREV_MAP: Dict[str, str] = {"INT": MOD_SOURCE_INTERNAL}
"""Mapping from common abbreviations to full SCPI modulation source keywords."""

# Arbitrary Waveform Filter Type
ARB_FILTER_NORMAL = "NORMal"
"""SCPI keyword for the normal arbitrary waveform filter (flattest frequency response)."""
ARB_FILTER_STEP = "STEP"
"""SCPI keyword for the step arbitrary waveform filter (minimizes overshoot)."""
ARB_FILTER_OFF = "OFF"
"""SCPI keyword to disable the arbitrary waveform filter."""
VALID_ARB_FILTERS: set[str] = {ARB_FILTER_NORMAL, ARB_FILTER_STEP, ARB_FILTER_OFF}
"""Set of valid string arguments for arbitrary waveform filter type."""
ARB_FILTER_ABBREV_MAP: Dict[str, str] = {"NORM": ARB_FILTER_NORMAL}
"""Mapping from common abbreviations to full SCPI arb filter keywords."""

# Arbitrary Waveform Advance Mode
ARB_ADVANCE_TRIGGER = "TRIGger"
"""SCPI keyword to advance arbitrary waveform points via trigger events."""
ARB_ADVANCE_SRATE = "SRATe"
"""SCPI keyword to advance arbitrary waveform points based on the sample rate."""
VALID_ARB_ADVANCE: set[str] = {ARB_ADVANCE_TRIGGER, ARB_ADVANCE_SRATE}
"""Set of valid string arguments for arbitrary waveform advance mode."""
ARB_ADVANCE_ABBREV_MAP: Dict[str, str] = {"TRIG": ARB_ADVANCE_TRIGGER}
"""Mapping from common abbreviations to full SCPI arb advance keywords."""

# Sweep Spacing
SWEEP_LINEAR = "LINear"
"""SCPI keyword for linear frequency sweep spacing."""
SWEEP_LOGARITHMIC = "LOGarithmic"
"""SCPI keyword for logarithmic frequency sweep spacing."""
VALID_SWEEP_SPACING: set[str] = {SWEEP_LINEAR, SWEEP_LOGARITHMIC}
"""Set of valid string arguments for sweep spacing."""
SWEEP_ABBREV_MAP: Dict[str, str] = {"LIN": SWEEP_LINEAR, "LOG": SWEEP_LOGARITHMIC}
"""Mapping from common abbreviations to full SCPI sweep spacing keywords."""

# Burst Mode
BURST_TRIGGERED = "TRIGgered"
"""SCPI keyword for triggered (N-cycle) burst mode."""
BURST_GATED = "GATed"
"""SCPI keyword for gated burst mode."""
VALID_BURST_MODES: set[str] = {BURST_TRIGGERED, BURST_GATED}
"""Set of valid string arguments for burst mode."""
BURST_ABBREV_MAP: Dict[str, str] = {"TRIG": BURST_TRIGGERED, "GAT": BURST_GATED}
"""Mapping from common abbreviations to full SCPI burst mode keywords."""

# Short SCPI Function Names (Keys for WAVEFORM_PARAM_COMMANDS and internal mapping)
FUNC_SIN = "SIN"
FUNC_SQUARE = "SQU"
FUNC_RAMP = "RAMP"
FUNC_PULSE = "PULS"
FUNC_PRBS = "PRBS"
FUNC_NOISE = "NOIS"
FUNC_ARB = "ARB"
FUNC_DC = "DC"
FUNC_TRI = "TRI"

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
        # Consider adding fields for active modulation/sweep/burst state if needed
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
WAVEFORM_PARAM_COMMANDS: Dict[str, Dict[str, Callable[[int, Any], str]]] = {
    FUNC_PULSE: {
        "duty_cycle": lambda ch, v: f"SOUR{ch}:FUNC:PULS:DCYCle {v}",
        "period": lambda ch, v: f"SOUR{ch}:FUNC:PULS:PERiod {v}",
        "width": lambda ch, v: f"SOUR{ch}:FUNC:PULS:WIDTh {v}",
        "transition_both": lambda ch, v: f"SOUR{ch}:FUNC:PULS:TRANsition:BOTH {v}",
        "transition_leading": lambda ch, v: f"SOUR{ch}:FUNC:PULS:TRANsition:LEADing {v}",
        "transition_trailing": lambda ch, v: f"SOUR{ch}:FUNC:PULS:TRANsition:TRAiling {v}",
        "hold_mode": lambda ch, v: f"SOUR{ch}:FUNC:PULS:HOLD {str(v).upper()}", # Expects WIDTh or DCYCle
    },
    FUNC_SQUARE: {
        "duty_cycle": lambda ch, v: f"SOUR{ch}:FUNC:SQUare:DCYCle {v}",
        "period": lambda ch, v: f"SOUR{ch}:FUNC:SQUare:PERiod {v}",
    },
    FUNC_RAMP: {
        "symmetry": lambda ch, v: f"SOUR{ch}:FUNC:RAMP:SYMMetry {v}",
    },
    FUNC_TRI: {
        # Triangle symmetry is controlled via the RAMP symmetry command
        "symmetry": lambda ch, v: f"SOUR{ch}:FUNC:RAMP:SYMMetry {v}",
    },
    FUNC_SIN: {},
    FUNC_PRBS: {
        "bit_rate": lambda ch, v: f"SOUR{ch}:FUNC:PRBS:BRATe {v}",
        "data_type": lambda ch, v: f"SOUR{ch}:FUNC:PRBS:DATA {str(v).upper()}", # Expects PN7, PN9, etc.
        "transition_both": lambda ch, v: f"SOUR{ch}:FUNC:PRBS:TRANsition:BOTH {v}",
    },
    FUNC_NOISE: {
        "bandwidth": lambda ch, v: f"SOUR{ch}:FUNC:NOISe:BANDwidth {v}",
    },
    FUNC_ARB: {
        "sample_rate": lambda ch, v: f"SOUR{ch}:FUNC:ARB:SRATe {v}",
        "filter": lambda ch, v: f"SOUR{ch}:FUNC:ARB:FILTer {str(v).upper()}", # Expects NORMal, STEP, OFF
        "advance_mode": lambda ch, v: f"SOUR{ch}:FUNC:ARB:ADVance {str(v).upper()}", # Expects TRIGger, SRATe
        "frequency": lambda ch, v: f"SOUR{ch}:FUNC:ARB:FREQ {v}",
        "period": lambda ch, v: f"SOUR{ch}:FUNC:ARB:PER {v}",
        "ptpeak_voltage": lambda ch, v: f"SOUR{ch}:FUNC:ARB:PTP {v}", 
    },
    FUNC_DC: {}
}


class WaveformGenerator(Instrument):
    """
    Provides a high-level Python interface for controlling Keysight EDU33210
    Series Trueform Arbitrary Waveform Generators via SCPI commands.
    ...
    """
    def __init__(self, config: WaveformGeneratorConfig, debug_mode: bool = False) -> None:
        """
        Initializes the WaveformGenerator instance.
        ...
        """
        if not isinstance(config, WaveformGeneratorConfig):
            raise InstrumentConfigurationError("WaveformGenerator requires a WaveformGeneratorConfig object.")
        super().__init__(config=config, debug_mode=debug_mode)

        self.config: WaveformGeneratorConfig = config
        self._channel_count: int

        try:
            if hasattr(self.config.channels, 'channels') and isinstance(self.config.channels.channels, dict):
                self._channel_count = len(self.config.channels.channels)
            elif hasattr(self.config.channels, 'count'): # type: ignore
                 self._channel_count = self.config.channels.count # type: ignore
            else:
                 raise InstrumentConfigurationError("Cannot determine channel count from config.channels structure.")

            if not isinstance(self._channel_count, int) or self._channel_count <= 0:
                 raise InstrumentConfigurationError(f"Invalid channel count determined: {self._channel_count}")

            self._log(f"Detected {self._channel_count} channels from configuration.")

        except (AttributeError, InstrumentConfigurationError) as e:
            self._log(f"Error determining channel count from config: {e}. Please check config structure.", level="error")
            raise InstrumentConfigurationError("Could not determine channel count from configuration.", cause=e) from e
        except Exception as e:
            self._log(f"Unexpected error accessing channel count from config: {e}", level="error")
            raise InstrumentConfigurationError("Unexpected error accessing channel count.", cause=e) from e

    @property
    def channel_count(self) -> int:
        """
        Returns the number of output channels supported by this instrument.
        ...
        """
        return self._channel_count


    @classmethod
    def from_config(cls: Type[WaveformGenerator], config: WaveformGeneratorConfig, debug_mode: bool =False) -> WaveformGenerator:
        # Assuming WaveformGeneratorConfig can be spread if it's a dict-like structure
        # If config is already a WaveformGeneratorConfig instance, this might need adjustment
        # or the caller should ensure it's a dict.
        # For now, assuming it's a dict that can be spread into the constructor.
        # If config is already a WaveformGeneratorConfig instance, it should be:
        # return cls(config=config, debug_mode=debug_mode)
        # Based on the __init__ type hint, config should be WaveformGeneratorConfig.
        # The AutoInstrument likely passes a dict, so **config is appropriate for that case.
        # If direct instantiation with a config object, then no **.
        # Let's assume it's a dict for now, as per typical AutoInstrument behavior.
        # However, the __init__ expects WaveformGeneratorConfig.
        # This implies the caller of from_config should pass a dict that can be used to init WaveformGeneratorConfig.
        # Or, if config is already WaveformGeneratorConfig, then just pass it.
        # Given the __init__ signature, if config is already a WaveformGeneratorConfig, then:
        return cls(config=config, debug_mode=debug_mode)

    def _validate_channel(self, channel: Union[int, str]) -> int:
        """
        Validates the provided channel identifier and returns the integer channel number.
        ...
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
                         raise ValueError(f"Could not parse channel number from '{channel}'.") from e
                else:
                     raise InstrumentParameterError(f"Invalid channel string format: '{channel}'. Use integer, 'CHx', or 'CHANNELx'.")
            else:
                try:
                    ch_num = int(channel) 
                except ValueError:
                    raise InstrumentParameterError(f"Invalid channel string format: '{channel}'. Use integer, 'CHx', or 'CHANNELx'.")
        elif isinstance(channel, int):
             ch_num = channel
        else:
            raise InstrumentParameterError(f"Invalid channel type: {type(channel)}. Expected int or str.")

        try:
            return self.config.channels.validate(ch_num)
        except InstrumentParameterError:
             raise 
        except Exception as e:
             self._log(f"Unexpected error during channel validation for {ch_num}: {e}", level="error")
             raise InstrumentConfigurationError(f"Channel validation failed unexpectedly for {ch_num}.", cause=e) from e

    def _get_scpi_function_name(self, user_function_name: str) -> str:
        """
        Translates a user-friendly function name or SCPI name to the canonical short SCPI name.
        ...
        """
        if not hasattr(self.config.waveforms, 'built_in') or \
           not hasattr(self.config.waveforms.built_in, 'options'):
            raise InstrumentConfigurationError("Configuration error: Missing 'waveforms.built_in.options'.")

        options = self.config.waveforms.built_in.options
        lookup_key = user_function_name.strip().upper()

        name_to_short_scpi: Dict[str, str] = {
            "SINE": FUNC_SIN, "SINUSOID": FUNC_SIN, FUNC_SIN: FUNC_SIN,
            "SQUARE": FUNC_SQUARE, FUNC_SQUARE: FUNC_SQUARE,
            "RAMP": FUNC_RAMP, FUNC_RAMP: FUNC_RAMP,
            "PULSE": FUNC_PULSE, FUNC_PULSE: FUNC_PULSE,
            "PRBS": FUNC_PRBS, FUNC_PRBS: FUNC_PRBS,
            "NOISE": FUNC_NOISE, FUNC_NOISE: FUNC_NOISE,
            "ARBITRARY": FUNC_ARB, "ARB": FUNC_ARB, FUNC_ARB: FUNC_ARB, 
            "DC": FUNC_DC, FUNC_DC: FUNC_DC,
            "TRIANGLE": FUNC_TRI, "TRI": FUNC_TRI, FUNC_TRI: FUNC_TRI, 
        }

        if lookup_key in name_to_short_scpi:
            short_name = name_to_short_scpi[lookup_key]
            supported_short_names: set[str] = set()
            if isinstance(options, dict):
                supported_short_names = {str(v).upper() for v in options.values()}
            elif isinstance(options, list):
                for opt in options:
                    opt_upper = str(opt).upper()
                    if opt_upper in name_to_short_scpi:
                        supported_short_names.add(name_to_short_scpi[opt_upper])
                    else:
                        self._log(f"Warning: Config waveform option '{opt}' not recognized in internal mapping.", level="warning")
            
            if short_name in supported_short_names:
                return short_name
        
        if isinstance(options, dict):
            if lookup_key in options: 
                scpi_val = str(options[lookup_key])
                return name_to_short_scpi.get(scpi_val.upper(), scpi_val) 
            valid_scpi_values_in_cfg = {str(v).upper() for v in options.values()}
            if lookup_key in valid_scpi_values_in_cfg: 
                return lookup_key 
            raise InstrumentParameterError(
                f"Unknown waveform type '{user_function_name}'. "
                f"Supported user types: {list(options.keys())} or SCPI values: {list(options.values())}"
            )
        elif isinstance(options, list):
            options_upper = [str(opt).upper() for opt in options]
            if lookup_key in options_upper:
                original_index = options_upper.index(lookup_key)
                config_name = str(options[original_index]) 
                return name_to_short_scpi.get(config_name.upper(), config_name) 
            raise InstrumentParameterError(
                f"Unknown waveform type '{user_function_name}'. "
                f"Supported types from config list: {options}"
            )
        else:
            raise InstrumentConfigurationError(f"Unexpected format for built_in waveform options: {type(options)}")


    def _format_value_min_max_def(self, value: Union[float, int, str]) -> str:
        """
        Formats numeric values or special string keywords for SCPI commands.
        ...
        """
        if isinstance(value, str):
            val_upper = value.upper().strip()
            special_strings_map: Dict[str, str] = {
                "MIN": LOAD_MINIMUM, "MINIMUM": LOAD_MINIMUM,
                "MAX": LOAD_MAXIMUM, "MAXIMUM": LOAD_MAXIMUM,
                "DEF": LOAD_DEFAULT, "DEFAULT": LOAD_DEFAULT,
                "INF": LOAD_INFINITY, "INFINITY": LOAD_INFINITY
            }
            if val_upper in special_strings_map:
                return special_strings_map[val_upper]
            else:
                try:
                    num_val = float(value)
                    return f"{num_val:.12G}"
                except ValueError:
                    raise InstrumentParameterError(
                        f"Invalid parameter string '{value}'. Expected a number or "
                        f"one of MIN/MAX/DEF/INF (case-insensitive)."
                    )
        elif isinstance(value, (int, float)):
            return f"{float(value):.12G}"
        else:
            raise InstrumentParameterError(f"Invalid parameter type: {type(value)}. Expected number or string.")

    def set_function(self, channel: Union[int, str], function_type: str, **kwargs: Any) -> None:
        """
        Sets the primary waveform function and associated parameters for a channel.
        ...
        """
        ch = self._validate_channel(channel)
        scpi_func_short = self._get_scpi_function_name(function_type) 

        standard_params_set: Dict[str, bool] = {}
        if 'frequency' in kwargs and scpi_func_short != FUNC_ARB:
            self.set_frequency(ch, kwargs.pop('frequency'))
            standard_params_set['frequency'] = True
        if 'amplitude' in kwargs:
             self.set_amplitude(ch, kwargs.pop('amplitude'))
             standard_params_set['amplitude'] = True
        if 'offset' in kwargs:
             self.set_offset(ch, kwargs.pop('offset'))
             standard_params_set['offset'] = True

        self._send_command(f"SOUR{ch}:FUNC {scpi_func_short}")
        self._log(f"Channel {ch}: Function set to {function_type} (SCPI: {scpi_func_short})")
        self._error_check()

        if kwargs:
            param_cmds_for_func = WAVEFORM_PARAM_COMMANDS.get(scpi_func_short)
            if not param_cmds_for_func:
                self._log(f"Warning: No specific parameters defined for SCPI function '{scpi_func_short}'. "
                          f"Ignoring remaining kwargs: {kwargs}", level="warning")
                if any(k not in standard_params_set for k in kwargs):
                     raise InstrumentParameterError(f"Unknown parameters {list(kwargs.keys())} passed for function {function_type}.")
                return 

            for param_name, value in kwargs.items():
                if param_name in param_cmds_for_func:
                    try:
                        if param_name in ["duty_cycle", "symmetry"] and isinstance(value, (int, float)):
                            if not (0 <= float(value) <= 100):
                                self._log(f"Warning: Parameter '{param_name}' value {value}% is outside the "
                                          f"typical 0-100 range. Instrument validation will apply.", level="warning")
                        
                        formatted_value = self._format_value_min_max_def(value)
                        cmd_lambda = param_cmds_for_func[param_name]
                        cmd = cmd_lambda(ch, formatted_value)

                        self._send_command(cmd)
                        self._log(f"Channel {ch}: Parameter '{param_name}' set to {value}")
                        self._error_check()
                    except InstrumentParameterError as ipe:
                        raise InstrumentParameterError(
                            f"Invalid value '{value}' provided for parameter '{param_name}' "
                            f"of function '{function_type}'. Cause: {ipe}"
                        ) from ipe
                    except InstrumentCommunicationError:
                         raise 
                    except Exception as e:
                        self._log(f"Error setting parameter '{param_name}' for function '{scpi_func_short}': {e}", level="error")
                        raise InstrumentCommunicationError(f"Failed to set parameter {param_name}", cause=e) from e
                else:
                    raise InstrumentParameterError(
                        f"Parameter '{param_name}' is not supported for function '{function_type}' ({scpi_func_short}). "
                        f"Supported specific parameters: {list(param_cmds_for_func.keys())}"
                    )

    def get_function(self, channel: Union[int, str]) -> str:
        """
        Queries the instrument for the currently selected waveform function.
        ...
        """
        ch = self._validate_channel(channel)
        scpi_func = self._query(f"SOUR{ch}:FUNC?").strip()
        self._log(f"Channel {ch}: Current function is {scpi_func}")
        return scpi_func

    def set_frequency(self, channel: Union[int, str], frequency: Union[float, str]) -> None:
        """
        Sets the output frequency for the selected waveform function.
        ...
        """
        ch = self._validate_channel(channel)
        freq_cmd_val = self._format_value_min_max_def(frequency)

        if isinstance(frequency, (int, float)) and hasattr(self.config.channels.get_channel(ch), 'frequency'): # type: ignore
             channel_config = self.config.channels.get_channel(ch)
             if channel_config and hasattr(channel_config.frequency, 'in_range'): # type: ignore
                 try:
                     channel_config.frequency.in_range(float(frequency)) # type: ignore
                 except InstrumentParameterError as e:
                     self._log(f"Warning: Frequency {frequency} Hz is outside the basic range defined "
                               f"in the configuration. Instrument will perform final validation. Config error: {e}",
                               level="warning")

        self._send_command(f"SOUR{ch}:FREQ {freq_cmd_val}")
        self._log(f"Channel {ch}: Frequency set to {frequency} Hz")
        self._error_check()

    def get_frequency(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current output frequency or its limits for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:FREQ?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum limit)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum limit)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        try:
            freq = float(response)
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse frequency float from response: '{response}'")

        self._log(f"Channel {ch}: Frequency{type_str} is {freq} Hz")
        return freq

    def set_amplitude(self, channel: Union[int, str], amplitude: Union[float, str]) -> None:
        """
        Sets the output amplitude for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        amp_cmd_val = self._format_value_min_max_def(amplitude)
        self._send_command(f"SOUR{ch}:VOLTage {amp_cmd_val}")
        unit = self.get_voltage_unit(ch) 
        self._log(f"Channel {ch}: Amplitude set to {amplitude} (in current unit: {unit})")
        self._error_check()

    def get_amplitude(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current output amplitude or its limits for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum limit)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum limit)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        try:
            amp = float(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Failed to parse amplitude float from response: '{response}'")

        unit = self.get_voltage_unit(ch) 
        self._log(f"Channel {ch}: Amplitude{type_str} is {amp} {unit}")
        return amp

    def set_offset(self, channel: Union[int, str], offset: Union[float, str]) -> None:
        """
        Sets the DC offset voltage for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        offset_cmd_val = self._format_value_min_max_def(offset)
        self._send_command(f"SOUR{ch}:VOLTage:OFFSet {offset_cmd_val}")
        self._log(f"Channel {ch}: Offset set to {offset} V")
        self._error_check()

    def get_offset(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current DC offset voltage or its limits for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage:OFFSet?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum limit)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum limit)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        try:
            offs = float(response)
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse offset float from response: '{response}'")

        self._log(f"Channel {ch}: Offset{type_str} is {offs} V")
        return offs

    def set_phase(self, channel: Union[int, str], phase: Union[float, str]) -> None:
        """
        Sets the phase offset for the waveform on the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        phase_cmd_val = self._format_value_min_max_def(phase)
        self._send_command(f"SOUR{ch}:PHASe {phase_cmd_val}")
        unit = self.get_angle_unit() 
        self._log(f"Channel {ch}: Phase set to {phase} (in current unit: {unit})")
        self._error_check()

    def get_phase(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current phase offset or its limits for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:PHASe?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum limit)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum limit)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        try:
            ph = float(response)
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse phase float from response: '{response}'")

        unit = self.get_angle_unit() 
        self._log(f"Channel {ch}: Phase{type_str} is {ph} {unit}")
        return ph

    def set_phase_reference(self, channel: Union[int, str]) -> None:
        """
        Defines the current phase of the waveform as the new zero-phase reference.
        ...
        """
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:PHASe:REFerence")
        self._log(f"Channel {ch}: Phase reference reset (current phase defined as 0).")
        self._error_check()

    def synchronize_phase_all_channels(self) -> None:
        """
        Synchronizes the phase generators of all output channels and internal sources.
        ...
        """
        if self.channel_count < 2:
            self._log("Warning: Phase synchronization command sent, but primarily intended for multi-channel instruments.", level="warning")
        self._send_command("PHASe:SYNChronize")
        self._log("All channels/internal phase generators synchronized.")
        self._error_check()

    def set_phase_unlock_error_state(self, state: bool) -> None:
        """
        Configures error reporting for internal timebase phase-lock loss.
        ...
        """
        cmd_state = STATE_ON if state else STATE_OFF
        self._send_command(f"SOUR1:PHASe:UNLock:ERRor:STATe {cmd_state}")
        self._log(f"Phase unlock error state set to {cmd_state}")
        self._error_check()

    def get_phase_unlock_error_state(self) -> bool:
        """
        Queries whether error generation for phase unlock is enabled.
        ...
        """
        response = self._query("SOUR1:PHASe:UNLock:ERRor:STATe?").strip()
        state = response == "1"
        self._log(f"Phase unlock error state is {'ON' if state else 'OFF'}")
        return state

    def set_output_state(self, channel: Union[int, str], state: bool) -> None:
        """
        Enables (ON) or disables (OFF) the main signal output connector.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        self._send_command(f"OUTPut{ch}:STATe {cmd_state}")
        self._log(f"Channel {ch}: Output state set to {cmd_state}")
        self._error_check()

    def get_output_state(self, channel: Union[int, str]) -> bool:
        """
        Queries the current state of the main signal output connector.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"OUTPut{ch}:STATe?").strip()
        state = response == "1"
        self._log(f"Channel {ch}: Output state is {'ON' if state else 'OFF'}")
        return state

    def set_output_load_impedance(self, channel: Union[int, str], impedance: Union[float, str]) -> None:
        """
        Sets the expected load impedance connected to the channel's output.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_impedance = self._format_value_min_max_def(impedance)
        self._send_command(f"OUTPut{ch}:LOAD {cmd_impedance}")
        self._log(f"Channel {ch}: Output load impedance setting updated to {impedance}")
        self._error_check()

    def get_output_load_impedance(self, channel: Union[int, str], query_type: Optional[str] = None) -> Union[float, str]:
        """
        Queries the configured output load impedance setting or its limits.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"OUTPut{ch}:LOAD?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum limit)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum limit)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        self._log(f"Channel {ch}: Raw impedance response{type_str} is '{response}'")

        try:
            numeric_response = float(response)
            if abs(numeric_response - 9.9e37) < 1e30:
                return LOAD_INFINITY
            else:
                return numeric_response
        except ValueError:
            if response.upper() == LOAD_INFINITY.upper() or response.upper() == "INF":
                 return LOAD_INFINITY
            self._log(f"Warning: Unexpected non-numeric impedance response: {response}", level="warning")
            raise InstrumentCommunicationError(f"Could not parse impedance response: '{response}'")

    def set_output_polarity(self, channel: Union[int, str], polarity: str) -> None:
        """
        Sets the output polarity for the channel's waveform.
        ...
        """
        ch = self._validate_channel(channel)
        pol_upper = polarity.upper().strip()

        cmd_polarity: str
        if pol_upper in POLARITY_ABBREV_MAP:
            cmd_polarity = POLARITY_ABBREV_MAP[pol_upper]
        elif pol_upper == POLARITY_NORMAL.upper():
             cmd_polarity = POLARITY_NORMAL
        elif pol_upper == POLARITY_INVERTED.upper():
             cmd_polarity = POLARITY_INVERTED
        else:
            raise InstrumentParameterError(f"Invalid polarity '{polarity}'. Use NORMal or INVerted.")

        self._send_command(f"OUTPut{ch}:POLarity {cmd_polarity}")
        self._log(f"Channel {ch}: Output polarity set to {cmd_polarity}")
        self._error_check()

    def get_output_polarity(self, channel: Union[int, str]) -> str:
        """
        Queries the current output polarity for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"OUTPut{ch}:POLarity?").strip().upper()

        pol_str: str
        if response == POLARITY_NORMAL[:4]: 
            pol_str = POLARITY_NORMAL
        elif response == POLARITY_INVERTED[:3]: 
            pol_str = POLARITY_INVERTED
        else:
             self._log(f"Warning: Unexpected polarity response '{response}'. Returning raw.", level="warning")
             pol_str = response 

        self._log(f"Channel {ch}: Output polarity is {pol_str}")
        return pol_str

    def set_voltage_unit(self, channel: Union[int, str], unit: str) -> None:
        """
        Selects the units used for setting and querying the output amplitude.
        ...
        """
        ch = self._validate_channel(channel)
        unit_upper = unit.upper().strip()

        if unit_upper not in VALID_VOLTAGE_UNITS:
            raise InstrumentParameterError(f"Invalid voltage unit '{unit}'. Use VPP, VRMS, or DBM.")

        self._send_command(f"SOUR{ch}:VOLTage:UNIT {unit_upper}")
        self._log(f"Channel {ch}: Voltage unit set to {unit_upper}")
        self._error_check() 

    def get_voltage_unit(self, channel: Union[int, str]) -> str:
        """
        Queries the currently selected voltage unit for amplitude settings.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:VOLTage:UNIT?").strip().upper()
        if response not in VALID_VOLTAGE_UNITS:
             self._log(f"Warning: Unexpected voltage unit response '{response}'. Returning raw.", level="warning")
        self._log(f"Channel {ch}: Voltage unit is {response}")
        return response

    def set_voltage_limits_state(self, channel: Union[int, str], state: bool) -> None:
        """
        Enables or disables the user-defined output voltage limits.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:STATe {cmd_state}")
        self._log(f"Channel {ch}: Voltage limits state set to {cmd_state}")
        self._error_check() 

    def get_voltage_limits_state(self, channel: Union[int, str]) -> bool:
        """
        Queries the current state of the output voltage limits.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:VOLTage:LIMit:STATe?").strip()
        state = response == "1"
        self._log(f"Channel {ch}: Voltage limits state is {'ON' if state else 'OFF'}")
        return state

    def set_voltage_limit_high(self, channel: Union[int, str], voltage: Union[float, str]) -> None:
        """
        Sets the high voltage limit boundary for the output signal.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(voltage)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:HIGH {cmd_val}")
        self._log(f"Channel {ch}: Voltage high limit set to {voltage} V")
        self._error_check() 

    def get_voltage_limit_high(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the configured high voltage limit or its possible MIN/MAX values.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage:LIMit:HIGH?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum possible)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum possible)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        try:
            val = float(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Failed to parse high limit float from response: '{response}'")

        self._log(f"Channel {ch}: Voltage high limit{type_str} is {val} V")
        return val

    def set_voltage_limit_low(self, channel: Union[int, str], voltage: Union[float, str]) -> None:
        """
        Sets the low voltage limit boundary for the output signal.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(voltage)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:LOW {cmd_val}")
        self._log(f"Channel {ch}: Voltage low limit set to {voltage} V")
        self._error_check() 

    def get_voltage_limit_low(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the configured low voltage limit or its possible MIN/MAX values.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:VOLTage:LIMit:LOW?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum possible)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum possible)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        try:
            val = float(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Failed to parse low limit float from response: '{response}'")

        self._log(f"Channel {ch}: Voltage low limit{type_str} is {val} V")
        return val

    def set_voltage_autorange_state(self, channel: Union[int, str], state: str) -> None:
        """
        Configures automatic selection of output amplifier gain ranges.
        ...
        """
        ch = self._validate_channel(channel)
        state_upper = state.upper().strip()
        valid_states = {STATE_ON, STATE_OFF, "ONCE"}
        if state_upper not in valid_states:
            raise InstrumentParameterError(f"Invalid autorange state '{state}'. Allowed: ON, OFF, ONCE.")

        self._send_command(f"SOUR{ch}:VOLTage:RANGe:AUTO {state_upper}")
        self._log(f"Channel {ch}: Voltage autorange state set to {state_upper}")
        self._error_check()

    def get_voltage_autorange_state(self, channel: Union[int, str]) -> str:
        """
        Queries the current voltage autoranging state.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:VOLTage:RANGe:AUTO?").strip()
        state_str = STATE_ON if response == "1" else STATE_OFF
        self._log(f"Channel {ch}: Voltage autorange state is {state_str} (Query response: {response})")
        return state_str

    def set_sync_output_state(self, state: bool) -> None:
        """
        Enables (ON) or disables (OFF) the front panel Sync output connector.
        ...
        """
        cmd_state = STATE_ON if state else STATE_OFF
        self._send_command(f"OUTPut:SYNC:STATe {cmd_state}")
        self._log(f"Sync output state set to {cmd_state}")
        self._error_check()

    def get_sync_output_state(self) -> bool:
        """
        Queries the state of the Sync output connector.
        ...
        """
        response = self._query("OUTPut:SYNC:STATe?").strip()
        state = response == "1"
        self._log(f"Sync output state is {'ON' if state else 'OFF'}")
        return state

    def set_sync_output_mode(self, channel: Union[int, str], mode: str) -> None:
        """
        Sets the behavior of the Sync signal relative to the channel's operation.
        ...
        """
        ch = self._validate_channel(channel)
        mode_upper = mode.upper().strip()

        cmd_mode: str
        if mode_upper in SYNC_MODE_ABBREV_MAP:
             cmd_mode = SYNC_MODE_ABBREV_MAP[mode_upper]
        elif mode_upper == SYNC_MODE_NORMAL.upper():
             cmd_mode = SYNC_MODE_NORMAL
        elif mode_upper == SYNC_MODE_CARRIER.upper():
             cmd_mode = SYNC_MODE_CARRIER
        elif mode_upper == SYNC_MODE_MARKER.upper():
             cmd_mode = SYNC_MODE_MARKER
        else:
             raise InstrumentParameterError(f"Invalid sync mode '{mode}'. Use NORMal, CARRier, or MARKer.")

        self._send_command(f"OUTPut{ch}:SYNC:MODE {cmd_mode}")
        self._log(f"Channel {ch}: Sync output mode set to {cmd_mode}")
        self._error_check()

    def get_sync_output_mode(self, channel: Union[int, str]) -> str:
        """
        Queries the Sync signal mode configured for the specified channel.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"OUTPut{ch}:SYNC:MODE?").strip().upper()

        mode_map_inv: Dict[str, str] = {v[:4]: v for v in VALID_SYNC_MODES} 
        mode_str = mode_map_inv.get(response, response) 

        self._log(f"Channel {ch}: Sync output mode is {mode_str}")
        return mode_str

    def set_sync_output_polarity(self, channel: Union[int, str], polarity: str) -> None:
        """
        Sets the polarity of the Sync output signal associated with a channel.
        ...
        """
        ch = self._validate_channel(channel)
        pol_upper = polarity.upper().strip()

        cmd_polarity: str
        if pol_upper in POLARITY_ABBREV_MAP:
            cmd_polarity = POLARITY_ABBREV_MAP[pol_upper]
        elif pol_upper == POLARITY_NORMAL.upper():
             cmd_polarity = POLARITY_NORMAL
        elif pol_upper == POLARITY_INVERTED.upper():
             cmd_polarity = POLARITY_INVERTED
        else:
            raise InstrumentParameterError(f"Invalid polarity '{polarity}'. Use NORMal or INVerted.")

        self._send_command(f"OUTPut{ch}:SYNC:POLarity {cmd_polarity}")
        self._log(f"Channel {ch}: Sync output polarity set to {cmd_polarity}")
        self._error_check()

    def get_sync_output_polarity(self, channel: Union[int, str]) -> str:
        """
        Queries the polarity of the Sync output signal associated with a channel.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"OUTPut{ch}:SYNC:POLarity?").strip().upper()

        pol_str: str
        if response == POLARITY_NORMAL[:4]: 
            pol_str = POLARITY_NORMAL
        elif response == POLARITY_INVERTED[:3]: 
            pol_str = POLARITY_INVERTED
        else:
             self._log(f"Warning: Unexpected sync polarity response '{response}'. Returning raw.", level="warning")
             pol_str = response 

        self._log(f"Channel {ch}: Sync output polarity is {pol_str}")
        return pol_str

    def set_sync_output_source(self, source_channel: Union[int, str]) -> None:
        """
        Selects which channel drives the front panel Sync output connector.
        ...
        """
        src_ch_num = self._validate_channel(source_channel) 

        if src_ch_num > self.channel_count:
             raise InstrumentParameterError(
                 f"Cannot set sync source to CH{src_ch_num}. Instrument only has {self.channel_count} channels."
             )

        self._send_command(f"OUTPut:SYNC:SOURce CH{src_ch_num}")
        self._log(f"Sync output source set to CH{src_ch_num}")
        self._error_check()

    def get_sync_output_source(self) -> int:
        """
        Queries which channel is currently driving the front panel Sync output connector.
        ...
        """
        response = self._query("OUTPut:SYNC:SOURce?").strip().upper()
        src_ch: int
        if response == "CH1":
             src_ch = 1
        elif response == "CH2":
             src_ch = 2
        else:
             raise InstrumentCommunicationError(f"Unexpected response querying Sync source: '{response}'")

        self._log(f"Sync output source is CH{src_ch}")
        return src_ch

    def select_arbitrary_waveform(self, channel: Union[int, str], arb_name: str) -> None:
        """
        Selects a previously loaded arbitrary waveform from volatile memory.
        ...
        """
        ch = self._validate_channel(channel)
        if not arb_name:
             raise InstrumentParameterError("Arbitrary waveform name cannot be empty.")
        if '"' in arb_name or "'" in arb_name:
             raise InstrumentParameterError("Arbitrary waveform name cannot contain quotes.")

        quoted_arb_name = f'"{arb_name}"'
        self._send_command(f"SOUR{ch}:FUNC:ARB {quoted_arb_name}")
        self._log(f"Channel {ch}: Active arbitrary waveform selection set to '{arb_name}'")
        self._error_check()

    def get_selected_arbitrary_waveform_name(self, channel: Union[int, str]) -> str:
        """
        Queries the name/path of the arbitrary waveform currently selected for ARB mode.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:ARB?").strip()
        self._log(f"Channel {ch}: Currently selected arbitrary waveform is {response}")
        return response

    def set_arbitrary_waveform_sample_rate(self, channel: Union[int, str], sample_rate: Union[float, str]) -> None:
        """
        Sets the sample rate for the arbitrary waveform function.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sample_rate)

        if isinstance(sample_rate, (int, float)):
             channel_config = self.config.channels.get_channel(ch)
             if channel_config and hasattr(channel_config.arbitrary, 'sampling_rate') and \
                hasattr(channel_config.arbitrary.sampling_rate, 'in_range'): # type: ignore
                 try:
                      channel_config.arbitrary.sampling_rate.in_range(float(sample_rate)) # type: ignore
                 except InstrumentParameterError as e:
                      self._log(f"Warning: Sample rate {sample_rate} Sa/s is outside the basic range "
                                f"defined in the configuration. Instrument will perform final validation. "
                                f"Config error: {e}", level="warning")

        self._send_command(f"SOUR{ch}:FUNC:ARB:SRATe {cmd_val}")
        self._log(f"Channel {ch}: Arbitrary waveform sample rate set to {sample_rate} Sa/s")
        self._error_check() 

    def get_arbitrary_waveform_sample_rate(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current sample rate or its limits for the ARB function.
        ...
        """
        ch = self._validate_channel(channel)
        cmd = f"SOUR{ch}:FUNC:ARB:SRATe?"
        type_str = ""
        if query_type:
            qt_upper = query_type.upper()
            if qt_upper == LOAD_MINIMUM.upper():
                 cmd += f" {LOAD_MINIMUM}"
                 type_str = " (MINimum limit)"
            elif qt_upper == LOAD_MAXIMUM.upper():
                 cmd += f" {LOAD_MAXIMUM}"
                 type_str = " (MAXimum limit)"
            else:
                 raise InstrumentParameterError(f"Invalid query_type '{query_type}'. Use MINimum or MAXimum.")

        response = self._query(cmd).strip()
        try:
            sr = float(response)
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse sample rate float from response: '{response}'")

        self._log(f"Channel {ch}: Arbitrary waveform sample rate{type_str} is {sr} Sa/s")
        return sr

    def get_arbitrary_waveform_points(self, channel: Union[int, str]) -> int:
        """
        Queries the number of data points in the currently selected arbitrary waveform.
        ...
        """
        ch = self._validate_channel(channel)
        try:
            response = self._query(f"SOUR{ch}:FUNC:ARB:POINts?").strip()
            points = int(response)
            self._log(f"Channel {ch}: Currently selected arbitrary waveform has {points} points")
            return points
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse integer points from response: '{response}'")
        except InstrumentCommunicationError as e:
            code, msg = self.get_error()
            if code != 0: 
                 self._log(f"Query SOUR{ch}:FUNC:ARB:POINts? failed. Inst Err {code}: {msg}. "
                           f"Is function ARB and waveform selected? Returning 0.", level="warning")
                 return 0 
            else:
                 raise e 

    def download_arbitrary_waveform_data(self,
                                        channel: Union[int, str],
                                        arb_name: str,
                                        data_points: Union[List[int], List[float], np.ndarray],
                                        data_type: str = "DAC",
                                        use_binary: bool = True) -> None:
        """
        Downloads arbitrary waveform data points into the instrument's volatile memory.
        ...
        """
        if use_binary:
            self.download_arbitrary_waveform_data_binary(channel, arb_name, data_points, data_type)
        else:
            self.download_arbitrary_waveform_data_csv(channel, arb_name, data_points, data_type)


    def download_arbitrary_waveform_data_csv(self,
                                        channel: Union[int, str],
                                        arb_name: str,
                                        data_points: Union[List[int], List[float], np.ndarray],
                                        data_type: str = "DAC") -> None:
        """
        Downloads arbitrary waveform data using comma-separated values (CSV).
        ...
        """
        ch = self._validate_channel(channel)
        if not re.match(r"^[a-zA-Z0-9_]{1,12}$", arb_name): 
            raise InstrumentParameterError(
                f"Arbitrary waveform name '{arb_name}' is invalid. Use 1-12 alphanumeric/underscore characters."
            )

        data_type_upper = data_type.upper().strip()
        if data_type_upper not in ["DAC", "NORM"]:
            raise InstrumentParameterError("Invalid data_type. Must be 'DAC' or 'NORM'.")

        np_data = np.asarray(data_points)
        if np_data.ndim != 1 or np_data.size == 0:
             raise InstrumentParameterError("data_points must be a non-empty 1D sequence.")

        formatted_data: str
        scpi_suffix: str
        if data_type_upper == "DAC":
            if not np.issubdtype(np_data.dtype, np.integer):
                 self._log("Warning: DAC data provided is not integer type, attempting conversion.", level="warning")
                 try:
                      np_data = np_data.astype(np.int16) 
                 except ValueError as e:
                      raise ValueError("Cannot convert DAC data points to integers.") from e
            dac_min, dac_max = -32768, 32767
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise ValueError(f"DAC data points out of range [{dac_min}, {dac_max}]. Found min={np.min(np_data)}, max={np.max(np_data)}")
            formatted_data = ','.join(map(str, np_data))
            scpi_suffix = ":DAC" 
        else: # NORM
            if not np.issubdtype(np_data.dtype, np.floating):
                 self._log("Warning: Normalized data provided is not float type, attempting conversion.", level="warning")
                 try:
                      np_data = np_data.astype(float)
                 except ValueError as e:
                      raise ValueError("Cannot convert Normalized data points to floats.") from e
            norm_min, norm_max = -1.0, 1.0
            tolerance = 1e-9
            if np.any(np_data < norm_min - tolerance) or np.any(np_data > norm_max + tolerance):
                raise ValueError(f"Normalized data points out of range [{norm_min}, {norm_max}]. Found min={np.min(np_data):.4f}, max={np.max(np_data):.4f}")
            np_data = np.clip(np_data, norm_min, norm_max)
            formatted_data = ','.join(map(lambda x: f"{x:.8G}", np_data))
            scpi_suffix = "" 

        cmd = f"SOUR{ch}:DATA:ARBitrary{scpi_suffix} {arb_name},{formatted_data}"

        if len(cmd) > 10000: 
             self._log(f"Warning: Generated SCPI command length ({len(cmd)} chars) is large. "
                       f"Consider using binary transfer (use_binary=True) for waveform '{arb_name}'.", level="warning")

        try:
            self._send_command(cmd)
            self._log(f"Channel {ch}: Downloaded arbitrary waveform '{arb_name}' via CSV "
                      f"({np_data.size} points, type: {data_type_upper})")
            self._error_check() 
        except InstrumentCommunicationError as e:
             self._log(f"Error during CSV arb download. Command prefix: {cmd[:100]}...", level="error")
             code, msg = self.get_error()
             if code == -113: 
                 raise InstrumentCommunicationError(f"SCPI Syntax Error (Err -113 'Undefined header'). Command: {cmd[:100]}...", cause=e) from e
             elif code == 786: 
                 raise InstrumentCommunicationError(f"Arb Name Conflict (Err 786). '{arb_name}' already exists in volatile memory. Clear memory or use a different name.", cause=e) from e
             elif code == 781: 
                 raise InstrumentCommunicationError(f"Out of Memory (Err 781). Cannot store '{arb_name}'.", cause=e) from e
             elif code == -102: 
                  raise InstrumentCommunicationError(f"SCPI Syntax Error (Err -102). Possible command length exceeded for CSV data. Command: {cmd[:100]}...", cause=e) from e
             elif code != 0:
                 raise InstrumentCommunicationError(f"Arb download failed. Inst Err {code}: {msg}", cause=e) from e
             else: 
                  raise e

    def download_arbitrary_waveform_data_binary(self,
                                         channel: Union[int, str],
                                         arb_name: str,
                                         data_points: Union[List[int], List[float], np.ndarray],
                                         data_type: str = "DAC",
                                         is_dual_channel_data: bool = False,
                                         dual_data_format: Optional[str] = None) -> None:
        """
        Downloads arbitrary waveform data using IEEE 488.2 binary block format.
        ...
        """
        ch = self._validate_channel(channel)
        if not re.match(r"^[a-zA-Z0-9_]{1,12}$", arb_name):
            raise InstrumentParameterError(
                f"Arbitrary waveform name '{arb_name}' is invalid. Use 1-12 alphanumeric/underscore characters."
            )

        data_type_upper = data_type.upper().strip()
        if data_type_upper not in ["DAC", "NORM"]:
            raise InstrumentParameterError("Invalid data_type. Must be 'DAC' or 'NORM'.")

        np_data = np.asarray(data_points)
        if np_data.ndim != 1 or np_data.size == 0:
             raise InstrumentParameterError("data_points must be a non-empty 1D sequence.")

        num_points_total = np_data.size
        num_points_per_channel = num_points_total

        arb_cmd_node = "ARBitrary" 
        if is_dual_channel_data:
            if self.channel_count < 2:
                raise InstrumentParameterError("Dual channel data download requires a 2-channel instrument.")
            arb_cmd_node = "ARBitrary2" 
            if num_points_total % 2 != 0:
                raise InstrumentParameterError("Total data_points must be even for dual channel data.")
            num_points_per_channel = num_points_total // 2

            if dual_data_format:
                fmt_upper = dual_data_format.upper().strip()
                if fmt_upper not in ["AABB", "ABAB"]:
                    raise InstrumentParameterError("Invalid dual_data_format. Use 'AABB' or 'ABAB'.")
                self._send_command(f"SOUR{ch}:DATA:{arb_cmd_node}:FORMat {fmt_upper}")
                self._error_check()
                self._log(f"Channel {ch}: Dual arb data format set to {fmt_upper}")
            else:
                self._log(f"Channel {ch}: Using instrument's current dual arb data format setting.")


        binary_data: bytes
        scpi_suffix: str
        transfer_type: str = "Binary Block" # Default, might change if fallback used

        if data_type_upper == "DAC":
            scpi_suffix = ":DAC"
            if not np.issubdtype(np_data.dtype, np.integer):
                self._log("Warning: DAC data provided is not integer type, attempting conversion to int16.", level="warning")
                try:
                    np_data = np_data.astype(np.int16)
                except ValueError as e:
                    raise ValueError("Cannot convert DAC data points to int16.") from e
            dac_min, dac_max = -32768, 32767
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise ValueError(f"DAC data points out of range [{dac_min}, {dac_max}]. Found min={np.min(np_data)}, max={np.max(np_data)}")
            binary_data = np_data.astype('<h').tobytes()
        else: # NORM
            scpi_suffix = "" 
            if not np.issubdtype(np_data.dtype, np.floating):
                self._log("Warning: Normalized data provided is not float type, attempting conversion to float32.", level="warning")
                try:
                     np_data = np_data.astype(np.float32)
                except ValueError as e:
                     raise ValueError("Cannot convert Normalized data points to float32.") from e
            norm_min, norm_max = -1.0, 1.0
            tolerance = 1e-6 
            if np.any(np_data < norm_min - tolerance) or np.any(np_data > norm_max + tolerance):
                raise ValueError(f"Normalized data points out of range [{norm_min}, {norm_max}]. Found min={np.min(np_data):.4f}, max={np.max(np_data):.4f}")
            np_data = np.clip(np_data, norm_min, norm_max)
            binary_data = np_data.astype('<f').tobytes()

        cmd_prefix = f"SOUR{ch}:DATA:{arb_cmd_node}{scpi_suffix} {arb_name},"
        num_bytes = len(binary_data)
        
        try:
            # Assuming self.instrument is the PyVISA resource manager or similar
            if hasattr(self.instrument, 'write_binary_values') and callable(self.instrument.write_binary_values):
                 # PyVISA style: write_binary_values(command_prefix, values_iterable, datatype='h' or 'f', is_big_endian=False)
                 # We have already packed binary_data, so we might need a lower-level write or adjust.
                 # For now, let's assume _write_binary handles the full SCPI binary block construction.
                 self._write_binary(cmd_prefix, binary_data) # _write_binary should construct the #N<len> header
            else:
                 # Fallback to manual construction if _write_binary or equivalent is not available
                 self._log("Warning: _write_binary method not found or not callable, attempting manual binary block formatting.", level="warning")
                 num_bytes_str = str(num_bytes)
                 num_digits_in_len = len(num_bytes_str)
                 header = f"#{num_digits_in_len}{num_bytes_str}".encode('ascii')
                 full_command_bytes = cmd_prefix.encode('ascii') + header + binary_data
                 self.instrument.write_raw(full_command_bytes) # Assumes write_raw on the VISA resource
                 transfer_type = "Manual Binary Block"


            self._log(f"Channel {ch}: Downloaded arbitrary waveform '{arb_name}' via {transfer_type} "
                      f"({num_points_per_channel} pts/ch, {num_bytes} bytes total, type: {data_type_upper})")
            self._error_check() 
        except InstrumentCommunicationError as e:
             self._log(f"Error during {transfer_type} arb download for '{arb_name}'.", level="error")
             code, msg = self.get_error()
             if code == 786: 
                 raise InstrumentCommunicationError(f"Arb Name Conflict (Err 786). '{arb_name}' already exists in volatile memory. Clear memory or use a different name.", cause=e) from e
             elif code == 781: 
                 raise InstrumentCommunicationError(f"Out of Memory (Err 781). Cannot store '{arb_name}'.", cause=e) from e
             elif code == -113: 
                 raise InstrumentCommunicationError(f"SCPI Syntax Error (Err -113 'Undefined header'). Check command format.", cause=e) from e
             elif code != 0:
                 raise InstrumentCommunicationError(f"Arb download failed. Inst Err {code}: {msg}", cause=e) from e
             else: 
                  raise e
        except Exception as e:
             self._log(f"Unexpected error during binary arb download for '{arb_name}': {e}", level="error")
             raise InstrumentCommunicationError(f"Unexpected failure downloading arb '{arb_name}'", cause=e) from e


    def clear_volatile_arbitrary_waveforms(self, channel: Union[int, str]) -> None:
        """
        Clears all user-defined arbitrary waveforms from volatile memory.
        ...
        """
        ch = self._validate_channel(channel)
        self._send_command(f"SOUR{ch}:DATA:VOLatile:CLEar")
        self._log(f"Channel {ch}: Cleared volatile arbitrary waveform memory.")
        self._error_check()

    def get_free_volatile_arbitrary_memory(self, channel: Union[int, str]) -> int:
        """
        Queries the number of free data points available in volatile arb memory.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:DATA:VOLatile:FREE?").strip()
        try:
            free_points = int(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Unexpected non-integer response from DATA:VOL:FREE?: {response}")
        self._log(f"Channel {ch}: Free volatile arbitrary memory: {free_points} points")
        return free_points

    def get_pulse_duty_cycle(self, channel: Union[int, str]) -> float:
        """Queries the duty cycle percentage for the PULSE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:PULS:DCYCle?").strip()
        return float(response)

    def get_pulse_period(self, channel: Union[int, str]) -> float:
        """Queries the period in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:PULS:PERiod?").strip()
        return float(response)

    def get_pulse_width(self, channel: Union[int, str]) -> float:
        """Queries the pulse width in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:PULS:WIDTh?").strip()
        return float(response)

    def get_pulse_transition_leading(self, channel: Union[int, str]) -> float:
        """Queries the leading edge transition time in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:PULS:TRANsition:LEADing?").strip()
        return float(response)

    def get_pulse_transition_trailing(self, channel: Union[int, str]) -> float:
        """Queries the trailing edge transition time in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:PULS:TRANsition:TRAiling?").strip()
        return float(response)

    def get_pulse_transition_both(self, channel: Union[int, str]) -> float:
        """Queries the transition time applied to both edges for the PULSE function."""
        warnings.warn("Querying transition_both; returning leading edge time as proxy.", stacklevel=2)
        return self.get_pulse_transition_leading(channel)

    def get_pulse_hold_mode(self, channel: Union[int, str]) -> str:
        """Queries the hold mode (WIDTh or DCYCle) for the PULSE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:PULS:HOLD?").strip().upper()
        return response 

    def get_square_duty_cycle(self, channel: Union[int, str]) -> float:
        """Queries the duty cycle percentage for the SQUARE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:SQUare:DCYCle?").strip()
        return float(response)

    def get_square_period(self, channel: Union[int, str]) -> float:
        """Queries the period in seconds for the SQUARE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:SQUare:PERiod?").strip()
        return float(response)

    def get_ramp_symmetry(self, channel: Union[int, str]) -> float:
        """Queries the symmetry percentage for the RAMP/TRIANGLE function."""
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:FUNC:RAMP:SYMMetry?").strip()
        return float(response)

    def set_angle_unit(self, unit: str) -> None:
        """
        Specifies the angle units used for phase-related commands.
        ...
        """
        unit_upper = unit.upper().strip()
        valid_units_scpi = {"DEGREE", "RADIAN", "SECOND", "DEFAULT"}
        map_to_scpi: Dict[str, str] = {"DEG": "DEGREE", "RAD": "RADIAN", "SEC": "SECOND", "DEF": "DEFAULT"}

        scpi_unit: Optional[str] = map_to_scpi.get(unit_upper)
        if not scpi_unit and unit_upper in valid_units_scpi:
             scpi_unit = unit_upper 

        if not scpi_unit:
            raise InstrumentParameterError(
                f"Invalid angle unit '{unit}'. Use DEGree, RADian, SECond, or DEFault (or DEG, RAD, SEC, DEF)."
            )

        self._send_command(f"UNIT:ANGLe {scpi_unit}")
        self._log(f"Global angle unit set to {scpi_unit}")
        self._error_check()

    def get_angle_unit(self) -> str:
        """
        Queries the current global angle unit setting used for phase parameters.
        ...
        """
        response = self._query("UNIT:ANGLe?").strip().upper()
        if response not in ["DEG", "RAD", "SEC"]:
             self._log(f"Warning: Unexpected angle unit response '{response}'. Returning raw.", level="warning")
        self._log(f"Current global angle unit is {response}")
        return response

    def apply_waveform_settings(self,
                                channel: Union[int, str],
                                function_type: str,
                                frequency: Union[float, str] = LOAD_DEFAULT,
                                amplitude: Union[float, str] = LOAD_DEFAULT,
                                offset: Union[float, str] = LOAD_DEFAULT) -> None:
        """
        Configures a standard waveform function and its primary parameters in one command.
        ...
        """
        ch = self._validate_channel(channel)
        scpi_short_name = self._get_scpi_function_name(function_type)

        apply_suffix_map: Dict[str, str] = {
            FUNC_SIN: "SINusoid", FUNC_SQUARE: "SQUare", FUNC_RAMP: "RAMP",
            FUNC_PULSE: "PULSe", FUNC_PRBS: "PRBS", FUNC_NOISE: "NOISe",
            FUNC_ARB: "ARBitrary", FUNC_DC: "DC", FUNC_TRI: "TRIangle"
        }
        apply_suffix = apply_suffix_map.get(scpi_short_name)

        if not apply_suffix:
            raise InstrumentParameterError(
                f"Function '{function_type}' (mapped to {scpi_short_name}) is not supported by the APPLy command."
            )

        params: List[str] = []
        params.append(self._format_value_min_max_def(frequency))
        params.append(self._format_value_min_max_def(amplitude))
        params.append(self._format_value_min_max_def(offset))

        param_str = ",".join(params)
        cmd = f"SOUR{ch}:APPLy:{apply_suffix} {param_str}" 

        self._send_command(cmd)
        self._log(f"Channel {ch}: Applied {apply_suffix} with params: Freq/SR={frequency}, Ampl={amplitude}, Offs={offset}")
        self._error_check()

    def get_channel_configuration_summary(self, channel: Union[int, str]) -> str:
        """
        Queries a summary string of the channel's current configuration.
        ...
        """
        ch = self._validate_channel(channel)
        response = self._query(f"SOUR{ch}:APPLy?").strip()
        self._log(f"Channel {ch}: Configuration summary query (APPLy?) returned: {response}")
        return response

    def get_complete_config(self, channel: Union[int, str]) -> WaveformConfigResult:
        """
        Retrieves a detailed configuration snapshot of the specified channel.
        ...
        """
        ch_num = self._validate_channel(channel)
        self._log(f"Getting complete configuration snapshot for channel {ch_num}...")
        try:
            func_name = self.get_function(ch_num) 
            freq = self.get_frequency(ch_num) 
            ampl = self.get_amplitude(ch_num)
            offs = self.get_offset(ch_num)
            output_state = self.get_output_state(ch_num)
            load_impedance = self.get_output_load_impedance(ch_num)
            voltage_unit = self.get_voltage_unit(ch_num)

            phase: Optional[float] = None
            if func_name not in {FUNC_DC, FUNC_NOISE}:
                try:
                    phase = self.get_phase(ch_num)
                except InstrumentCommunicationError as e:
                    self._log(f"Note: Phase query failed for CH{ch_num} (likely normal for function {func_name}): {e}", level="info")
                    err_code, err_msg = self.get_error()
                    if err_code != 0:
                         self._log(f"Instrument error during phase query: {err_code} - {err_msg}", level="info")

            symmetry: Optional[float] = None
            duty_cycle: Optional[float] = None
            try:
                if func_name in {FUNC_RAMP, FUNC_TRI}:
                    symmetry = self.get_ramp_symmetry(ch_num)
                elif func_name == FUNC_SQUARE:
                    duty_cycle = self.get_square_duty_cycle(ch_num)
                elif func_name == FUNC_PULSE:
                    duty_cycle = self.get_pulse_duty_cycle(ch_num)
            except InstrumentCommunicationError as e:
                 self._log(f"Note: Query failed for function-specific parameter for CH{ch_num} function {func_name}: {e}", level="info")
                 err_code, err_msg = self.get_error()
                 if err_code != 0:
                      self._log(f"Instrument error during func-specific query: {err_code} - {err_msg}", level="info")


            return WaveformConfigResult(
                channel=ch_num,
                function=func_name,
                frequency=freq,
                amplitude=ampl,
                offset=offs,
                phase=phase,
                symmetry=symmetry,
                duty_cycle=duty_cycle,
                output_state=output_state,
                load_impedance=load_impedance,
                voltage_unit=voltage_unit
            )
        except Exception as e:
             self._log(f"Error retrieving complete config for channel {ch_num}: {e}", level="error")
             raise InstrumentCommunicationError(f"Failed getting complete config for CH{ch_num}. Cause: {e}", cause=e) from e

    def enable_modulation(self, channel: Union[int, str], mod_type: str, state: bool) -> None:
        """
        Enables or disables a specific modulation type for the channel.
        ...
        """
        ch = self._validate_channel(channel)
        mod_upper = mod_type.upper().strip()
        valid_mods = {"AM", "FM", "PM", "PWM", "FSK", "BPSK", "SUM"} 
        if mod_upper not in valid_mods:
            raise InstrumentParameterError(f"Invalid or unsupported modulation type '{mod_type}'. Allowed: {valid_mods}")

        cmd_state = STATE_ON if state else STATE_OFF
        self._send_command(f"SOUR{ch}:{mod_upper}:STATe {cmd_state}")
        self._log(f"Channel {ch}: {mod_upper} modulation state set to {cmd_state}")
        self._error_check()

    def set_am_depth(self, channel: Union[int, str], depth_percent: Union[float, str]) -> None:
        """
        Sets the Amplitude Modulation (AM) depth.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(depth_percent)

        if isinstance(depth_percent, (int, float)) and not (0 <= float(depth_percent) <= 120):
            self._log(f"Warning: AM depth {depth_percent}% is outside the typical 0-120 range.", level="warning")

        self._send_command(f"SOUR{ch}:AM:DEPTh {cmd_val}")
        self._log(f"Channel {ch}: AM depth set to {depth_percent}%")
        self._error_check()

    def set_am_source(self, channel: Union[int, str], source: str) -> None:
        """
        Selects the source for the Amplitude Modulation (AM) signal.
        ...
        """
        ch = self._validate_channel(channel)
        src_upper = source.upper().strip()

        cmd_src: str
        if src_upper in MOD_SOURCE_ABBREV_MAP:
             cmd_src = MOD_SOURCE_ABBREV_MAP[src_upper]
        elif src_upper in VALID_MOD_SOURCES:
             src_map_inv: Dict[str,str] = {v.upper(): v for v in VALID_MOD_SOURCES}
             cmd_src = src_map_inv.get(src_upper, src_upper) 
        else:
            raise InstrumentParameterError(f"Invalid AM source '{source}'. Use INTernal, CH1, or CH2.")

        if cmd_src == f"CH{ch}":
            raise InstrumentParameterError(f"Channel {ch} cannot be its own AM source.")
        if cmd_src == MOD_SOURCE_CH2 and self.channel_count < 2:
            raise InstrumentParameterError("CH2 source is invalid for a 1-channel instrument.")

        self._send_command(f"SOUR{ch}:AM:SOURce {cmd_src}")
        self._log(f"Channel {ch}: AM source set to {cmd_src}")
        self._error_check()

    def set_fm_deviation(self, channel: Union[int, str], deviation_hz: Union[float, str]) -> None:
        """
        Sets the peak frequency deviation for Frequency Modulation (FM).
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(deviation_hz)
        self._send_command(f"SOUR{ch}:FM:DEViation {cmd_val}")
        self._log(f"Channel {ch}: FM deviation set to {deviation_hz} Hz")
        self._error_check()

    def enable_sweep(self, channel: Union[int, str], state: bool) -> None:
        """
        Enables (True) or disables (False) frequency sweep mode for the channel.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        self._send_command(f"SOUR{ch}:SWEep:STATe {cmd_state}")
        self._log(f"Channel {ch}: Sweep state set to {cmd_state}")
        self._error_check()

    def set_sweep_time(self, channel: Union[int, str], sweep_time_sec: Union[float, str]) -> None:
        """
        Sets the time duration for one frequency sweep (from start to stop frequency).
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sweep_time_sec)
        self._send_command(f"SOUR{ch}:SWEep:TIME {cmd_val}")
        self._log(f"Channel {ch}: Sweep time set to {sweep_time_sec} s")
        self._error_check()

    def set_sweep_start_frequency(self, channel: Union[int, str], freq_hz: Union[float, str]) -> None:
        """
        Sets the starting frequency for the frequency sweep.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        self._send_command(f"SOUR{ch}:FREQuency:STARt {cmd_val}")
        self._log(f"Channel {ch}: Sweep start frequency set to {freq_hz} Hz")
        self._error_check()

    def set_sweep_stop_frequency(self, channel: Union[int, str], freq_hz: Union[float, str]) -> None:
        """
        Sets the ending frequency for the frequency sweep.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        self._send_command(f"SOUR{ch}:FREQuency:STOP {cmd_val}")
        self._log(f"Channel {ch}: Sweep stop frequency set to {freq_hz} Hz")
        self._error_check()

    def set_sweep_spacing(self, channel: Union[int, str], spacing: str) -> None:
        """
        Sets the sweep frequency spacing to LINear or LOGarithmic.
        ...
        """
        ch = self._validate_channel(channel)
        spacing_upper = spacing.upper().strip()

        cmd_spacing: str
        if spacing_upper in SWEEP_ABBREV_MAP:
            cmd_spacing = SWEEP_ABBREV_MAP[spacing_upper]
        elif spacing_upper == SWEEP_LINEAR.upper():
             cmd_spacing = SWEEP_LINEAR
        elif spacing_upper == SWEEP_LOGARITHMIC.upper():
             cmd_spacing = SWEEP_LOGARITHMIC
        else:
            raise InstrumentParameterError(f"Invalid sweep spacing '{spacing}'. Use LINear or LOGarithmic.")

        self._send_command(f"SOUR{ch}:SWEep:SPACing {cmd_spacing}")
        self._log(f"Channel {ch}: Sweep spacing set to {cmd_spacing}")
        self._error_check()

    def enable_burst(self, channel: Union[int, str], state: bool) -> None:
        """
        Enables (True) or disables (False) burst mode for the channel.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        self._send_command(f"SOUR{ch}:BURSt:STATe {cmd_state}")
        self._log(f"Channel {ch}: Burst state set to {cmd_state}")
        self._error_check()

    def set_burst_mode(self, channel: Union[int, str], mode: str) -> None:
        """
        Sets the burst operation mode.
        ...
        """
        ch = self._validate_channel(channel)
        mode_upper = mode.upper().strip()

        cmd_mode: str
        if mode_upper in BURST_ABBREV_MAP:
            cmd_mode = BURST_ABBREV_MAP[mode_upper]
        elif mode_upper == BURST_TRIGGERED.upper():
             cmd_mode = BURST_TRIGGERED
        elif mode_upper == BURST_GATED.upper():
             cmd_mode = BURST_GATED
        else:
            raise InstrumentParameterError(f"Invalid burst mode '{mode}'. Use TRIGgered or GATed.")

        self._send_command(f"SOUR{ch}:BURSt:MODE {cmd_mode}")
        self._log(f"Channel {ch}: Burst mode set to {cmd_mode}")
        self._error_check()

    def set_burst_cycles(self, channel: Union[int, str], n_cycles: Union[int, str]) -> None:
        """
        Sets the number of waveform cycles to output in each burst.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val: str
        log_val: Union[int, str] = n_cycles 

        if isinstance(n_cycles, str):
            nc_upper = n_cycles.upper().strip()
            if nc_upper in {"MIN", "MINIMUM"}:
                 cmd_val = LOAD_MINIMUM
            elif nc_upper in {"MAX", "MAXIMUM"}:
                 cmd_val = LOAD_MAXIMUM
            elif nc_upper in {"INF", "INFINITY"}:
                 cmd_val = "INFinity"
            else:
                 raise InstrumentParameterError(f"Invalid string '{n_cycles}' for burst cycles. Use INFinity, MINimum, or MAXimum.")
        elif isinstance(n_cycles, int):
             if n_cycles < 1:
                 raise InstrumentParameterError(f"Burst cycle count must be positive integer or INF/MIN/MAX. Got {n_cycles}.")
             inst_max_cycles = 100_000_000
             if n_cycles > inst_max_cycles:
                 self._log(f"Warning: Burst cycle count {n_cycles} exceeds typical instrument max ({inst_max_cycles}).", level="warning")
             cmd_val = str(n_cycles)
        else:
             raise InstrumentParameterError(f"Invalid type '{type(n_cycles)}' for burst cycles. Expected positive integer or string (INF/MIN/MAX).")

        self._send_command(f"SOUR{ch}:BURSt:NCYCles {cmd_val}")
        self._log(f"Channel {ch}: Burst cycles set to {log_val}")
        self._error_check() 

    def set_burst_period(self, channel: Union[int, str], period_sec: Union[float, str]) -> None:
        """
        Sets the time interval between the start of consecutive bursts.
        ...
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(period_sec)
        self._send_command(f"SOUR{ch}:BURSt:INTernal:PERiod {cmd_val}")
        self._log(f"Channel {ch}: Internal burst period set to {period_sec} s")
        self._error_check() 

    def set_trigger_source(self, channel: Union[int, str], source: str) -> None:
        """
        Selects the source that initiates a trigger event for Sweep, Burst, or List modes.
        ...
        """
        ch = self._validate_channel(channel)
        src_upper = source.upper().strip()

        cmd_src: str
        if src_upper in SOURCE_ABBREV_MAP:
            cmd_src = SOURCE_ABBREV_MAP[src_upper]
        elif src_upper in VALID_TRIGGER_SOURCES:
            cmd_src = next((s for s in VALID_TRIGGER_SOURCES if src_upper == s.upper()), src_upper)
        elif src_upper == SOURCE_BUS.upper(): 
             cmd_src = SOURCE_BUS
        else:
            raise InstrumentParameterError(f"Invalid trigger source '{source}'. Use IMMediate, EXTernal, TIMer, or BUS.")

        self._send_command(f"TRIGger{ch}:SOURce {cmd_src}")
        self._log(f"Channel {ch}: Trigger source set to {cmd_src}")
        self._error_check()

    def set_trigger_slope(self, channel: Union[int, str], slope: str) -> None:
        """
        Selects the active edge for the EXTernal trigger input signal.
        ...
        """
        ch = self._validate_channel(channel)
        slope_upper = slope.upper().strip()

        cmd_slope: str
        if slope_upper in SLOPE_ABBREV_MAP:
            cmd_slope = SLOPE_ABBREV_MAP[slope_upper]
        elif slope_upper == SLOPE_POSITIVE.upper():
            cmd_slope = SLOPE_POSITIVE
        elif slope_upper == SLOPE_NEGATIVE.upper():
             cmd_slope = SLOPE_NEGATIVE
        else:
            raise InstrumentParameterError(f"Invalid trigger slope '{slope}'. Use POSitive or NEGative.")

        self._send_command(f"TRIGger{ch}:SLOPe {cmd_slope}")
        self._log(f"Channel {ch}: Trigger slope set to {cmd_slope}")
        self._error_check()

    def trigger_now(self, channel: Optional[Union[int, str]] = None) -> None:
        """
        Forces an immediate trigger event via software command.
        ...
        """
        if channel is not None:
            ch = self._validate_channel(channel)
            self._send_command(f"TRIGger{ch}")
            self._log(f"Sent immediate channel-specific trigger command TRIGger{ch}")
        else:
             self._send_command("*TRG")
             self._log("Sent general bus trigger command *TRG")

        self._error_check()

    def list_directory(self, path: str = "") -> FileSystemInfo:
        """
        Lists directory contents (files/folders) on internal or USB memory.
        ...
        """
        path_scpi = f' "{path}"' if path else "" 

        cmd = f"MMEMory:CATalog:ALL?{path_scpi}"
        response = self._query(cmd).strip()

        try:
            parts = response.split(',', 2)
            if len(parts) < 2:
                 raise InstrumentCommunicationError(f"Unexpected response format from MMEM:CAT?: {response}")

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
                          self._log(f"Warning: Could not parse size '{size_str}' for file '{name}'. Skipping.", level="warning")
                          continue
                     info.files.append({'name': name, 'type': file_type.upper(), 'size': size})

            self._log(f"Directory listing for '{path or 'current dir'}': Used={info.bytes_used}, "
                      f"Free={info.bytes_free}, Items={len(info.files)}")
            return info

        except (ValueError, IndexError) as e:
            raise InstrumentCommunicationError(f"Failed to parse MMEM:CAT? response: '{response}'. Error: {e}", cause=e) from e


    def delete_file_or_folder(self, path: str) -> None:
        """
        Deletes a specified file or an *empty* folder from instrument memory.
        ...
        """
        if not path:
             raise InstrumentParameterError("Path cannot be empty for deletion.")

        path_scpi = f'"{path}"'
        cmd = f"MMEMory:DELete {path_scpi}"
        action_logged = "file/folder" 

        try:
            self._send_command(cmd)
            self._log(f"Attempted to delete {action_logged}: '{path}' using MMEM:DELete")
            self._error_check() 
        except InstrumentCommunicationError as e:
             code, msg = self.get_error()
             if code != 0: 
                 if "Directory not empty" in msg or "folder" in msg.lower(): 
                     raise InstrumentCommunicationError(f"Failed to delete '{path}'. It might be a non-empty folder. "
                                                      f"Use MMEM:RDIR for empty folders. Inst Err {code}: {msg}", cause=e) from e
                 else:
                      raise InstrumentCommunicationError(f"Failed to delete '{path}'. Inst Err {code}: {msg}", cause=e) from e
             else: 
                 raise e
