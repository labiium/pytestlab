# -*- coding: utf-8 -*-
"""
Module providing a high-level interface for Keysight EDU33210 Series
Trueform Arbitrary Waveform Generators.
"""

import re
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

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
WAVEFORM_PARAM_COMMANDS: Dict[str, Dict[str, callable]] = {
    FUNC_PULSE: {
        "duty_cycle": lambda ch, v: f"SOUR{ch}:FUNC:PULS:DCYCle {v}",
        "period": lambda ch, v: f"SOUR{ch}:FUNC:PULS:PERiod {v}",
        "width": lambda ch, v: f"SOUR{ch}:FUNC:PULS:WIDTh {v}",
        "transition_both": lambda ch, v: f"SOUR{ch}:FUNC:PULS:TRANsition:BOTH {v}",
        "transition_leading": lambda ch, v: f"SOUR{ch}:FUNC:PULS:TRANsition:LEADing {v}",
        "transition_trailing": lambda ch, v: f"SOUR{ch}:FUNC:PULS:TRANsition:TRAiling {v}",
        "hold_mode": lambda ch, v: f"SOUR{ch}:FUNC:PULS:HOLD {v.upper()}", # Expects WIDTh or DCYCle
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
        "data_type": lambda ch, v: f"SOUR{ch}:FUNC:PRBS:DATA {v.upper()}", # Expects PN7, PN9, etc.
        "transition_both": lambda ch, v: f"SOUR{ch}:FUNC:PRBS:TRANsition:BOTH {v}",
    },
    FUNC_NOISE: {
        "bandwidth": lambda ch, v: f"SOUR{ch}:FUNC:NOISe:BANDwidth {v}",
    },
    FUNC_ARB: {
        "sample_rate": lambda ch, v: f"SOUR{ch}:FUNC:ARB:SRATe {v}",
        "filter": lambda ch, v: f"SOUR{ch}:FUNC:ARB:FILTer {v.upper()}", # Expects NORMal, STEP, OFF
        "advance_mode": lambda ch, v: f"SOUR{ch}:FUNC:ARB:ADVance {v.upper()}", # Expects TRIGger, SRATe
        "frequency": lambda ch, v: f"SOUR{ch}:FUNC:ARB:FREQ {v}",
        "period": lambda ch, v: f"SOUR{ch}:FUNC:ARB:PER {v}",
        "ptpeak_voltage": lambda ch, v: f"SOUR{ch}:FUNC:ARB:PTP {v}", # Note: This is FUNC:ARB:PTPeak in manual? PTP exists p.157
    },
    FUNC_DC: {}
}


class WaveformGenerator(Instrument):
    """
    Provides a high-level Python interface for controlling Keysight EDU33210
    Series Trueform Arbitrary Waveform Generators via SCPI commands.

    This class aims for comprehensive coverage of the instrument's programming manual,
    encompassing waveform generation (standard and arbitrary), output configuration
    (impedance, polarity, limits), modulation (AM, FM, etc.), sweep, burst modes,
    memory management (volatile and file system), triggering, synchronization,
    and system settings.

    It relies on a `WaveformGeneratorConfig` object, typically loaded via `AutoInstrument`
    or a configuration manager, which provides instrument-specific details such as
    channel count, parameter ranges, supported waveforms, and SCPI command mappings.

    The class handles SCPI command formatting, validation of channel numbers and
    common parameters, and basic error checking after command execution. For complex
    operations like arbitrary waveform downloads, both simple CSV and more robust
    binary block transfer methods are available.

    Typical Usage:
    ```python
    from pytestlab.instruments import AutoInstrument
    import numpy as np

    # Assuming AutoInstrument finds config for "keysight/EDU33212A"
    # and the instrument is connected at the specified address.
    try:
        wg = AutoInstrument.from_config("keysight/EDU33212A", debug_mode=True)

        # Basic setup
        wg.reset() 
        wg.clear_status()
        print(f"Connected to: {wg.id()}")
        print(f"Instrument has {wg.channel_count} channels.")

        # Configure Channel 1: Sine wave
        wg.set_function(1, "SINE", frequency=10000, amplitude=2.0)
        wg.set_offset(1, 0.1)
        wg.set_output_load_impedance(1, 50)
        wg.set_output_state(1, True)
        print("Channel 1 configured for 10kHz Sine, 2Vpp, 0.1V offset, output ON.")

        # Configure Channel 2 (if available): Arbitrary waveform
        if wg.channel_count >= 2:
            arb_data = np.linspace(-1.0, 1.0, 256) # Normalized data
            arb_name = "MyRampArb"
            wg.clear_volatile_arbitrary_waveforms(2)
            # Use binary transfer for better performance/reliability
            wg.download_arbitrary_waveform_data_binary(2, arb_name, arb_data, data_type="NORM")
            wg.select_arbitrary_waveform(2, arb_name)
            wg.set_function(2, "ARB", sample_rate=500000) # Set function and sample rate
            wg.set_amplitude(2, 1.5) # 1.5 Vpp
            wg.set_output_state(2, True)
            print("Channel 2 configured for downloaded Arbitrary Ramp, output ON.")

        # Wait and then disable outputs
        time.sleep(2)
        wg.set_output_state(1, False)
        if wg.channel_count >= 2:
            wg.set_output_state(2, False)
        print("Outputs disabled.")

        # Check for errors
        errors = wg.get_all_errors()
        if errors:
            print(f"Instrument errors occurred: {errors}")
        else:
            print("No instrument errors detected.")

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        if 'wg' in locals() and wg.is_connected:
            wg.close()
            print("Instrument connection closed.")
    ```
    """
    def __init__(self, config: WaveformGeneratorConfig, debug_mode: bool = False):
        """
        Initializes the WaveformGenerator instance.

        Connects to the instrument defined by the configuration using the base
        Instrument class, verifies the configuration type, and determines basic
        properties like channel count from the configuration.

        Args:
            config: Configuration object containing device-specific details
                    such as manufacturer, model, channel capabilities,
                    waveform types, and parameter limits. Must be an instance
                    of `WaveformGeneratorConfig`.
            debug_mode: If True, enables verbose logging of SCPI commands
                        and responses via the base Instrument class.
                        Defaults to False.

        Raises:
            InstrumentConfigurationError: If the provided `config` is not a valid
                                          `WaveformGeneratorConfig` instance or if
                                          channel count cannot be determined.
            InstrumentConnectionError: If communication with the instrument fails
                                       during initialization (e.g., cannot connect
                                       or clear initial errors).
        """
        if not isinstance(config, WaveformGeneratorConfig):
            raise InstrumentConfigurationError("WaveformGenerator requires a WaveformGeneratorConfig object.")
        super().__init__(config=config, debug_mode=debug_mode)

        # Store typed config for easier access
        self.config: WaveformGeneratorConfig = config

        # Determine and store channel count from config
        try:
            # Assumes config.channels is accessible and has a 'channels' attribute (dict or list)
            # or a count attribute directly. Adapt as needed based on actual config structure.
            if hasattr(self.config.channels, 'channels') and isinstance(self.config.channels.channels, dict):
                self._channel_count = len(self.config.channels.channels)
            elif hasattr(self.config.channels, 'count'):
                 self._channel_count = self.config.channels.count
            else:
                 # Fallback or attempt another way if structure differs
                 raise InstrumentConfigurationError("Cannot determine channel count from config.channels structure.")

            if not isinstance(self._channel_count, int) or self._channel_count <= 0:
                 raise InstrumentConfigurationError(f"Invalid channel count determined: {self._channel_count}")

            self._log(f"Detected {self._channel_count} channels from configuration.")

        except (AttributeError, InstrumentConfigurationError) as e:
            self._log(f"Error determining channel count from config: {e}. Please check config structure.", level="error")
            # Decide whether to raise or default. Raising is safer.
            raise InstrumentConfigurationError("Could not determine channel count from configuration.", cause=e) from e
        except Exception as e:
            # Catch unexpected errors during config access
            self._log(f"Unexpected error accessing channel count from config: {e}", level="error")
            raise InstrumentConfigurationError("Unexpected error accessing channel count.", cause=e) from e

    @property
    def channel_count(self) -> int:
        """
        Returns the number of output channels supported by this instrument.

        This value is determined from the `WaveformGeneratorConfig` object provided
        during initialization.

        Returns:
            The number of channels (e.g., 1 or 2).
        """
        return self._channel_count


    @classmethod
    def from_config(cls, config: WaveformGeneratorConfig, debug_mode=False):
        
        return cls(config=WaveformGeneratorConfig(**config), debug_mode=debug_mode)
    # --- Helper Methods ---
    def _validate_channel(self, channel: Union[int, str]) -> int:
        """
        Validates the provided channel identifier and returns the integer channel number.

        Accepts integer channel numbers (e.g., 1, 2) or string identifiers
        (e.g., "1", "CH1", "CH2", "CHANNEL1"). It uses the validation logic
        defined within the instrument's configuration (`config.channels.validate`).

        Args:
            channel: The channel identifier to validate.

        Returns:
            The validated integer channel number (e.g., 1 or 2).

        Raises:
            InstrumentParameterError: If the channel identifier is invalid (not an integer,
                                      not convertible to an integer, or out of the
                                      instrument's supported channel range as defined
                                      in the configuration).
            ValueError: If a string format like "CHx" is provided but the number 'x'
                        cannot be parsed as an integer.
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
                         # Should not happen if regex matches \d+ but handle defensively
                         raise ValueError(f"Could not parse channel number from '{channel}'.") from e
                else:
                     raise InstrumentParameterError(f"Invalid channel string format: '{channel}'. Use integer, 'CHx', or 'CHANNELx'.")
            else:
                try:
                    ch_num = int(channel) # Allow direct numeric strings like "1"
                except ValueError:
                    raise InstrumentParameterError(f"Invalid channel string format: '{channel}'. Use integer, 'CHx', or 'CHANNELx'.")
        elif isinstance(channel, int):
             ch_num = channel
        else:
            raise InstrumentParameterError(f"Invalid channel type: {type(channel)}. Expected int or str.")

        # Use the validate method from the config's ChannelsConfig
        # This will raise InstrumentParameterError if ch_num is out of configured range (e.g., 3 for a 2ch device)
        try:
            return self.config.channels.validate(ch_num)
        except InstrumentParameterError:
             raise # Re-raise the specific error from config validation
        except Exception as e:
             # Catch unexpected errors during config validation
             self._log(f"Unexpected error during channel validation for {ch_num}: {e}", level="error")
             raise InstrumentConfigurationError(f"Channel validation failed unexpectedly for {ch_num}.", cause=e) from e

    def _get_scpi_function_name(self, user_function_name: str) -> str:
        """
        Translates a user-friendly function name or SCPI name to the canonical short SCPI name.

        Handles common variations (e.g., "SINE", "SINUSOID", "SIN") and maps them to the
        short form (e.g., "SIN") required for internal logic (like `WAVEFORM_PARAM_COMMANDS`).
        It checks against the `waveforms.built_in.options` defined in the instrument's
        configuration.

        Args:
            user_function_name: The function name provided by the user (case-insensitive).

        Returns:
            The short SCPI function name (e.g., "SIN", "SQU", "PULS", "ARB").

        Raises:
            InstrumentParameterError: If the function name cannot be mapped to a supported
                                      SCPI function based on the configuration.
            InstrumentConfigurationError: If the configuration's built-in waveform structure
                                          is missing or malformed.
        """
        if not hasattr(self.config.waveforms, 'built_in') or \
           not hasattr(self.config.waveforms.built_in, 'options'):
            raise InstrumentConfigurationError("Configuration error: Missing 'waveforms.built_in.options'.")

        options = self.config.waveforms.built_in.options
        lookup_key = user_function_name.strip().upper()

        # Mapping from common/long names/SCPI short names to the canonical short SCPI name
        # This map provides flexibility beyond just what's in the config file.
        name_to_short_scpi = {
            "SINE": FUNC_SIN, "SINUSOID": FUNC_SIN, FUNC_SIN: FUNC_SIN,
            "SQUARE": FUNC_SQUARE, FUNC_SQUARE: FUNC_SQUARE,
            "RAMP": FUNC_RAMP, FUNC_RAMP: FUNC_RAMP,
            "PULSE": FUNC_PULSE, FUNC_PULSE: FUNC_PULSE,
            "PRBS": FUNC_PRBS, FUNC_PRBS: FUNC_PRBS,
            "NOISE": FUNC_NOISE, FUNC_NOISE: FUNC_NOISE,
            "ARBITRARY": FUNC_ARB, "ARB": FUNC_ARB, FUNC_ARB: FUNC_ARB, # Explicitly add ARB
            "DC": FUNC_DC, FUNC_DC: FUNC_DC,
            "TRIANGLE": FUNC_TRI, "TRI": FUNC_TRI, FUNC_TRI: FUNC_TRI, # Added TRIANGLE/TRI
        }

        # 1. Direct lookup using common variations
        if lookup_key in name_to_short_scpi:
            short_name = name_to_short_scpi[lookup_key]
            # 2. Check if the derived short name is actually supported by the config
            supported_short_names = set()
            if isinstance(options, dict):
                # Config format: {"SINE": "SIN", "SQUARE": "SQU"}
                supported_short_names = {v.upper() for v in options.values()}
            elif isinstance(options, list):
                # Config format: ["SINusoid", "SQUare", "ARB"] -> map these back to short names
                for opt in options:
                    opt_upper = str(opt).upper()
                    if opt_upper in name_to_short_scpi:
                        supported_short_names.add(name_to_short_scpi[opt_upper])
                    else:
                        # Handle cases where config list might contain unexpected names
                        self._log(f"Warning: Config waveform option '{opt}' not recognized in internal mapping.", level="warning")

            if short_name in supported_short_names:
                return short_name # Found a valid mapping supported by config
            else:
                 # If the direct lookup gave a short name not in config, maybe user entered a name *exactly* from config list?
                 pass # Fall through to check against config options directly


        # 3. Check directly against config options (handling list or dict)
        if isinstance(options, dict):
            # Check if lookup_key matches a user-facing key OR a SCPI value in the config dict
            if lookup_key in options: # Matches a key like "SINE"
                scpi_val = options[lookup_key]
                return name_to_short_scpi.get(scpi_val.upper(), scpi_val) # Map value ("SIN") back to canonical short form
            valid_scpi_values_in_cfg = {v.upper() for v in options.values()}
            if lookup_key in valid_scpi_values_in_cfg: # Matches a value like "SIN"
                return lookup_key # User entered the short SCPI name directly
            raise InstrumentParameterError(
                f"Unknown waveform type '{user_function_name}'. "
                f"Supported user types: {list(options.keys())} or SCPI values: {list(options.values())}"
            )
        elif isinstance(options, list):
            # Check if lookup_key matches any entry in the list (case-insensitive)
            options_upper = [str(opt).upper() for opt in options]
            if lookup_key in options_upper:
                original_index = options_upper.index(lookup_key)
                config_name = options[original_index] # e.g., "SINusoid" or "SIN"
                # Map the name found in the config back to the canonical short SCPI name
                return name_to_short_scpi.get(config_name.upper(), config_name) # Fallback to config_name if mapping fails
            raise InstrumentParameterError(
                f"Unknown waveform type '{user_function_name}'. "
                f"Supported types from config list: {options}"
            )
        else:
            raise InstrumentConfigurationError(f"Unexpected format for built_in waveform options: {type(options)}")


    def _format_value_min_max_def(self, value: Union[float, int, str]) -> str:
        """
        Formats numeric values or special string keywords for SCPI commands.

        Handles standard numeric types (float, int) and the special SCPI keywords
        "MINimum", "MAXimum", "DEFault", and "INFinity" (and their common abbreviations).
        Numeric values are formatted using scientific notation ('G') for compactness
        and precision.

        Args:
            value: The value or keyword to format. Case-insensitive for keywords.

        Returns:
            The formatted SCPI parameter string (e.g., "5.0E+3", "MINimum", "INFinity").

        Raises:
            InstrumentParameterError: If the input value/string is invalid (not numeric,
                                      not a recognized keyword, or wrong type).
        """
        if isinstance(value, str):
            val_upper = value.upper().strip()
            # Use canonical SCPI keywords defined as constants
            special_strings_map = {
                "MIN": LOAD_MINIMUM, "MINIMUM": LOAD_MINIMUM,
                "MAX": LOAD_MAXIMUM, "MAXIMUM": LOAD_MAXIMUM,
                "DEF": LOAD_DEFAULT, "DEFAULT": LOAD_DEFAULT,
                "INF": LOAD_INFINITY, "INFINITY": LOAD_INFINITY
            }
            if val_upper in special_strings_map:
                return special_strings_map[val_upper]
            else:
                # If not a special string, attempt to parse as a number
                try:
                    num_val = float(value)
                    # Format using 'G' for general format (either fixed or scientific)
                    # with sufficient precision.
                    return f"{num_val:.12G}"
                except ValueError:
                    raise InstrumentParameterError(
                        f"Invalid parameter string '{value}'. Expected a number or "
                        f"one of MIN/MAX/DEF/INF (case-insensitive)."
                    )
        elif isinstance(value, (int, float)):
            # Format numbers consistently
            return f"{float(value):.12G}"
        else:
            raise InstrumentParameterError(f"Invalid parameter type: {type(value)}. Expected number or string.")

    # --- Waveform Configuration ---

    def set_function(self, channel: Union[int, str], function_type: str, **kwargs: Any):
        """
        Sets the primary waveform function and associated parameters for a channel.

        This command selects the basic waveform shape (e.g., Sine, Square, Pulse, Arbitrary)
        and allows configuration of function-specific parameters like duty cycle, symmetry,
        period, or sample rate using keyword arguments.

        Example:
        ```python
        # Set Channel 1 to a 1 kHz Pulse with 25% duty cycle and 10 ns transition time
        wg.set_function(1, "PULSE", frequency=1000, duty_cycle=25, transition_both=10E-9)

        # Set Channel 2 to the selected Arbitrary waveform with a 500 kSa/s sample rate
        wg.select_arbitrary_waveform(2, "MyArb")
        wg.set_function(2, "ARB", sample_rate=500000)
        ```

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            function_type: The desired waveform function type (e.g., "SINE", "PULSE",
                           "RAMP", "ARB"). Case-insensitive. Must map to a function
                           supported by the instrument configuration.
            **kwargs: Optional keyword arguments for function-specific parameters.
                      Supported keywords depend on the `function_type` and are defined
                      internally (see `WAVEFORM_PARAM_COMMANDS`). Common examples:
                      - For PULSE: `duty_cycle`, `period`, `width`, `transition_leading`,
                        `transition_trailing`, `transition_both`, `hold_mode`.
                      - For SQUARE: `duty_cycle`, `period`.
                      - For RAMP/TRIANGLE: `symmetry`.
                      - For PRBS: `bit_rate`, `data_type`, `transition_both`.
                      - For NOISE: `bandwidth`.
                      - For ARB: `sample_rate`, `filter`, `advance_mode`, `frequency`,
                        `period`, `ptpeak_voltage`.
                      Values can often be numeric or MIN/MAX/DEF strings where applicable.
                      Standard parameters like `frequency`, `amplitude`, `offset` should
                      generally be set using their dedicated methods (`set_frequency`, etc.)
                      *unless* they are specific to the ARB function context (like ARB frequency).

        Raises:
            InstrumentParameterError: If `function_type` is unrecognized, a keyword argument
                                      is invalid for the selected function, or a parameter
                                      value is invalid (e.g., wrong type, out of range,
                                      invalid string).
            InstrumentCommunicationError: If sending SCPI commands to the instrument fails.
            InstrumentConfigurationError: If the internal configuration is malformed or
                                          parameter definitions are missing.
        """
        ch = self._validate_channel(channel)
        scpi_func_short = self._get_scpi_function_name(function_type) # e.g., "SIN", "PULS", "ARB"

        # --- Handle standard parameters (Freq, Ampl, Offset) if provided ---
        # These are usually set via dedicated methods, but handle them here if passed,
        # especially for ARB which has its own frequency/period commands.
        standard_params_set = {}
        if 'frequency' in kwargs and scpi_func_short != FUNC_ARB:
            self.set_frequency(ch, kwargs.pop('frequency'))
            standard_params_set['frequency'] = True
        if 'amplitude' in kwargs:
             self.set_amplitude(ch, kwargs.pop('amplitude'))
             standard_params_set['amplitude'] = True
        if 'offset' in kwargs:
             self.set_offset(ch, kwargs.pop('offset'))
             standard_params_set['offset'] = True

        # --- Set the main function type ---
        # SCPI: SOUR#:FUNC <SCPI_FUNC_NAME> (Manual p.152)
        # Note: The manual uses the longer SCPI names here (e.g., SINusoid) but
        # the short names (e.g., SIN) are generally accepted by Keysight instruments.
        # Let's stick to the short names derived by _get_scpi_function_name for consistency.
        self._send_command(f"SOUR{ch}:FUNC {scpi_func_short}")
        self._log(f"Channel {ch}: Function set to {function_type} (SCPI: {scpi_func_short})")
        # Check for errors immediately after setting the function, before applying params
        self._error_check()

        # --- Process function-specific keyword arguments ---
        if kwargs:
            param_cmds_for_func = WAVEFORM_PARAM_COMMANDS.get(scpi_func_short)
            if not param_cmds_for_func:
                # If kwargs were provided but no specific params are defined for this function, warn.
                self._log(f"Warning: No specific parameters defined for SCPI function '{scpi_func_short}'. "
                          f"Ignoring remaining kwargs: {kwargs}", level="warning")
                # Re-check if any standard params were handled earlier and raise if other kwargs remain
                if any(k not in standard_params_set for k in kwargs):
                     # This should ideally not happen if the param_cmds dict is complete
                     raise InstrumentParameterError(f"Unknown parameters {kwargs.keys()} passed for function {function_type}.")
                return # Exit if only standard params were passed or no specific params exist

            # Apply each specified keyword parameter
            for param_name, value in kwargs.items():
                if param_name in param_cmds_for_func:
                    try:
                        # Basic validation for common percentage parameters
                        if param_name in ["duty_cycle", "symmetry"] and isinstance(value, (int, float)):
                            if not (0 <= float(value) <= 100):
                                self._log(f"Warning: Parameter '{param_name}' value {value}% is outside the "
                                          f"typical 0-100 range. Instrument validation will apply.", level="warning")
                        # Add more basic range checks here if helpful (though instrument does final validation)

                        # Format numeric values or MIN/MAX/DEF/INF strings appropriately
                        formatted_value = self._format_value_min_max_def(value)

                        # Get the lambda function to generate the SCPI command string
                        cmd_lambda = param_cmds_for_func[param_name]
                        # Generate the specific SCPI command
                        cmd = cmd_lambda(ch, formatted_value)

                        self._send_command(cmd)
                        self._log(f"Channel {ch}: Parameter '{param_name}' set to {value}")
                        # Check for errors after *each* parameter set for easier debugging
                        self._error_check()
                    except InstrumentParameterError as ipe:
                        # Re-raise formatting errors with more context
                        raise InstrumentParameterError(
                            f"Invalid value '{value}' provided for parameter '{param_name}' "
                            f"of function '{function_type}'. Cause: {ipe}"
                        ) from ipe
                    except InstrumentCommunicationError:
                         raise # Propagate communication errors directly
                    except Exception as e:
                        # Catch unexpected errors during command generation or sending
                        self._log(f"Error setting parameter '{param_name}' for function '{scpi_func_short}': {e}", level="error")
                        raise InstrumentCommunicationError(f"Failed to set parameter {param_name}", cause=e) from e
                else:
                    # Raise error if the keyword argument is unknown for this function
                    raise InstrumentParameterError(
                        f"Parameter '{param_name}' is not supported for function '{function_type}' ({scpi_func_short}). "
                        f"Supported specific parameters: {list(param_cmds_for_func.keys())}"
                    )

    def get_function(self, channel: Union[int, str]) -> str:
        """
        Queries the instrument for the currently selected waveform function.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The short SCPI name of the current function (e.g., "SIN", "SQU", "PULS", "ARB").

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC? (Manual p.152) - Returns short form (SIN, SQU, etc.)
        scpi_func = self._query(f"SOUR{ch}:FUNC?").strip()
        self._log(f"Channel {ch}: Current function is {scpi_func}")
        return scpi_func

    def set_frequency(self, channel: Union[int, str], frequency: Union[float, str]):
        """
        Sets the output frequency for the selected waveform function.

        Note: For Arbitrary waveforms (ARB), use `set_arbitrary_waveform_sample_rate`
              or pass `sample_rate` to `set_function`. This method sets the main
              frequency register, which applies to standard functions (SIN, SQU, etc.).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            frequency: The desired frequency in Hertz (Hz). Can also be the string
                       "MINimum", "MAXimum", or "DEFault". The instrument validates
                       the value against the limits for the currently active function.

        Raises:
            InstrumentParameterError: If the `frequency` string is invalid or the value type
                                      is incorrect.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value out of
                                          range for the current function).
        """
        ch = self._validate_channel(channel)
        freq_cmd_val = self._format_value_min_max_def(frequency)

        # Perform a basic configuration range check if available and numeric value provided
        # The instrument performs the definitive function-specific range check.
        if isinstance(frequency, (int, float)) and hasattr(self.config.channels[ch], 'frequency'):
             if hasattr(self.config.channels[ch].frequency, 'in_range'):
                 try:
                     self.config.channels[ch].frequency.in_range(float(frequency))
                 except InstrumentParameterError as e:
                     # Log a warning if outside basic config range, but let instrument handle final check
                     self._log(f"Warning: Frequency {frequency} Hz is outside the basic range defined "
                               f"in the configuration. Instrument will perform final validation. Config error: {e}",
                               level="warning")

        # SCPI: SOUR#:FREQ (Manual p.142)
        self._send_command(f"SOUR{ch}:FREQ {freq_cmd_val}")
        self._log(f"Channel {ch}: Frequency set to {frequency} Hz")
        self._error_check()

    def get_frequency(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current output frequency or its limits for the specified channel.

        Note: For Arbitrary waveforms, query the sample rate using
              `get_arbitrary_waveform_sample_rate`. This method reads the main
              frequency register used by standard functions.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query
                        the allowed frequency limits for the *current* function.
                        If None (default), queries the current frequency setting.

        Returns:
            The frequency in Hertz (Hz).

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails.
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

        # SCPI: SOUR#:FREQ? [MIN|MAX] (Manual p.142)
        response = self._query(cmd).strip()
        try:
            freq = float(response)
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse frequency float from response: '{response}'")

        self._log(f"Channel {ch}: Frequency{type_str} is {freq} Hz")
        return freq

    def set_amplitude(self, channel: Union[int, str], amplitude: Union[float, str]):
        """
        Sets the output amplitude for the specified channel.

        Uses the currently configured voltage unit (VPP, VRMS, or DBM - see
        `set_voltage_unit`). The instrument validates the requested amplitude
        against the current offset voltage, load impedance, voltage limits (if enabled),
        and the characteristics of the active function.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            amplitude: The desired amplitude value in the current voltage units.
                       Can also be "MINimum", "MAXimum", or "DEFault".

        Raises:
            InstrumentParameterError: If the `amplitude` string/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value conflicts
                                          with offset, limits, or load impedance).
        """
        ch = self._validate_channel(channel)
        amp_cmd_val = self._format_value_min_max_def(amplitude)
        # Instrument handles complex validation based on current state (offset, load, limits, function)
        # SCPI: SOUR#:VOLT (Manual p.204)
        self._send_command(f"SOUR{ch}:VOLTage {amp_cmd_val}")
        # Log with the value provided, units are implicit from current setting
        unit = self.get_voltage_unit(ch) # Get current unit for logging context
        self._log(f"Channel {ch}: Amplitude set to {amplitude} (in current unit: {unit})")
        self._error_check()

    def get_amplitude(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current output amplitude or its limits for the specified channel.

        The returned value is in the currently configured voltage unit (VPP, VRMS, or DBM).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query the
                        allowed amplitude limits based on the *current* instrument state
                        (function, offset, load, etc.). If None (default), queries the
                        current amplitude setting.

        Returns:
            The amplitude in the current voltage unit.

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails.
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

        # SCPI: SOUR#:VOLT? [MIN|MAX] (Manual p.204)
        response = self._query(cmd).strip()
        try:
            amp = float(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Failed to parse amplitude float from response: '{response}'")

        unit = self.get_voltage_unit(ch) # Get unit for logging context
        self._log(f"Channel {ch}: Amplitude{type_str} is {amp} {unit}")
        return amp

    def set_offset(self, channel: Union[int, str], offset: Union[float, str]):
        """
        Sets the DC offset voltage for the specified channel.

        The instrument validates the requested offset against the current amplitude,
        load impedance, and voltage limits (if enabled).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            offset: The desired DC offset in Volts (V). Can also be "MINimum",
                    "MAXimum", or "DEFault".

        Raises:
            InstrumentParameterError: If the `offset` string/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value conflicts
                                          with amplitude or limits).
        """
        ch = self._validate_channel(channel)
        offset_cmd_val = self._format_value_min_max_def(offset)
        # Instrument handles validation against amplitude, load, limits
        # SCPI: SOUR#:VOLT:OFFS (Manual p.209)
        self._send_command(f"SOUR{ch}:VOLTage:OFFSet {offset_cmd_val}")
        self._log(f"Channel {ch}: Offset set to {offset} V")
        self._error_check()

    def get_offset(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current DC offset voltage or its limits for the specified channel.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query the
                        allowed offset limits based on the *current* instrument state
                        (amplitude, load, etc.). If None (default), queries the current
                        offset setting.

        Returns:
            The DC offset in Volts (V).

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails.
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

        # SCPI: SOUR#:VOLT:OFFS? [MIN|MAX] (Manual p.209)
        response = self._query(cmd).strip()
        try:
            offs = float(response)
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse offset float from response: '{response}'")

        self._log(f"Channel {ch}: Offset{type_str} is {offs} V")
        return offs

    def set_phase(self, channel: Union[int, str], phase: Union[float, str]):
        """
        Sets the phase offset for the waveform on the specified channel.

        The phase is relative to a reference phase, often the start of the waveform cycle
        or a synchronization signal. The units (Degrees, Radians, Seconds) are determined
        by the global `set_angle_unit()` setting.

        Note: Phase setting is not applicable for DC or Noise waveforms.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            phase: The desired phase offset value in the current angle units.
                   Can also be "MINimum", "MAXimum", or "DEFault".

        Raises:
            InstrumentParameterError: If the `phase` string/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., setting phase
                                          on a DC or Noise function, value out of range
                                          for current units [-360 to +360 deg, etc.]).
        """
        ch = self._validate_channel(channel)
        phase_cmd_val = self._format_value_min_max_def(phase)
        # Instrument validates range based on current angle units and function type
        # SCPI: SOUR#:PHAS (Manual p.178)
        self._send_command(f"SOUR{ch}:PHASe {phase_cmd_val}")
        unit = self.get_angle_unit() # Get unit for logging context
        self._log(f"Channel {ch}: Phase set to {phase} (in current unit: {unit})")
        self._error_check()

    def get_phase(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current phase offset or its limits for the specified channel.

        The returned value is in the currently configured angle unit (Degrees, Radians,
        or Seconds - see `get_angle_unit`).

        Note: Phase is not applicable for DC or Noise waveforms; querying may result
              in an instrument error.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query the
                        allowed phase limits. If None (default), queries the current
                        phase setting.

        Returns:
            The phase offset in the current angle unit.

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails (e.g., function is DC/Noise).
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

        # SCPI: SOUR#:PHAS? [MIN|MAX] (Manual p.178)
        response = self._query(cmd).strip()
        try:
            ph = float(response)
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse phase float from response: '{response}'")

        unit = self.get_angle_unit() # Get unit for logging context
        self._log(f"Channel {ch}: Phase{type_str} is {ph} {unit}")
        return ph

    def set_phase_reference(self, channel: Union[int, str]):
        """
        Defines the current phase of the waveform as the new zero-phase reference.

        This command essentially sets the current instantaneous phase angle of the
        specified channel's output signal to be 0 degrees/radians/seconds. It does
        not change the output signal itself at the moment of execution, but it resets
        the internal phase counter. Subsequent `set_phase` or `get_phase` operations
        will be relative to this new reference point.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Raises:
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:PHAS:REF (Manual p.178)
        self._send_command(f"SOUR{ch}:PHASe:REFerence")
        self._log(f"Channel {ch}: Phase reference reset (current phase defined as 0).")
        self._error_check()

    def synchronize_phase_all_channels(self):
        """
        Synchronizes the phase generators of all output channels and internal sources.

        This command aligns the internal phase counters of typically CH1, CH2, and
        any internal modulation sources to a common internal reference signal.
        This ensures a known, stable phase relationship between the channels
        immediately after execution.

        The individual channel phase offsets previously set by `set_phase` are
        maintained relative to this new common synchronization point.

        Note: This command is most relevant for multi-channel instruments.
              The `SOURce` prefix in the SCPI command is ignored by the instrument.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails.
        """
        if self.channel_count < 2:
            self._log("Warning: Phase synchronization command sent, but primarily intended for multi-channel instruments.", level="warning")
        # SCPI: PHASe:SYNC (Manual p.179) - Note: Manual shows SOUR#:PHAS:SYNC, but also just PHAS:SYNC likely global
        self._send_command("PHASe:SYNChronize")
        self._log("All channels/internal phase generators synchronized.")
        self._error_check()

    def set_phase_unlock_error_state(self, state: bool):
        """
        Configures error reporting for internal timebase phase-lock loss.

        Determines whether the instrument generates error -580 ("Reference phase-locked
        loop is unlocked") if the internal timebase reference (associated with Channel 1)
        loses phase lock with its reference source (e.g., external 10 MHz reference).

        Args:
            state: True (ON) to enable error generation on phase unlock,
                   False (OFF) to disable error generation.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails.
        """
        cmd_state = STATE_ON if state else STATE_OFF
        # SCPI: SOUR1:PHAS:UNL:ERR:STAT ON|OFF (Manual p.179) - Applies to SOURce1 context
        self._send_command(f"SOUR1:PHASe:UNLock:ERRor:STATe {cmd_state}")
        self._log(f"Phase unlock error state set to {cmd_state}")
        self._error_check()

    def get_phase_unlock_error_state(self) -> bool:
        """
        Queries whether error generation for phase unlock is enabled.

        Returns:
            True if error generation is ON, False if OFF.

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        # SCPI: SOUR1:PHAS:UNL:ERR:STAT? (Manual p.179) - Applies to SOURce1 context
        response = self._query("SOUR1:PHASe:UNLock:ERRor:STATe?").strip()
        # Instrument returns 1 (ON) or 0 (OFF)
        state = response == "1"
        self._log(f"Phase unlock error state is {'ON' if state else 'OFF'}")
        return state

    # --- Output Configuration ---

    def set_output_state(self, channel: Union[int, str], state: bool):
        """
        Enables (ON) or disables (OFF) the main signal output connector.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            state: True to turn the output ON, False to turn it OFF.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        # SCPI: OUTP#:STAT ON|OFF (Manual p.93)
        self._send_command(f"OUTPut{ch}:STATe {cmd_state}")
        self._log(f"Channel {ch}: Output state set to {cmd_state}")
        self._error_check()

    def get_output_state(self, channel: Union[int, str]) -> bool:
        """
        Queries the current state of the main signal output connector.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            True if the output is currently ON, False if OFF.

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: OUTP#:STAT? (Manual p.93) - Returns 1 (ON) or 0 (OFF)
        response = self._query(f"OUTPut{ch}:STATe?").strip()
        state = response == "1"
        self._log(f"Channel {ch}: Output state is {'ON' if state else 'OFF'}")
        return state

    def set_output_load_impedance(self, channel: Union[int, str], impedance: Union[float, str]):
        """
        Sets the expected load impedance connected to the channel's output.

        This value is used by the instrument to calculate and display voltage levels
        (Amplitude, Offset, High/Low Levels) accurately for the specified load.
        It does *not* change the instrument's physical output impedance (typically fixed).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            impedance: The expected load impedance in Ohms (e.g., 50, 75, 1000),
                       or one of the string keywords: "INFinity" (for high-Z loads),
                       "MINimum", "MAXimum", "DEFault". Case-insensitive for keywords.
                       Typical numeric range is 1 Ohm to 10 kOhm.

        Raises:
            InstrumentParameterError: If the `impedance` value or string is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value outside
                                          instrument range 1-10k).
        """
        ch = self._validate_channel(channel)
        cmd_impedance = self._format_value_min_max_def(impedance)
        # Instrument performs range check (1 to 10k Ohm) or accepts keywords
        # SCPI: OUTP#:LOAD <ohms>|INF|MIN|MAX|DEF (Manual p.94)
        self._send_command(f"OUTPut{ch}:LOAD {cmd_impedance}")
        self._log(f"Channel {ch}: Output load impedance setting updated to {impedance}")
        self._error_check()

    def get_output_load_impedance(self, channel: Union[int, str], query_type: Optional[str] = None) -> Union[float, str]:
        """
        Queries the configured output load impedance setting or its limits.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query the
                        allowed numeric impedance limits (typically 1 and 10000 Ohms).
                        If None (default), queries the current setting.

        Returns:
            - If querying current setting: The configured load impedance in Ohms (float),
              or the string "INFinity" if set to high impedance.
            - If querying MIN/MAX: The numeric limit in Ohms (float).

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails or the response cannot
                                          be parsed.
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

        # SCPI: OUTP#:LOAD? [MIN|MAX] (Manual p.94)
        response = self._query(cmd).strip()
        self._log(f"Channel {ch}: Raw impedance response{type_str} is '{response}'")

        try:
            numeric_response = float(response)
            # Instrument returns a very large number (9.9E+37) for the INFinity setting.
            # Check if the response is close to this value.
            if abs(numeric_response - 9.9e37) < 1e30:
                # Return the canonical string representation for consistency
                return LOAD_INFINITY
            else:
                # Return the specific numeric impedance or the MIN/MAX limit
                return numeric_response
        except ValueError:
            # This might happen if the instrument unexpectedly returns a string like "INF"
            # although the manual implies numeric or 9.9E37 for the query.
            # Handle the INF case defensively.
            if response.upper() == LOAD_INFINITY.upper() or response.upper() == "INF":
                 return LOAD_INFINITY
            self._log(f"Warning: Unexpected non-numeric impedance response: {response}", level="warning")
            # Raise error as we cannot interpret the value
            raise InstrumentCommunicationError(f"Could not parse impedance response: '{response}'")

    def set_output_polarity(self, channel: Union[int, str], polarity: str):
        """
        Sets the output polarity for the channel's waveform.

        "INVerted" flips the waveform vertically relative to its DC offset voltage.
        "NORMal" outputs the waveform as generated.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            polarity: Desired polarity: "NORMal" or "INVerted". Case-insensitive.
                      Abbreviations "NORM" and "INV" are also accepted.

        Raises:
            InstrumentParameterError: If `polarity` is not a valid option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        pol_upper = polarity.upper().strip()

        # Map user input (full or abbrev) to the canonical SCPI keyword
        if pol_upper in POLARITY_ABBREV_MAP:
            cmd_polarity = POLARITY_ABBREV_MAP[pol_upper]
        elif pol_upper == POLARITY_NORMAL.upper():
             cmd_polarity = POLARITY_NORMAL
        elif pol_upper == POLARITY_INVERTED.upper():
             cmd_polarity = POLARITY_INVERTED
        else:
            raise InstrumentParameterError(f"Invalid polarity '{polarity}'. Use NORMal or INVerted.")

        # SCPI: OUTP#:POL NORM|INV (Manual p.95)
        self._send_command(f"OUTPut{ch}:POLarity {cmd_polarity}")
        self._log(f"Channel {ch}: Output polarity set to {cmd_polarity}")
        self._error_check()

    def get_output_polarity(self, channel: Union[int, str]) -> str:
        """
        Queries the current output polarity for the specified channel.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The current polarity state, either "NORMal" or "INVerted".

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: OUTP#:POL? (Manual p.95) - Returns NORM or INV
        response = self._query(f"OUTPut{ch}:POLarity?").strip().upper()

        # Map SCPI response back to full constant name for consistency
        if response == POLARITY_NORMAL[:4]: # NORM
            pol_str = POLARITY_NORMAL
        elif response == POLARITY_INVERTED[:3]: # INV
            pol_str = POLARITY_INVERTED
        else:
             self._log(f"Warning: Unexpected polarity response '{response}'. Returning raw.", level="warning")
             pol_str = response # Fallback

        self._log(f"Channel {ch}: Output polarity is {pol_str}")
        return pol_str

    def set_voltage_unit(self, channel: Union[int, str], unit: str):
        """
        Selects the units used for setting and querying the output amplitude.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            unit: The desired voltage unit: "VPP" (Volts peak-to-peak),
                  "VRMS" (Volts root-mean-square), or "DBM" (decibel-milliwatts).
                  Case-insensitive. DBM requires a non-infinite load impedance.

        Raises:
            InstrumentParameterError: If `unit` is not a valid option ("VPP", "VRMS", "DBM").
            InstrumentCommunicationError: If the SCPI command fails (e.g., setting DBM
                                          with load impedance set to "INFinity").
        """
        ch = self._validate_channel(channel)
        unit_upper = unit.upper().strip()

        if unit_upper not in VALID_VOLTAGE_UNITS:
            raise InstrumentParameterError(f"Invalid voltage unit '{unit}'. Use VPP, VRMS, or DBM.")

        # Instrument handles check for DBM with High-Z load automatically
        # SCPI: SOUR#:VOLT:UNIT VPP|VRMS|DBM (Manual p.211)
        self._send_command(f"SOUR{ch}:VOLTage:UNIT {unit_upper}")
        self._log(f"Channel {ch}: Voltage unit set to {unit_upper}")
        self._error_check() # Check for error, e.g., DBM with High-Z

    def get_voltage_unit(self, channel: Union[int, str]) -> str:
        """
        Queries the currently selected voltage unit for amplitude settings.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The current voltage unit ("VPP", "VRMS", or "DBM").

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:VOLT:UNIT? (Manual p.211) - Returns VPP, VRMS, or DBM
        response = self._query(f"SOUR{ch}:VOLTage:UNIT?").strip().upper()
        # Validate response against known units
        if response not in VALID_VOLTAGE_UNITS:
             self._log(f"Warning: Unexpected voltage unit response '{response}'. Returning raw.", level="warning")
        self._log(f"Channel {ch}: Voltage unit is {response}")
        return response

    def set_voltage_limits_state(self, channel: Union[int, str], state: bool):
        """
        Enables or disables the user-defined output voltage limits.

        When enabled (True), the instrument prevents settings (Amplitude, Offset)
        that would cause the output signal's instantaneous voltage to exceed the
        defined high (`set_voltage_limit_high`) and low (`set_voltage_limit_low`)
        boundaries.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            state: True to turn voltage limits ON, False to turn them OFF.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails. This can occur if
                                          enabling the limits conflicts with the current
                                          amplitude/offset settings (i.e., the current
                                          signal already exceeds the limits being enabled).
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        # SCPI: SOUR#:VOLT:LIM:STAT ON|OFF (Manual p.208)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:STATe {cmd_state}")
        self._log(f"Channel {ch}: Voltage limits state set to {cmd_state}")
        self._error_check() # Check for conflicts if enabling limits

    def get_voltage_limits_state(self, channel: Union[int, str]) -> bool:
        """
        Queries the current state of the output voltage limits.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            True if voltage limits are currently enabled (ON), False if disabled (OFF).

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:VOLT:LIM:STAT? (Manual p.208) - Returns 1 (ON) or 0 (OFF)
        response = self._query(f"SOUR{ch}:VOLTage:LIMit:STATe?").strip()
        state = response == "1"
        self._log(f"Channel {ch}: Voltage limits state is {'ON' if state else 'OFF'}")
        return state

    def set_voltage_limit_high(self, channel: Union[int, str], voltage: Union[float, str]):
        """
        Sets the high voltage limit boundary for the output signal.

        This limit defines the maximum instantaneous voltage the output signal is
        allowed to reach. It is only active when voltage limits are enabled
        (`set_voltage_limits_state(True)`).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            voltage: The maximum allowed output voltage in Volts (V).
                     Can also be "MINimum", "MAXimum", or "DEFault".
                     Must be greater than the currently set low limit.

        Raises:
            InstrumentParameterError: If the `voltage` string/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value is
                                          less than or equal to the low limit, or
                                          conflicts with instrument hardware limits).
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(voltage)
        # Instrument validates against low limit and absolute max/min capabilities
        # SCPI: SOUR#:VOLT:LIM:HIGH (Manual p.207)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:HIGH {cmd_val}")
        self._log(f"Channel {ch}: Voltage high limit set to {voltage} V")
        self._error_check() # Check for conflicts with low limit

    def get_voltage_limit_high(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the configured high voltage limit or its possible MIN/MAX values.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query the
                        absolute minimum or maximum possible values for this limit,
                        considering hardware constraints. If None (default), queries
                        the current setting.

        Returns:
            The high voltage limit setting or boundary in Volts (V).

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails.
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

        # SCPI: SOUR#:VOLT:LIM:HIGH? [MIN|MAX] (Manual p.207)
        response = self._query(cmd).strip()
        try:
            val = float(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Failed to parse high limit float from response: '{response}'")

        self._log(f"Channel {ch}: Voltage high limit{type_str} is {val} V")
        return val

    def set_voltage_limit_low(self, channel: Union[int, str], voltage: Union[float, str]):
        """
        Sets the low voltage limit boundary for the output signal.

        This limit defines the minimum instantaneous voltage the output signal is
        allowed to reach. It is only active when voltage limits are enabled
        (`set_voltage_limits_state(True)`).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            voltage: The minimum allowed output voltage in Volts (V).
                     Can also be "MINimum", "MAXimum", or "DEFault".
                     Must be less than the currently set high limit.

        Raises:
            InstrumentParameterError: If the `voltage` string/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value is
                                          greater than or equal to the high limit, or
                                          conflicts with instrument hardware limits).
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(voltage)
        # Instrument validates against high limit and absolute max/min capabilities
        # SCPI: SOUR#:VOLT:LIM:LOW (Manual p.207)
        self._send_command(f"SOUR{ch}:VOLTage:LIMit:LOW {cmd_val}")
        self._log(f"Channel {ch}: Voltage low limit set to {voltage} V")
        self._error_check() # Check for conflicts with high limit

    def get_voltage_limit_low(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the configured low voltage limit or its possible MIN/MAX values.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query the
                        absolute minimum or maximum possible values for this limit,
                        considering hardware constraints. If None (default), queries
                        the current setting.

        Returns:
            The low voltage limit setting or boundary in Volts (V).

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails.
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

        # SCPI: SOUR#:VOLT:LIM:LOW? [MIN|MAX] (Manual p.207)
        response = self._query(cmd).strip()
        try:
            val = float(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Failed to parse low limit float from response: '{response}'")

        self._log(f"Channel {ch}: Voltage low limit{type_str} is {val} V")
        return val

    def set_voltage_autorange_state(self, channel: Union[int, str], state: str):
        """
        Configures automatic selection of output amplifier gain ranges.

        Mode Descriptions:
        - "ON": Autorange enabled continuously. The instrument automatically selects
                the optimal gain range for the current amplitude setting to maximize
                accuracy and fidelity.
        - "OFF": Uses the current fixed range. Disables automatic switching. This
                 can prevent momentary signal disruptions when amplitude changes,
                 but may result in reduced accuracy or waveform fidelity if the
                 amplitude is significantly lower than the fixed range's capability.
        - "ONCE": Performs an immediate autorange operation based on the current
                  amplitude setting, selects the appropriate fixed range, and then
                  sets the autorange state to "OFF".

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            state: The desired autorange state: "ON", "OFF", or "ONCE". Case-insensitive.

        Raises:
            InstrumentParameterError: If `state` is not "ON", "OFF", or "ONCE".
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        state_upper = state.upper().strip()
        valid_states = {STATE_ON, STATE_OFF, "ONCE"}
        if state_upper not in valid_states:
            raise InstrumentParameterError(f"Invalid autorange state '{state}'. Allowed: ON, OFF, ONCE.")

        # SCPI: SOUR#:VOLT:RANG:AUTO OFF|ON|ONCE (Manual p.210)
        # SCPI command directly accepts ON/OFF/ONCE keywords.
        self._send_command(f"SOUR{ch}:VOLTage:RANGe:AUTO {state_upper}")
        self._log(f"Channel {ch}: Voltage autorange state set to {state_upper}")
        self._error_check()

    def get_voltage_autorange_state(self, channel: Union[int, str]) -> str:
        """
        Queries the current voltage autoranging state.

        Note: The "ONCE" state is transient. After executing `set_voltage_autorange_state`
              with "ONCE", a subsequent query will typically return "OFF".

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The current autorange state, usually "ON" or "OFF".

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:VOLT:RANG:AUTO? (Manual p.210) - Returns 0 (OFF) or 1 (ON)
        response = self._query(f"SOUR{ch}:VOLTage:RANGe:AUTO?").strip()
        state_str = STATE_ON if response == "1" else STATE_OFF
        self._log(f"Channel {ch}: Voltage autorange state is {state_str} (Query response: {response})")
        return state_str

    # --- Sync Output Configuration ---

    def set_sync_output_state(self, state: bool):
        """
        Enables (ON) or disables (OFF) the front panel Sync output connector.

        This controls whether the synchronization signal (configured by other sync
        methods) is physically output from the Sync BNC connector.

        Args:
            state: True to turn the Sync output ON, False to turn it OFF.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails.
        """
        cmd_state = STATE_ON if state else STATE_OFF
        # SCPI: OUTP:SYNC[:STATe] ON|OFF (Manual p.96) - Applies globally to Sync connector
        self._send_command(f"OUTPut:SYNC:STATe {cmd_state}")
        self._log(f"Sync output state set to {cmd_state}")
        self._error_check()

    def get_sync_output_state(self) -> bool:
        """
        Queries the state of the Sync output connector.

        Returns:
            True if the Sync output is currently enabled (ON), False if disabled (OFF).

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        # SCPI: OUTP:SYNC[:STATe]? (Manual p.96) - Returns 1 (ON) or 0 (OFF)
        response = self._query("OUTPut:SYNC:STATe?").strip()
        state = response == "1"
        self._log(f"Sync output state is {'ON' if state else 'OFF'}")
        return state

    def set_sync_output_mode(self, channel: Union[int, str], mode: str):
        """
        Sets the behavior of the Sync signal relative to the channel's operation.

        This determines what event or signal the Sync pulse represents for the
        specified channel. The actual Sync output is controlled globally by
        `set_sync_output_state` and `set_sync_output_source`.

        Mode Descriptions:
        - "NORMal": Sync pulse follows the primary waveform shape, or the envelope
                    of modulation, sweep, or burst signals. This is the typical
                    "waveform cycle complete" or "trigger start" pulse.
        - "CARRier": Sync pulse follows the underlying carrier frequency during
                     modulation, sweep, or burst operations, ignoring the
                     modulation/sweep/burst envelope itself.
        - "MARKer": Sync pulse position is determined by marker settings
                    (e.g., `set_marker_frequency`, `set_marker_cycle`,
                    `set_marker_point`) depending on the operating mode (Sweep,
                    Burst, Arb).

        Args:
            channel: The channel (1 or 2) whose sync behavior is being configured.
            mode: Desired mode: "NORMal", "CARRier", or "MARKer". Case-insensitive.
                  Abbreviations "NORM", "CARR", "MARK" are accepted.

        Raises:
            InstrumentParameterError: If `mode` is not a valid option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        mode_upper = mode.upper().strip()

        # Map user input (full or abbrev) to canonical SCPI keyword
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

        # SCPI: OUTP#:SYNC:MODE NORM|CARR|MARK (Manual p.97)
        self._send_command(f"OUTPut{ch}:SYNC:MODE {cmd_mode}")
        self._log(f"Channel {ch}: Sync output mode set to {cmd_mode}")
        self._error_check()

    def get_sync_output_mode(self, channel: Union[int, str]) -> str:
        """
        Queries the Sync signal mode configured for the specified channel.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The current sync mode: "NORMal", "CARRier", or "MARKer".

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: OUTP#:SYNC:MODE? (Manual p.97) - Returns NORM, CARR, MARK
        response = self._query(f"OUTPut{ch}:SYNC:MODE?").strip().upper()

        # Map SCPI response back to full constant name
        mode_map_inv = {v[:4]: v for v in VALID_SYNC_MODES} # Map "NORM"->"NORMal", etc.
        mode_str = mode_map_inv.get(response, response) # Fallback to raw response if needed

        self._log(f"Channel {ch}: Sync output mode is {mode_str}")
        return mode_str

    def set_sync_output_polarity(self, channel: Union[int, str], polarity: str):
        """
        Sets the polarity of the Sync output signal associated with a channel.

        This affects the Sync signal generated based on the channel's operation
        (as determined by `set_sync_output_mode`). The actual output occurs via
        the global Sync connector.

        Polarity Descriptions:
        - "NORMal": Sync pulse is positive-going (typically TTL logic high level).
        - "INVerted": Sync pulse is negative-going (typically TTL logic low level).

        Args:
            channel: The channel (1 or 2) whose sync polarity is being configured.
            polarity: Desired polarity: "NORMal" or "INVerted". Case-insensitive.
                      Abbreviations "NORM", "INV" are accepted.

        Raises:
            InstrumentParameterError: If `polarity` is not a valid option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        pol_upper = polarity.upper().strip()

        # Use map or check against valid constants (copied from output polarity logic)
        if pol_upper in POLARITY_ABBREV_MAP:
            cmd_polarity = POLARITY_ABBREV_MAP[pol_upper]
        elif pol_upper == POLARITY_NORMAL.upper():
             cmd_polarity = POLARITY_NORMAL
        elif pol_upper == POLARITY_INVERTED.upper():
             cmd_polarity = POLARITY_INVERTED
        else:
            raise InstrumentParameterError(f"Invalid polarity '{polarity}'. Use NORMal or INVerted.")

        # SCPI: OUTP#:SYNC:POL NORM|INV (Manual p.98)
        self._send_command(f"OUTPut{ch}:SYNC:POLarity {cmd_polarity}")
        self._log(f"Channel {ch}: Sync output polarity set to {cmd_polarity}")
        self._error_check()

    def get_sync_output_polarity(self, channel: Union[int, str]) -> str:
        """
        Queries the polarity of the Sync output signal associated with a channel.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The current polarity: "NORMal" or "INVerted".

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: OUTP#:SYNC:POL? (Manual p.98) - Returns NORM or INV
        response = self._query(f"OUTPut{ch}:SYNC:POLarity?").strip().upper()

        # Map SCPI response back to full constant name (copied from output polarity logic)
        if response == POLARITY_NORMAL[:4]: # NORM
            pol_str = POLARITY_NORMAL
        elif response == POLARITY_INVERTED[:3]: # INV
            pol_str = POLARITY_INVERTED
        else:
             self._log(f"Warning: Unexpected sync polarity response '{response}'. Returning raw.", level="warning")
             pol_str = response # Fallback

        self._log(f"Channel {ch}: Sync output polarity is {pol_str}")
        return pol_str

    def set_sync_output_source(self, source_channel: Union[int, str]):
        """
        Selects which channel drives the front panel Sync output connector.

        This is a global setting for the Sync BNC connector, determining which
        channel's configured sync signal (mode, polarity) is routed to the output.

        Args:
            source_channel: The channel identifier (1 or 2) to use as the source.

        Raises:
            InstrumentParameterError: If the specified channel is invalid for this
                                      instrument (e.g., CH2 on a 1-channel model).
            InstrumentCommunicationError: If the SCPI command fails.
        """
        src_ch_num = self._validate_channel(source_channel) # Validates channel number exists

        # Check against the actual channel count determined during init
        if src_ch_num > self.channel_count:
             raise InstrumentParameterError(
                 f"Cannot set sync source to CH{src_ch_num}. Instrument only has {self.channel_count} channels."
             )

        # SCPI: OUTP:SYNC:SOUR CH1|CH2 (Manual p.98) - Global setting
        self._send_command(f"OUTPut:SYNC:SOURce CH{src_ch_num}")
        self._log(f"Sync output source set to CH{src_ch_num}")
        self._error_check()

    def get_sync_output_source(self) -> int:
        """
        Queries which channel is currently driving the front panel Sync output connector.

        Returns:
            The source channel number (1 or 2).

        Raises:
            InstrumentCommunicationError: If the SCPI query fails or response is unexpected.
        """
        # SCPI: OUTP:SYNC:SOUR? (Manual p.98) - Returns CH1 or CH2
        response = self._query("OUTPut:SYNC:SOURce?").strip().upper()
        if response == "CH1":
             src_ch = 1
        elif response == "CH2":
             src_ch = 2
        else:
             raise InstrumentCommunicationError(f"Unexpected response querying Sync source: '{response}'")

        self._log(f"Sync output source is CH{src_ch}")
        return src_ch

    # --- Arbitrary Waveform Specific ---

    def select_arbitrary_waveform(self, channel: Union[int, str], arb_name: str):
        """
        Selects a previously loaded arbitrary waveform from volatile memory.

        This makes the specified waveform the active one when the function type
        is set to ARB (`set_function(ch, "ARB")`). The waveform must have been
        previously downloaded using `download_arbitrary_waveform_data` or loaded
        from a file using `load_arbitrary_waveform_from_file`.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            arb_name: The name assigned to the waveform during download/load
                      (e.g., "myWave", "INT:\\BUILTIN\\SINC.ARB"). The name might
                      need to include path information if stored/loaded that way,
                      although typically only the base name assigned during download
                      to volatile memory is needed here. SCPI requires the name
                      to be enclosed in quotes in the command.

        Raises:
            InstrumentParameterError: If `arb_name` contains invalid characters or is empty.
            InstrumentCommunicationError: If the SCPI command fails (e.g., `arb_name`
                                          is not found in volatile memory).
        """
        ch = self._validate_channel(channel)
        if not arb_name:
             raise InstrumentParameterError("Arbitrary waveform name cannot be empty.")
        # Basic check for potentially problematic characters in name itself (quotes)
        if '"' in arb_name or "'" in arb_name:
             raise InstrumentParameterError("Arbitrary waveform name cannot contain quotes.")

        # SCPI: SOUR#:FUNC:ARB "<arb_name>" (Manual p.153) - Requires quotes around name
        # Ensure the name is properly quoted for the SCPI command
        quoted_arb_name = f'"{arb_name}"'
        self._send_command(f"SOUR{ch}:FUNC:ARB {quoted_arb_name}")
        self._log(f"Channel {ch}: Active arbitrary waveform selection set to '{arb_name}'")
        # Check if the name was valid and found by the instrument
        self._error_check()

    def get_selected_arbitrary_waveform_name(self, channel: Union[int, str]) -> str:
        """
        Queries the name/path of the arbitrary waveform currently selected for ARB mode.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The name/path of the selected waveform, including the quotes as returned
            by the instrument (e.g., '"MyWave"', '"INT:\\BUILTIN\\SINC.ARB"').
            Returns an empty string "" if no specific user arb is selected (instrument might default).

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:ARB? (Manual p.153)
        response = self._query(f"SOUR{ch}:FUNC:ARB?").strip()
        # Instrument returns the name enclosed in double quotes, or just ""? Check manual/behavior.
        # Assuming it returns quoted string or potentially an empty string/default name if none selected.
        self._log(f"Channel {ch}: Currently selected arbitrary waveform is {response}")
        # Return the raw response, including quotes if present.
        return response

    def set_arbitrary_waveform_sample_rate(self, channel: Union[int, str], sample_rate: Union[float, str]):
        """
        Sets the sample rate for the arbitrary waveform function.

        This determines the speed at which the waveform points are played back when
        the function is ARB. It is coupled with the ARB frequency and period settings
        (changing one affects the others based on the number of points).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            sample_rate: The desired sample rate in Samples per second (Sa/s).
                         Can also be "MINimum", "MAXimum", or "DEFault".

        Raises:
            InstrumentParameterError: If the `sample_rate` string/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value out of range,
                                          conflicts with ARB filter setting).
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sample_rate)

        # Basic config range check if available and numeric value provided
        # Instrument performs the definitive check based on filter settings etc.
        if isinstance(sample_rate, (int, float)):
             config_path = self.config.channels[ch].arbitrary.sampling_rate
             if hasattr(config_path, 'in_range'):
                 try:
                      config_path.in_range(float(sample_rate))
                 except InstrumentParameterError as e:
                      self._log(f"Warning: Sample rate {sample_rate} Sa/s is outside the basic range "
                                f"defined in the configuration. Instrument will perform final validation. "
                                f"Config error: {e}", level="warning")

        # SCPI: SOUR#:FUNC:ARB:SRATe <sample_rate> (Manual p.158)
        self._send_command(f"SOUR{ch}:FUNC:ARB:SRATe {cmd_val}")
        self._log(f"Channel {ch}: Arbitrary waveform sample rate set to {sample_rate} Sa/s")
        self._error_check() # Check for conflicts (e.g., with filter OFF)

    def get_arbitrary_waveform_sample_rate(self, channel: Union[int, str], query_type: Optional[str] = None) -> float:
        """
        Queries the current sample rate or its limits for the ARB function.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            query_type: Specify "MINimum" or "MAXimum" (case-insensitive) to query the
                        allowed sample rate limits (which may depend on filter settings).
                        If None (default), queries the current setting.

        Returns:
            The sample rate in Samples per second (Sa/s).

        Raises:
            InstrumentParameterError: If `query_type` is specified but is not
                                      "MINimum" or "MAXimum".
            InstrumentCommunicationError: If the SCPI query fails.
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

        # SCPI: SOUR#:FUNC:ARB:SRATe? [MIN|MAX] (Manual p.158)
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

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The number of points (samples) in the selected waveform. Returns 0 if
            no valid arbitrary waveform is selected or active.

        Raises:
            InstrumentCommunicationError: If the SCPI query fails (e.g., if function is not ARB
                                          or no arb waveform is selected, might return error).
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:ARB:POINts? (Manual p.156) - Also DATA:ATTR:POINts? (p.134) exists. Let's use FUNC one.
        # It's possible this query might fail if the function is not ARB. Add try/except.
        try:
            response = self._query(f"SOUR{ch}:FUNC:ARB:POINts?").strip()
            points = int(response)
            self._log(f"Channel {ch}: Currently selected arbitrary waveform has {points} points")
            return points
        except ValueError:
             raise InstrumentCommunicationError(f"Failed to parse integer points from response: '{response}'")
        except InstrumentCommunicationError as e:
            # Check if error is due to wrong function type (this is speculative based on common SCPI errors)
            code, msg = self.get_error()
            if code != 0: # Check if an error was logged
                 self._log(f"Query SOUR{ch}:FUNC:ARB:POINts? failed. Inst Err {code}: {msg}. "
                           f"Is function ARB and waveform selected? Returning 0.", level="warning")
                 return 0 # Return 0 if query failed likely due to state
            else:
                 raise e # Re-raise original communication error if no specific instrument error found

    def download_arbitrary_waveform_data(self,
                                        channel: Union[int, str],
                                        arb_name: str,
                                        data_points: Union[List[int], List[float], np.ndarray],
                                        data_type: str = "DAC",
                                        use_binary: bool = True):
        """
        Downloads arbitrary waveform data points into the instrument's volatile memory.

        This method acts as a convenient wrapper. By default (`use_binary=True`), it calls
        `download_arbitrary_waveform_data_binary` for robust transfer using the
        IEEE 488.2 binary block format. If `use_binary=False`, it calls
        `download_arbitrary_waveform_data_csv` which uses comma-separated values
        (suitable only for very small waveforms due to performance and command length limits).

        Args:
            channel: Target channel identifier (e.g., 1).
            arb_name: Name to assign the waveform in volatile memory (e.g., "myRamp").
                      Should be alphanumeric with underscores. Max 12 characters usually.
            data_points: Sequence of waveform data points (list or numpy array).
            data_type: Specifies the format/range of `data_points`.
                       - "DAC": Integers representing DAC codes (e.g., -32768 to +32767).
                       - "NORM": Floating-point values normalized from -1.0 to +1.0.
                       Defaults to "DAC". Case-insensitive.
            use_binary: If True (default), uses binary block transfer. If False, uses
                        comma-separated values (CSV).

        Raises:
            InstrumentParameterError: For invalid `arb_name`, `data_type`, or if `data_points`
                                      are outside the expected range for `data_type`.
            InstrumentCommunicationError: If the SCPI command fails (e.g., name conflict,
                                          out of memory, syntax error).
            ValueError: If data validation fails (e.g. values out of range).
        """
        if use_binary:
            self.download_arbitrary_waveform_data_binary(channel, arb_name, data_points, data_type)
        else:
            self.download_arbitrary_waveform_data_csv(channel, arb_name, data_points, data_type)


    def download_arbitrary_waveform_data_csv(self,
                                        channel: Union[int, str],
                                        arb_name: str,
                                        data_points: Union[List[int], List[float], np.ndarray],
                                        data_type: str = "DAC"):
        """
        Downloads arbitrary waveform data using comma-separated values (CSV).

        **Warning:** This method is generally NOT recommended for production use,
        especially with waveforms longer than a few hundred points. It can be slow
        and may exceed instrument SCPI command length limits. Use
        `download_arbitrary_waveform_data_binary` for better performance and reliability.

        Sends data points as a comma-separated string within the SCPI command.

        Args:
            channel: Target channel identifier (e.g., 1).
            arb_name: Name to assign the waveform in volatile memory (e.g., "myRamp").
                      Alphanumeric/underscores, max 12 chars typically.
            data_points: Sequence of waveform data points (list or numpy array).
            data_type: Specifies the format/range of `data_points`.
                       - "DAC": Integers representing DAC codes (e.g., -32768 to +32767).
                       - "NORM": Floating-point values normalized from -1.0 to +1.0.
                       Defaults to "DAC". Case-insensitive.

        Raises:
            InstrumentParameterError: For invalid `arb_name`, `data_type`, or empty data.
            ValueError: If `data_points` values are outside the expected range for `data_type`.
            InstrumentCommunicationError: If the SCPI command fails (e.g., name conflict
                                          (Err 786), out of memory (Err 781), syntax
                                          (Err -113), command too long).
        """
        ch = self._validate_channel(channel)
        if not re.match(r"^[a-zA-Z0-9_]{1,12}$", arb_name): # Added length check (typical limit)
            raise InstrumentParameterError(
                f"Arbitrary waveform name '{arb_name}' is invalid. Use 1-12 alphanumeric/underscore characters."
            )

        data_type_upper = data_type.upper().strip()
        if data_type_upper not in ["DAC", "NORM"]:
            raise InstrumentParameterError("Invalid data_type. Must be 'DAC' or 'NORM'.")

        # Convert to numpy array for easier processing and validation
        np_data = np.asarray(data_points)
        if np_data.ndim != 1 or np_data.size == 0:
             raise InstrumentParameterError("data_points must be a non-empty 1D sequence.")

        # Validate data range and format for CSV string
        if data_type_upper == "DAC":
            if not np.issubdtype(np_data.dtype, np.integer):
                 self._log("Warning: DAC data provided is not integer type, attempting conversion.", level="warning")
                 try:
                      np_data = np_data.astype(np.int16) # Use int16 for typical DAC range
                 except ValueError as e:
                      raise ValueError("Cannot convert DAC data points to integers.") from e
            # DAC range for EDU33210 series seems to be 16-bit signed
            dac_min, dac_max = -32768, 32767
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise ValueError(f"DAC data points out of range [{dac_min}, {dac_max}]. Found min={np.min(np_data)}, max={np.max(np_data)}")
            formatted_data = ','.join(map(str, np_data))
            scpi_suffix = ":DAC" # SCPI node suffix for DAC data
        else: # NORM
            if not np.issubdtype(np_data.dtype, np.floating):
                 self._log("Warning: Normalized data provided is not float type, attempting conversion.", level="warning")
                 try:
                      np_data = np_data.astype(float)
                 except ValueError as e:
                      raise ValueError("Cannot convert Normalized data points to floats.") from e
            norm_min, norm_max = -1.0, 1.0
            # Add a small tolerance for float comparisons
            tolerance = 1e-9
            if np.any(np_data < norm_min - tolerance) or np.any(np_data > norm_max + tolerance):
                raise ValueError(f"Normalized data points out of range [{norm_min}, {norm_max}]. Found min={np.min(np_data):.4f}, max={np.max(np_data):.4f}")
            # Clip values slightly outside the range due to precision issues
            np_data = np.clip(np_data, norm_min, norm_max)
            # Format floats with sufficient precision for SCPI
            formatted_data = ','.join(map(lambda x: f"{x:.8G}", np_data))
            scpi_suffix = "" # No suffix for normalized data (default)

        # --- NOTE: Dual Channel CSV Data Not Implemented ---
        # The manual page 132 `DATA:ARBitrary[1|2]` shows format for CSV data, but implies
        # binary block for ARB2. CSV for dual channel is complex and highly likely to
        # exceed command length limits. Sticking to single channel for CSV method.
        # If dual needed, use binary method.

        # Construct the SCPI command (single channel only for CSV)
        # Syntax: SOUR#:DATA:ARB[:DAC] <arb_name>, <value>{, <value>} (Manual p.132)
        cmd = f"SOUR{ch}:DATA:ARBitrary{scpi_suffix} {arb_name},{formatted_data}"

        # Warn about potential length issues
        # Typical SCPI buffer limits are around 256kB or less. Very long CSV strings will fail.
        if len(cmd) > 10000: # Arbitrary threshold for warning
             self._log(f"Warning: Generated SCPI command length ({len(cmd)} chars) is large. "
                       f"Consider using binary transfer (use_binary=True) for waveform '{arb_name}'.", level="warning")

        try:
            self._send_command(cmd)
            self._log(f"Channel {ch}: Downloaded arbitrary waveform '{arb_name}' via CSV "
                      f"({np_data.size} points, type: {data_type_upper})")
            self._error_check() # Crucial check after download attempt
        except InstrumentCommunicationError as e:
             self._log(f"Error during CSV arb download. Command prefix: {cmd[:100]}...", level="error")
             code, msg = self.get_error()
             # Provide more specific feedback based on common errors
             if code == -113: # Undefined header (Syntax issue)
                 raise InstrumentCommunicationError(f"SCPI Syntax Error (Err -113 'Undefined header'). Command: {cmd[:100]}...", cause=e) from e
             elif code == 786: # Name already exists
                 raise InstrumentCommunicationError(f"Arb Name Conflict (Err 786). '{arb_name}' already exists in volatile memory. Clear memory or use a different name.", cause=e) from e
             elif code == 781: # Not enough memory
                 raise InstrumentCommunicationError(f"Out of Memory (Err 781). Cannot store '{arb_name}'.", cause=e) from e
             elif code == -102: # Syntax Error (potentially due to command length)
                  raise InstrumentCommunicationError(f"SCPI Syntax Error (Err -102). Possible command length exceeded for CSV data. Command: {cmd[:100]}...", cause=e) from e
             # Add more specific error code handling if needed
             elif code != 0:
                 raise InstrumentCommunicationError(f"Arb download failed. Inst Err {code}: {msg}", cause=e) from e
             else: # If _error_check raised but get_error returned 0 (less likely)
                  raise e

    def download_arbitrary_waveform_data_binary(self,
                                         channel: Union[int, str],
                                         arb_name: str,
                                         data_points: Union[List[int], List[float], np.ndarray],
                                         data_type: str = "DAC",
                                         is_dual_channel_data: bool = False,
                                         dual_data_format: Optional[str] = None):
        """
        Downloads arbitrary waveform data using IEEE 488.2 binary block format.

        This is the recommended method for downloading arbitrary waveforms, especially
        for longer sequences, as it is more efficient and less prone to command
        length limitations than the CSV method.

        Args:
            channel: Target channel identifier (e.g., 1).
            arb_name: Name to assign the waveform in volatile memory (e.g., "myRamp").
                      Alphanumeric/underscores, max 12 chars typically.
            data_points: Sequence of waveform data points (list or numpy array).
            data_type: Specifies the format/range of `data_points`.
                       - "DAC": Integers representing DAC codes (e.g., -32768 to +32767). Data
                                will be packed as 16-bit signed integers (little-endian).
                       - "NORM": Floating-point values normalized from -1.0 to +1.0. Data
                                 will be packed as 32-bit floats (IEEE 754, little-endian).
                       Defaults to "DAC". Case-insensitive.
            is_dual_channel_data: Set True if `data_points` contains data for two channels
                                  (requires a 2-channel instrument). Defaults to False.
            dual_data_format: If `is_dual_channel_data` is True, specify the data ordering:
                              "AABB" (all CH1 points then all CH2 points) or
                              "ABAB" (interleaved points CH1, CH2, CH1, CH2...).
                              If None, the instrument's current setting is used. Case-insensitive.

        Raises:
            InstrumentParameterError: For invalid `arb_name`, `data_type`, `dual_data_format`,
                                      mismatched data length for dual channel, or empty data.
            ValueError: If `data_points` values are outside the expected range for `data_type`.
            InstrumentCommunicationError: If the SCPI command fails (e.g., name conflict
                                          (Err 786), out of memory (Err 781), syntax (Err -113)).
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

        # --- Handle Dual Channel Setup ---
        arb_cmd_node = "ARBitrary" # Base SCPI node for single channel
        if is_dual_channel_data:
            if self.channel_count < 2:
                raise InstrumentParameterError("Dual channel data download requires a 2-channel instrument.")
            arb_cmd_node = "ARBitrary2" # SCPI node for dual channel data
            # Validate data length for dual channel
            if num_points_total % 2 != 0:
                raise InstrumentParameterError("Total data_points must be even for dual channel data.")
            num_points_per_channel = num_points_total // 2

            if dual_data_format:
                fmt_upper = dual_data_format.upper().strip()
                if fmt_upper not in ["AABB", "ABAB"]:
                    raise InstrumentParameterError("Invalid dual_data_format. Use 'AABB' or 'ABAB'.")
                # Set the format before sending data
                # SCPI: SOUR#:DATA:ARBitrary2:FORMat AABB|ABAB (Manual p.131)
                self._send_command(f"SOUR{ch}:DATA:{arb_cmd_node}:FORMat {fmt_upper}")
                self._error_check()
                self._log(f"Channel {ch}: Dual arb data format set to {fmt_upper}")
            else:
                self._log(f"Channel {ch}: Using instrument's current dual arb data format setting.")


        # --- Prepare Binary Data Block ---
        binary_data: bytes
        scpi_suffix: str

        if data_type_upper == "DAC":
            scpi_suffix = ":DAC"
            # Ensure data is integer, convert if necessary
            if not np.issubdtype(np_data.dtype, np.integer):
                self._log("Warning: DAC data provided is not integer type, attempting conversion to int16.", level="warning")
                try:
                    np_data = np_data.astype(np.int16)
                except ValueError as e:
                    raise ValueError("Cannot convert DAC data points to int16.") from e
            # Validate range
            dac_min, dac_max = -32768, 32767
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise ValueError(f"DAC data points out of range [{dac_min}, {dac_max}]. Found min={np.min(np_data)}, max={np.max(np_data)}")
            # Pack as 16-bit signed integers, little-endian ('<h')
            binary_data = np_data.astype('<h').tobytes()

        else: # NORM
            scpi_suffix = "" # No suffix for normalized data
             # Ensure data is float, convert if necessary
            if not np.issubdtype(np_data.dtype, np.floating):
                self._log("Warning: Normalized data provided is not float type, attempting conversion to float32.", level="warning")
                try:
                     np_data = np_data.astype(np.float32)
                except ValueError as e:
                     raise ValueError("Cannot convert Normalized data points to float32.") from e
            # Validate range
            norm_min, norm_max = -1.0, 1.0
            tolerance = 1e-6 # Tolerance for float32
            if np.any(np_data < norm_min - tolerance) or np.any(np_data > norm_max + tolerance):
                raise ValueError(f"Normalized data points out of range [{norm_min}, {norm_max}]. Found min={np.min(np_data):.4f}, max={np.max(np_data):.4f}")
            # Clip values slightly outside the range due to precision issues
            np_data = np.clip(np_data, norm_min, norm_max)
            # Pack as 32-bit floats (IEEE 754), little-endian ('<f')
            binary_data = np_data.astype('<f').tobytes()

        # --- Construct and Send SCPI Command with Binary Block ---
        # Command structure: SOUR#:DATA:ARB[2][:DAC] <arb_name>, <binary_block>
        # Binary block format: #<N><NNN...><data>
        # N = number of digits in NNN...
        # NNN... = number of data bytes
        num_bytes = len(binary_data)
        num_bytes_str = str(num_bytes)
        num_digits = len(num_bytes_str)

        # Build the command prefix including the arb name
        cmd_prefix = f"SOUR{ch}:DATA:{arb_cmd_node}{scpi_suffix} {arb_name},"

        # Combine prefix, binary block header, and data
        # Note: The base Instrument class's `write_binary_values` or similar method
        # usually handles the formatting of the binary block header.
        # Assuming self._write_binary exists and handles this:
        try:
            self._write_binary(cmd_prefix, binary_data)
            transfer_type = "Binary Block"
            self._log(f"Channel {ch}: Downloaded arbitrary waveform '{arb_name}' via {transfer_type} "
                      f"({num_points_per_channel} pts/ch, {num_bytes} bytes total, type: {data_type_upper})")
            self._error_check() # Crucial check after download attempt
        except AttributeError:
             # Fallback if _write_binary doesn't exist - manual formatting
             # THIS IS LESS ROBUST - prefer using VISA's write_binary_values if available
             self._log("Warning: _write_binary method not found, attempting manual binary block formatting.", level="warning")
             header = f"#{num_digits}{num_bytes_str}"
             full_command_bytes = cmd_prefix.encode('ascii') + header.encode('ascii') + binary_data
             self.instrument.write_raw(full_command_bytes) # Assumes a write_raw method exists
             transfer_type = "Manual Binary Block"
             self._log(f"Channel {ch}: Downloaded arbitrary waveform '{arb_name}' via {transfer_type} "
                       f"({num_points_per_channel} pts/ch, {num_bytes} bytes total, type: {data_type_upper})")
             self._error_check() # Crucial check after download attempt

        except InstrumentCommunicationError as e:
             # Catch errors specifically from the binary write or subsequent error check
             self._log(f"Error during {transfer_type} arb download for '{arb_name}'.", level="error")
             code, msg = self.get_error()
             if code == 786: # Name already exists
                 raise InstrumentCommunicationError(f"Arb Name Conflict (Err 786). '{arb_name}' already exists in volatile memory. Clear memory or use a different name.", cause=e) from e
             elif code == 781: # Not enough memory
                 raise InstrumentCommunicationError(f"Out of Memory (Err 781). Cannot store '{arb_name}'.", cause=e) from e
             elif code == -113: # Undefined header (Syntax issue)
                 raise InstrumentCommunicationError(f"SCPI Syntax Error (Err -113 'Undefined header'). Check command format.", cause=e) from e
             elif code != 0:
                 raise InstrumentCommunicationError(f"Arb download failed. Inst Err {code}: {msg}", cause=e) from e
             else: # If binary write itself failed before _error_check
                  raise e
        except Exception as e:
             self._log(f"Unexpected error during binary arb download for '{arb_name}': {e}", level="error")
             raise InstrumentCommunicationError(f"Unexpected failure downloading arb '{arb_name}'", cause=e) from e


    def clear_volatile_arbitrary_waveforms(self, channel: Union[int, str]):
        """
        Clears all user-defined arbitrary waveforms from volatile memory.

        This removes all waveforms previously downloaded using methods like
        `download_arbitrary_waveform_data`. The default built-in arbitrary waveform
        (typically an exponential rise) is reloaded into volatile memory after clearing.

        Args:
            channel: The channel identifier (e.g., 1, "CH1"). Note: Although specified
                     per channel, this operation often clears memory globally or for
                     all arbs associated with the source subsystem. Check instrument
                     manual for specifics. The SCPI command is SOURce-specific.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:DATA:VOLatile:CLEar (Manual p.135)
        self._send_command(f"SOUR{ch}:DATA:VOLatile:CLEar")
        self._log(f"Channel {ch}: Cleared volatile arbitrary waveform memory.")
        self._error_check()

    def get_free_volatile_arbitrary_memory(self, channel: Union[int, str]) -> int:
        """
        Queries the number of free data points available in volatile arb memory.

        This indicates how many more arbitrary waveform points can be downloaded
        to the specified channel's volatile memory before it becomes full.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            The number of available data points remaining in volatile memory.

        Raises:
            InstrumentCommunicationError: If the SCPI query fails or the response
                                          cannot be parsed as an integer.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:DATA:VOLatile:FREE? (Manual p.136)
        response = self._query(f"SOUR{ch}:DATA:VOLatile:FREE?").strip()
        try:
            free_points = int(response)
        except ValueError:
            raise InstrumentCommunicationError(f"Unexpected non-integer response from DATA:VOL:FREE?: {response}")
        self._log(f"Channel {ch}: Free volatile arbitrary memory: {free_points} points")
        return free_points

    # --- Function-Specific Getters ---

    def get_pulse_duty_cycle(self, channel: Union[int, str]) -> float:
        """Queries the duty cycle percentage for the PULSE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:PULS:DCYC? (Manual p.164)
        response = self._query(f"SOUR{ch}:FUNC:PULS:DCYCle?").strip()
        return float(response)

    def get_pulse_period(self, channel: Union[int, str]) -> float:
        """Queries the period in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:PULS:PER? (Manual p.166)
        response = self._query(f"SOUR{ch}:FUNC:PULS:PERiod?").strip()
        return float(response)

    def get_pulse_width(self, channel: Union[int, str]) -> float:
        """Queries the pulse width in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:PULS:WIDT? (Manual p.168)
        response = self._query(f"SOUR{ch}:FUNC:PULS:WIDTh?").strip()
        return float(response)

    def get_pulse_transition_leading(self, channel: Union[int, str]) -> float:
        """Queries the leading edge transition time in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:PULS:TRAN:LEAD? (Manual p.167)
        response = self._query(f"SOUR{ch}:FUNC:PULS:TRANsition:LEADing?").strip()
        return float(response)

    def get_pulse_transition_trailing(self, channel: Union[int, str]) -> float:
        """Queries the trailing edge transition time in seconds for the PULSE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:PULS:TRAN:TRA? (Manual p.167)
        response = self._query(f"SOUR{ch}:FUNC:PULS:TRANsition:TRAiling?").strip()
        return float(response)

    def get_pulse_transition_both(self, channel: Union[int, str]) -> float:
        """Queries the transition time applied to both edges for the PULSE function."""
        # Note: Querying :BOTH? might return the LEADING edge time if they are linked.
        # It's safer to query LEADING if :BOTH? isn't explicitly supported for query.
        # Manual p.167 only shows query for LEAD and TRAIL. Assume BOTH query is not standard.
        # We return the leading edge as a proxy if BOTH was set.
        warnings.warn("Querying transition_both; returning leading edge time as proxy.", stacklevel=2)
        return self.get_pulse_transition_leading(channel)
        # ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:PULS:TRAN:BOTH? (Manual p.167 - Query not shown)
        # response = self._query(f"SOUR{ch}:FUNC:PULS:TRANsition:BOTH?").strip()
        # return float(response)

    def get_pulse_hold_mode(self, channel: Union[int, str]) -> str:
        """Queries the hold mode (WIDTh or DCYCle) for the PULSE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:PULS:HOLD? (Manual p.165) - Returns WIDT or DCYC
        response = self._query(f"SOUR{ch}:FUNC:PULS:HOLD?").strip().upper()
        return response # Return SCPI short form

    def get_square_duty_cycle(self, channel: Union[int, str]) -> float:
        """Queries the duty cycle percentage for the SQUARE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:SQU:DCYC? (Manual p.170)
        response = self._query(f"SOUR{ch}:FUNC:SQUare:DCYCle?").strip()
        return float(response)

    def get_square_period(self, channel: Union[int, str]) -> float:
        """Queries the period in seconds for the SQUARE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:SQU:PER? (Manual p.171)
        response = self._query(f"SOUR{ch}:FUNC:SQUare:PERiod?").strip()
        return float(response)

    def get_ramp_symmetry(self, channel: Union[int, str]) -> float:
        """Queries the symmetry percentage for the RAMP/TRIANGLE function."""
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:FUNC:RAMP:SYMM? (Manual p.169)
        response = self._query(f"SOUR{ch}:FUNC:RAMP:SYMMetry?").strip()
        return float(response)

    # --- System and Unit Settings ---

    def set_angle_unit(self, unit: str):
        """
        Specifies the angle units used for phase-related commands.

        This setting affects commands like `set_phase`, `get_phase`, `set_burst_phase`,
        and `set_pm_deviation`. It applies globally to the instrument.

        Args:
            unit: The desired angle unit: "DEGree", "RADian", "SECond", or "DEFault".
                  Abbreviations "DEG", "RAD", "SEC", "DEF" are accepted. Case-insensitive.

        Raises:
            InstrumentParameterError: If `unit` is not a valid option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        unit_upper = unit.upper().strip()
        valid_units_scpi = {"DEGREE", "RADIAN", "SECOND", "DEFAULT"}
        map_to_scpi = {"DEG": "DEGREE", "RAD": "RADIAN", "SEC": "SECOND", "DEF": "DEFAULT"}

        # Map abbreviations or use directly if full name provided
        scpi_unit = map_to_scpi.get(unit_upper)
        if not scpi_unit and unit_upper in valid_units_scpi:
             scpi_unit = unit_upper # User provided full name like "DEGREE"

        if not scpi_unit:
            raise InstrumentParameterError(
                f"Invalid angle unit '{unit}'. Use DEGree, RADian, SECond, or DEFault (or DEG, RAD, SEC, DEF)."
            )

        # SCPI: UNIT:ANGLe DEG|RAD|SEC|DEF (Manual p.238)
        self._send_command(f"UNIT:ANGLe {scpi_unit}")
        self._log(f"Global angle unit set to {scpi_unit}")
        self._error_check()

    def get_angle_unit(self) -> str:
        """
        Queries the current global angle unit setting used for phase parameters.

        Returns:
            The current angle unit abbreviation ("DEG", "RAD", or "SEC").

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        # SCPI: UNIT:ANGLe? (Manual p.238) - Instrument returns short form DEG/RAD/SEC
        response = self._query("UNIT:ANGLe?").strip().upper()
        # Validate response
        if response not in ["DEG", "RAD", "SEC"]:
             self._log(f"Warning: Unexpected angle unit response '{response}'. Returning raw.", level="warning")
        self._log(f"Current global angle unit is {response}")
        return response

    # --- Apply Command ---

    def apply_waveform_settings(self,
                                channel: Union[int, str],
                                function_type: str,
                                frequency: Union[float, str] = LOAD_DEFAULT,
                                amplitude: Union[float, str] = LOAD_DEFAULT,
                                offset: Union[float, str] = LOAD_DEFAULT):
        """
        Configures a standard waveform function and its primary parameters in one command.

        This high-level command provides a convenient way to set up common waveforms.
        It typically performs several implicit actions besides setting the specified
        parameters (check instrument manual for exact behavior):
        - Selects the specified waveform function.
        - Sets the trigger source to Immediate.
        - Disables any active modulation, sweep, or burst mode.
        - Turns the channel output ON.
        - Enables voltage autoranging (VOLT:RANG:AUTO ON).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            function_type: The desired waveform function (e.g., "SINE", "SQUare", "RAMP",
                           "PULSe", "NOISe", "PRBS", "ARB", "DC", "TRIangle").
                           Use user-friendly name or SCPI name. Case-insensitive.
            frequency: Frequency in Hz (for standard waveforms) or Sample Rate in Sa/s
                       (for ARB). Defaults to "DEFault". Can be "MINimum", "MAXimum".
                       For DC and Noise, this parameter is often ignored but might need
                       to be provided as a placeholder (e.g., DEFault).
            amplitude: Amplitude in the current voltage units. Defaults to "DEFault".
                       Can be "MINimum", "MAXimum". For DC, this is ignored.
            offset: DC offset in Volts. Defaults to "DEFault". Can be "MINimum", "MAXimum".
                    For DC, this sets the DC level.

        Raises:
            InstrumentParameterError: If the function type is not supported by the APPLy
                                      command, or if parameters are invalid for the function.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        # Get the short SCPI name first (e.g., SIN, SQU) using the robust helper
        scpi_short_name = self._get_scpi_function_name(function_type)

        # Map short SCPI name to the longer suffix used in APPLy commands (Manual p.110-117)
        # Keys are the short names (FUNC_SIN etc.), values are the APPLy suffixes.
        apply_suffix_map = {
            FUNC_SIN: "SINusoid", FUNC_SQUARE: "SQUare", FUNC_RAMP: "RAMP",
            FUNC_PULSE: "PULSe", FUNC_PRBS: "PRBS", FUNC_NOISE: "NOISe",
            FUNC_ARB: "ARBitrary", FUNC_DC: "DC", FUNC_TRI: "TRIangle"
        }
        apply_suffix = apply_suffix_map.get(scpi_short_name)

        if not apply_suffix:
            # This should not happen if _get_scpi_function_name worked and map is complete
            raise InstrumentParameterError(
                f"Function '{function_type}' (mapped to {scpi_short_name}) is not supported by the APPLy command."
            )

        # Format parameters carefully using the helper function
        # Note: Order matters: Frequency, Amplitude, Offset
        params = []
        # Frequency/SampleRate parameter (placeholder needed even if not used by DC/Noise)
        params.append(self._format_value_min_max_def(frequency))
        # Amplitude parameter (placeholder needed even if not used by DC)
        params.append(self._format_value_min_max_def(amplitude))
        # Offset parameter
        params.append(self._format_value_min_max_def(offset))

        # Construct the command string: SOUR#:APPL:<Suffix> [Freq[,Ampl[,Offs]]]
        param_str = ",".join(params)
        cmd = f"SOUR{ch}:APPLy:{apply_suffix} {param_str}" # Space before params

        self._send_command(cmd)
        self._log(f"Channel {ch}: Applied {apply_suffix} with params: Freq/SR={frequency}, Ampl={amplitude}, Offs={offset}")
        # Check for errors after the composite command, as it performs many actions
        self._error_check()

    def get_channel_configuration_summary(self, channel: Union[int, str]) -> str:
        """
        Queries a summary string of the channel's current configuration.

        This typically corresponds to the parameters settable by the `APPLy` command.
        The format is usually: `"FUNCTION +FREQUENCY, +AMPLITUDE, +OFFSET"`

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            A string summarizing the channel's configuration as returned by the
            instrument (often includes surrounding quotes). Example:
            `'"SIN +1.000000000000000E+03,+1.500000000000000E+00,+1.000000000000000E-01"'`

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        ch = self._validate_channel(channel)
        # SCPI: SOUR#:APPLy? (Manual p.109)
        response = self._query(f"SOUR{ch}:APPLy?").strip()
        self._log(f"Channel {ch}: Configuration summary query (APPLy?) returned: {response}")
        return response

    # --- Get Complete Config ---
    def get_complete_config(self, channel: Union[int, str]) -> WaveformConfigResult:
        """
        Retrieves a detailed configuration snapshot of the specified channel.

        This method queries multiple individual parameters (function, frequency,
        amplitude, offset, phase, output state, load, units, and relevant
        function-specific parameters like symmetry or duty cycle) and returns
        them structured in a `WaveformConfigResult` dataclass.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").

        Returns:
            A `WaveformConfigResult` dataclass instance populated with the current settings.

        Raises:
            InstrumentCommunicationError: If any underlying SCPI query fails.
        """
        ch_num = self._validate_channel(channel)
        self._log(f"Getting complete configuration snapshot for channel {ch_num}...")
        try:
            # Query standard parameters using existing getter methods
            func_name = self.get_function(ch_num) # Returns short SCPI name (SIN, SQU, etc.)
            freq = self.get_frequency(ch_num) # Gets standard freq, not ARB sample rate
            ampl = self.get_amplitude(ch_num)
            offs = self.get_offset(ch_num)
            output_state = self.get_output_state(ch_num)
            load_impedance = self.get_output_load_impedance(ch_num)
            voltage_unit = self.get_voltage_unit(ch_num)

            # Phase query might fail for DC/Noise, handle it gracefully
            phase: Optional[float] = None
            if func_name not in {FUNC_DC, FUNC_NOISE}:
                try:
                    phase = self.get_phase(ch_num)
                except InstrumentCommunicationError as e:
                    self._log(f"Note: Phase query failed for CH{ch_num} (likely normal for function {func_name}): {e}", level="info")
                    # Check if the error queue confirms the reason (optional, depends on instrument behavior)
                    err_code, err_msg = self.get_error()
                    if err_code != 0:
                         self._log(f"Instrument error during phase query: {err_code} - {err_msg}", level="info")

            # Query function-specific parameters using new getter methods
            symmetry: Optional[float] = None
            duty_cycle: Optional[float] = None
            try:
                if func_name in {FUNC_RAMP, FUNC_TRI}:
                    symmetry = self.get_ramp_symmetry(ch_num)
                elif func_name == FUNC_SQUARE:
                    duty_cycle = self.get_square_duty_cycle(ch_num)
                elif func_name == FUNC_PULSE:
                    duty_cycle = self.get_pulse_duty_cycle(ch_num)
                # Add queries for other function-specific params if needed (e.g., ARB sample rate)
                # Note: The 'frequency' field already holds standard freq; ARB SR might need separate handling
                # if get_frequency doesn't return SR when function is ARB. Let's assume get_frequency works
                # for standard funcs and ARB SR needs get_arbitrary_waveform_sample_rate.
                # For simplicity here, we'll rely on 'frequency' holding the primary value reported by get_frequency.

            except InstrumentCommunicationError as e:
                 # Log if specific getters fail (e.g., querying duty cycle when func is SINE)
                 self._log(f"Note: Query failed for function-specific parameter for CH{ch_num} function {func_name}: {e}", level="info")
                 err_code, err_msg = self.get_error()
                 if err_code != 0:
                      self._log(f"Instrument error during func-specific query: {err_code} - {err_msg}", level="info")


            # Construct the result dataclass
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
             # Wrap the exception for consistent error handling
             raise InstrumentCommunicationError(f"Failed getting complete config for CH{ch_num}. Cause: {e}", cause=e) from e

    # --- Modulation (AM, FM Examples - Add more as needed) ---

    def enable_modulation(self, channel: Union[int, str], mod_type: str, state: bool):
        """
        Enables or disables a specific modulation type for the channel.

        Only one modulation mode (AM, FM, PM, PWM, FSK, BPSK, SUM) can be active
        at a time per channel. Enabling one type typically disables any other active
        modulation, as well as sweep and burst modes.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            mod_type: The modulation type to enable/disable (e.g., "AM", "FM", "PM",
                      "PWM", "FSK", "BPSK", "SUM"). Case-insensitive.
            state: True to enable (ON), False to disable (OFF).

        Raises:
            InstrumentParameterError: If `mod_type` is not a valid modulation type
                                      supported by this class/instrument.
            InstrumentCommunicationError: If the SCPI command fails (e.g., trying to enable
                                          modulation when sweep/burst is active, or on an
                                          incompatible function like DC/Noise).
        """
        ch = self._validate_channel(channel)
        mod_upper = mod_type.upper().strip()
        # Define valid modulation types based on manual/implemented methods
        valid_mods = {"AM", "FM", "PM", "PWM", "FSK", "BPSK", "SUM"} # Add others as implemented
        if mod_upper not in valid_mods:
            raise InstrumentParameterError(f"Invalid or unsupported modulation type '{mod_type}'. Allowed: {valid_mods}")

        cmd_state = STATE_ON if state else STATE_OFF
        # SCPI: SOUR#:MOD_TYPE:STATe ON|OFF (e.g., SOUR1:AM:STATe ON, manual p.106)
        self._send_command(f"SOUR{ch}:{mod_upper}:STATe {cmd_state}")
        self._log(f"Channel {ch}: {mod_upper} modulation state set to {cmd_state}")
        # Check for conflicts (e.g., enabling while sweep/burst active)
        self._error_check()

    # --- AM Specific ---
    def set_am_depth(self, channel: Union[int, str], depth_percent: Union[float, str]):
        """
        Sets the Amplitude Modulation (AM) depth.

        The depth is specified as a percentage of the carrier amplitude. A depth of 100%
        causes the output to vary from 0% to 200% of the carrier's amplitude setting.
        Depths > 100% are possible (up to 120%) but may clip if the resulting peak
        voltage exceeds instrument limits.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            depth_percent: Modulation depth (typically 0% to 120%).
                           Can also be "MINimum", "MAXimum", "DEFault".

        Raises:
            InstrumentParameterError: If `depth_percent` format/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., value conflicts).
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(depth_percent)

        # Basic range check for user feedback (instrument does final validation)
        if isinstance(depth_percent, (int, float)) and not (0 <= float(depth_percent) <= 120):
            self._log(f"Warning: AM depth {depth_percent}% is outside the typical 0-120 range.", level="warning")

        # SCPI: SOUR#:AM:DEPTh <depth> (Manual p.104)
        self._send_command(f"SOUR{ch}:AM:DEPTh {cmd_val}")
        self._log(f"Channel {ch}: AM depth set to {depth_percent}%")
        self._error_check()

    def set_am_source(self, channel: Union[int, str], source: str):
        """
        Selects the source for the Amplitude Modulation (AM) signal.

        Args:
            channel: The channel identifier (e.g., 1) being modulated.
            source: The modulation source: "INTernal", "CH1", or "CH2". Case-insensitive.
                    Abbreviation "INT" is accepted for "INTernal". Using CH1/CH2 requires
                    a 2-channel instrument and that the source channel differs from the
                    modulated channel.

        Raises:
            InstrumentParameterError: If `source` is invalid, or attempting to modulate
                                      a channel with itself, or using CH2 on a 1-channel instrument.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        src_upper = source.upper().strip()

        # Map abbreviations and check validity
        if src_upper in MOD_SOURCE_ABBREV_MAP:
             cmd_src = MOD_SOURCE_ABBREV_MAP[src_upper]
        elif src_upper in VALID_MOD_SOURCES:
             cmd_src = src_upper # User provided full name like "INTERNAL" or "CH1"
             # Need to map back to canonical for comparison/logging if needed
             src_map_inv = {v.upper(): v for v in VALID_MOD_SOURCES}
             cmd_src = src_map_inv.get(src_upper, src_upper) # Use canonical INTERNAL, CH1, CH2
        else:
            raise InstrumentParameterError(f"Invalid AM source '{source}'. Use INTernal, CH1, or CH2.")

        # Prevent self-modulation
        if cmd_src == f"CH{ch}":
            raise InstrumentParameterError(f"Channel {ch} cannot be its own AM source.")
        # Check if CH2 is valid for this instrument
        if cmd_src == MOD_SOURCE_CH2 and self.channel_count < 2:
            raise InstrumentParameterError("CH2 source is invalid for a 1-channel instrument.")

        # SCPI: SOUR#:AM:SOUR INT|CH1|CH2 (Manual p.106)
        self._send_command(f"SOUR{ch}:AM:SOURce {cmd_src}")
        self._log(f"Channel {ch}: AM source set to {cmd_src}")
        self._error_check()

    # --- FM Specific Example ---
    def set_fm_deviation(self, channel: Union[int, str], deviation_hz: Union[float, str]):
        """
        Sets the peak frequency deviation for Frequency Modulation (FM).

        This value represents the maximum shift (in Hertz) from the carrier frequency
        that is caused by the modulating signal at its peak.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            deviation_hz: The peak frequency deviation in Hertz (Hz).
                          Must be less than or equal to the carrier frequency.
                          The sum (carrier frequency + deviation) must not exceed the
                          instrument's maximum frequency limit for the function.
                          Can also be "MINimum", "MAXimum", "DEFault".

        Raises:
            InstrumentParameterError: If `deviation_hz` format/value is invalid.
            InstrumentCommunicationError: If the SCPI command fails (e.g., deviation
                                          is too large for the carrier frequency).
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(deviation_hz)
        # Instrument performs validation against carrier frequency and max frequency limits
        # SCPI: SOUR#:FM:DEV <deviation> (Manual p.138)
        self._send_command(f"SOUR{ch}:FM:DEViation {cmd_val}")
        self._log(f"Channel {ch}: FM deviation set to {deviation_hz} Hz")
        self._error_check()

    # --- Sweep ---
    def enable_sweep(self, channel: Union[int, str], state: bool):
        """
        Enables (True) or disables (False) frequency sweep mode for the channel.

        Enabling sweep typically disables modulation and burst modes.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            state: True to enable sweep mode, False to disable.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails (e.g., conflicts
                                          with modulation/burst).
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        # SCPI: SOUR#:SWE:STAT ON|OFF (Manual p.201). Note: This likely sets FREQ:MODE implicitly.
        self._send_command(f"SOUR{ch}:SWEep:STATe {cmd_state}")
        self._log(f"Channel {ch}: Sweep state set to {cmd_state}")
        self._error_check() # Check for conflicts

    def set_sweep_time(self, channel: Union[int, str], sweep_time_sec: Union[float, str]):
        """
        Sets the time duration for one frequency sweep (from start to stop frequency).

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            sweep_time_sec: Sweep duration in seconds. Instrument limits apply
                            (e.g., 1 ms to 500 s). Can also be "MINimum",
                            "MAXimum", "DEFault".

        Raises:
            InstrumentParameterError: If `sweep_time_sec` format/value is invalid.
            InstrumentCommunicationError: If value is out of range or conflicts with
                                          trigger settings (e.g., timer).
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sweep_time_sec)
        # SCPI: SOUR#:SWE:TIME <seconds> (Manual p.201)
        self._send_command(f"SOUR{ch}:SWEep:TIME {cmd_val}")
        self._log(f"Channel {ch}: Sweep time set to {sweep_time_sec} s")
        self._error_check()

    def set_sweep_start_frequency(self, channel: Union[int, str], freq_hz: Union[float, str]):
        """
        Sets the starting frequency for the frequency sweep.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            freq_hz: The starting frequency in Hertz (Hz). Can also be "MINimum",
                     "MAXimum", "DEFault". Must be within the function's frequency range.

        Raises:
            InstrumentParameterError: If `freq_hz` format/value is invalid.
            InstrumentCommunicationError: If the value is out of range or conflicts with
                                          the stop frequency.
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        # SCPI: SOUR#:FREQ:STARt <frequency> (Manual p.146)
        self._send_command(f"SOUR{ch}:FREQuency:STARt {cmd_val}")
        self._log(f"Channel {ch}: Sweep start frequency set to {freq_hz} Hz")
        self._error_check()

    def set_sweep_stop_frequency(self, channel: Union[int, str], freq_hz: Union[float, str]):
        """
        Sets the ending frequency for the frequency sweep.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            freq_hz: The ending frequency in Hertz (Hz). Can also be "MINimum",
                     "MAXimum", "DEFault". Must be within the function's frequency range.

        Raises:
            InstrumentParameterError: If `freq_hz` format/value is invalid.
            InstrumentCommunicationError: If the value is out of range or conflicts with
                                          the start frequency.
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        # SCPI: SOUR#:FREQ:STOP <frequency> (Manual p.146)
        self._send_command(f"SOUR{ch}:FREQuency:STOP {cmd_val}")
        self._log(f"Channel {ch}: Sweep stop frequency set to {freq_hz} Hz")
        self._error_check()

    def set_sweep_spacing(self, channel: Union[int, str], spacing: str):
        """
        Sets the sweep frequency spacing to LINear or LOGarithmic.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            spacing: Desired spacing: "LINear" or "LOGarithmic". Case-insensitive.
                     Abbreviations "LIN", "LOG" accepted.

        Raises:
            InstrumentParameterError: If `spacing` is not a valid option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        spacing_upper = spacing.upper().strip()

        # Map user input (full or abbrev) to canonical SCPI keyword
        if spacing_upper in SWEEP_ABBREV_MAP:
            cmd_spacing = SWEEP_ABBREV_MAP[spacing_upper]
        elif spacing_upper == SWEEP_LINEAR.upper():
             cmd_spacing = SWEEP_LINEAR
        elif spacing_upper == SWEEP_LOGARITHMIC.upper():
             cmd_spacing = SWEEP_LOGARITHMIC
        else:
            raise InstrumentParameterError(f"Invalid sweep spacing '{spacing}'. Use LINear or LOGarithmic.")

        # SCPI: SOUR#:SWE:SPAC LIN|LOG (Manual p.200)
        self._send_command(f"SOUR{ch}:SWEep:SPACing {cmd_spacing}")
        self._log(f"Channel {ch}: Sweep spacing set to {cmd_spacing}")
        self._error_check()

    # --- Burst ---
    def enable_burst(self, channel: Union[int, str], state: bool):
        """
        Enables (True) or disables (False) burst mode for the channel.

        Enabling burst typically disables modulation and sweep modes.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            state: True to enable burst mode, False to disable.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails (e.g., conflicts
                                          with modulation/sweep).
        """
        ch = self._validate_channel(channel)
        cmd_state = STATE_ON if state else STATE_OFF
        # SCPI: SOUR#:BURS:STAT ON|OFF (Manual p.127)
        self._send_command(f"SOUR{ch}:BURSt:STATe {cmd_state}")
        self._log(f"Channel {ch}: Burst state set to {cmd_state}")
        self._error_check() # Check for conflicts

    def set_burst_mode(self, channel: Union[int, str], mode: str):
        """
        Sets the burst operation mode.

        Mode Descriptions:
        - "TRIGgered": Outputs a specified number of waveform cycles (`set_burst_cycles`)
                       each time a trigger event occurs (from source set by
                       `set_trigger_source`). Also known as N-Cycle burst.
        - "GATed": Outputs the waveform continuously only while the external gate
                   signal (on the Trig In connector) is asserted (polarity set by
                   `set_burst_gate_polarity`). When the gate de-asserts, the current
                   cycle completes, and the output holds at the starting phase voltage.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            mode: Burst mode: "TRIGgered" or "GATed". Case-insensitive.
                  Abbreviations "TRIG", "GAT" accepted.

        Raises:
            InstrumentParameterError: If `mode` is not a valid option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        mode_upper = mode.upper().strip()

        # Map user input (full or abbrev) to canonical SCPI keyword
        if mode_upper in BURST_ABBREV_MAP:
            cmd_mode = BURST_ABBREV_MAP[mode_upper]
        elif mode_upper == BURST_TRIGGERED.upper():
             cmd_mode = BURST_TRIGGERED
        elif mode_upper == BURST_GATED.upper():
             cmd_mode = BURST_GATED
        else:
            raise InstrumentParameterError(f"Invalid burst mode '{mode}'. Use TRIGgered or GATed.")

        # SCPI: SOUR#:BURS:MODE TRIG|GAT (Manual p.125)
        self._send_command(f"SOUR{ch}:BURSt:MODE {cmd_mode}")
        self._log(f"Channel {ch}: Burst mode set to {cmd_mode}")
        self._error_check()

    def set_burst_cycles(self, channel: Union[int, str], n_cycles: Union[int, str]):
        """
        Sets the number of waveform cycles to output in each burst.

        This setting is used only when `set_burst_mode` is "TRIGgered".

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            n_cycles: Number of cycles (integer, typically 1 to 100,000,000),
                      or the string "INFinity" for continuous output after trigger,
                      or "MINimum" (usually 1), "MAXimum". Case-insensitive for strings.

        Raises:
            InstrumentParameterError: If `n_cycles` value or format is invalid (e.g.,
                                      non-integer, non-positive, invalid string).
            InstrumentCommunicationError: If the SCPI command fails (e.g., conflicts with
                                          burst period or function type).
        """
        ch = self._validate_channel(channel)
        cmd_val: str
        log_val = n_cycles # Value to log

        if isinstance(n_cycles, str):
            nc_upper = n_cycles.upper().strip()
            if nc_upper in {"MIN", "MINIMUM"}:
                 cmd_val = LOAD_MINIMUM
            elif nc_upper in {"MAX", "MAXIMUM"}:
                 cmd_val = LOAD_MAXIMUM
            elif nc_upper in {"INF", "INFINITY"}:
                 # BURSt:NCYCles specifically uses "INFinity" keyword (Manual p.126)
                 cmd_val = "INFinity"
            else:
                 raise InstrumentParameterError(f"Invalid string '{n_cycles}' for burst cycles. Use INFinity, MINimum, or MAXimum.")
        elif isinstance(n_cycles, int):
             if n_cycles < 1:
                 raise InstrumentParameterError(f"Burst cycle count must be positive integer or INF/MIN/MAX. Got {n_cycles}.")
             # Check against typical instrument limit (adjust if needed)
             inst_max_cycles = 100_000_000
             if n_cycles > inst_max_cycles:
                 self._log(f"Warning: Burst cycle count {n_cycles} exceeds typical instrument max ({inst_max_cycles}).", level="warning")
             cmd_val = str(n_cycles)
        else:
             raise InstrumentParameterError(f"Invalid type '{type(n_cycles)}' for burst cycles. Expected positive integer or string (INF/MIN/MAX).")

        # SCPI: SOUR#:BURS:NCYC <num>|INF|MIN|MAX (Manual p.126)
        self._send_command(f"SOUR{ch}:BURSt:NCYCles {cmd_val}")
        self._log(f"Channel {ch}: Burst cycles set to {log_val}")
        self._error_check() # Check for conflicts (e.g., with burst period)

    def set_burst_period(self, channel: Union[int, str], period_sec: Union[float, str]):
        """
        Sets the time interval between the start of consecutive bursts.

        This setting applies only when `set_burst_mode` is "TRIGgered" AND
        `set_trigger_source` is "IMMediate".

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            period_sec: Burst period in seconds. Instrument limits apply (e.g., 1 us
                        to 8000 s). Can also be "MINimum", "MAXimum", "DEFault".
                        The period must be long enough to accommodate the burst duration
                        (N_Cycles / Frequency) plus some instrument overhead (e.g., 1 us).

        Raises:
            InstrumentParameterError: If `period_sec` format/value is invalid.
            InstrumentCommunicationError: If the value conflicts with burst cycles/frequency,
                                          or other settings.
        """
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(period_sec)
        # Instrument validates against N_Cycles / Frequency + overhead
        # SCPI: SOUR#:BURS:INT:PER <seconds> (Manual p.124)
        self._send_command(f"SOUR{ch}:BURSt:INTernal:PERiod {cmd_val}")
        self._log(f"Channel {ch}: Internal burst period set to {period_sec} s")
        self._error_check() # Checks for conflicts

    # --- Triggering ---

    def set_trigger_source(self, channel: Union[int, str], source: str):
        """
        Selects the source that initiates a trigger event for Sweep, Burst, or List modes.

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            source: Trigger source:
                    - "IMMediate": Internal source, triggers based on rates like burst
                                   period or sweep time.
                    - "EXTernal": Hardware trigger via front panel Trig In connector.
                    - "TIMer": Internal timer set by `set_trigger_timer`.
                    - "BUS": Software trigger via `trigger_now()` or IEEE-488 *TRG.
                    Case-insensitive. Abbreviations "IMM", "EXT", "TIM" accepted.

        Raises:
            InstrumentParameterError: If `source` is not a valid trigger source option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        src_upper = source.upper().strip()

        # Map user input (full or abbrev) to canonical SCPI keyword
        if src_upper in SOURCE_ABBREV_MAP:
            cmd_src = SOURCE_ABBREV_MAP[src_upper]
        elif src_upper in VALID_TRIGGER_SOURCES:
            # Find the canonical spelling if user provided full name
            cmd_src = next((s for s in VALID_TRIGGER_SOURCES if src_upper == s.upper()), src_upper)
        elif src_upper == SOURCE_BUS.upper(): # BUS is not in ABBREV_MAP
             cmd_src = SOURCE_BUS
        else:
            raise InstrumentParameterError(f"Invalid trigger source '{source}'. Use IMMediate, EXTernal, TIMer, or BUS.")

        # SCPI: TRIG#:SOUR IMM|EXT|TIM|BUS (Manual p.235)
        self._send_command(f"TRIGger{ch}:SOURce {cmd_src}")
        self._log(f"Channel {ch}: Trigger source set to {cmd_src}")
        self._error_check()

    def set_trigger_slope(self, channel: Union[int, str], slope: str):
        """
        Selects the active edge for the EXTernal trigger input signal.

        This determines whether a rising edge ("POSitive") or falling edge ("NEGative")
        on the front-panel Trig In connector constitutes a valid hardware trigger event
        when `set_trigger_source` is "EXTernal".

        Args:
            channel: The channel identifier (e.g., 1, "CH1").
            slope: Trigger edge polarity: "POSitive" (rising) or "NEGative" (falling).
                   Case-insensitive. Abbreviations "POS", "NEG" accepted.

        Raises:
            InstrumentParameterError: If `slope` is not a valid option.
            InstrumentCommunicationError: If the SCPI command fails.
        """
        ch = self._validate_channel(channel)
        slope_upper = slope.upper().strip()

        # Map user input (full or abbrev) to canonical SCPI keyword
        if slope_upper in SLOPE_ABBREV_MAP:
            cmd_slope = SLOPE_ABBREV_MAP[slope_upper]
        elif slope_upper == SLOPE_POSITIVE.upper():
            cmd_slope = SLOPE_POSITIVE
        elif slope_upper == SLOPE_NEGATIVE.upper():
             cmd_slope = SLOPE_NEGATIVE
        else:
            raise InstrumentParameterError(f"Invalid trigger slope '{slope}'. Use POSitive or NEGative.")

        # SCPI: TRIG#:SLOP POS|NEG (Manual p.234)
        self._send_command(f"TRIGger{ch}:SLOPe {cmd_slope}")
        self._log(f"Channel {ch}: Trigger slope set to {cmd_slope}")
        self._error_check()

    def trigger_now(self, channel: Optional[Union[int, str]] = None):
        """
        Forces an immediate trigger event via software command.

        This is primarily used when the trigger source (`set_trigger_source`) is set
        to "BUS". It can also act as a manual override for other trigger sources,
        effectively injecting a single trigger event.

        Args:
            channel: Specific channel to trigger (e.g., 1, "CH1"). Sends the
                     channel-specific `TRIGger[1|2]` command. If None (default),
                     sends the general bus trigger command `*TRG`, which typically
                     triggers the channel(s) currently configured for BUS trigger source.

        Raises:
            InstrumentCommunicationError: If the SCPI command fails (e.g., if the instrument
                                          is not in a state ready to accept a trigger).
        """
        if channel is not None:
            ch = self._validate_channel(channel)
            # SCPI: TRIGger[1|2] (Manual p.233) - Forces immediate trigger for the channel
            self._send_command(f"TRIGger{ch}")
            self._log(f"Sent immediate channel-specific trigger command TRIGger{ch}")
        else:
             # SCPI: *TRG (Manual p.69) - General bus trigger
             self._send_command("*TRG")
             self._log("Sent general bus trigger command *TRG")

        # Check if the trigger command was accepted in the current instrument state
        self._error_check()

    # --- MMEMory (File System Operations - Basic Examples) ---

    def list_directory(self, path: str = "") -> FileSystemInfo:
        """
        Lists directory contents (files/folders) on internal or USB memory.

        Args:
            path: Directory path using the instrument's format (often backslashes).
                  Examples: "" (current directory), "INT:\\", "USB:\\MyData",
                  "INT:\\BUILTIN". Defaults to the current directory set by `change_directory`.

        Returns:
            A `FileSystemInfo` dataclass containing memory usage (used, free bytes)
            and a list of dictionaries describing the files/folders found. Each
            dictionary contains 'name', 'type' (e.g., 'FILE', 'FOLDER', 'ARB', 'STAT'),
            and 'size' (in bytes).

        Raises:
            InstrumentCommunicationError: If the SCPI query fails or the response
                                          cannot be parsed.
        """
        # SCPI command requires path argument to be quoted if provided
        path_scpi = f' "{path}"' if path else "" # Add space before quoted path

        # SCPI: MMEMory:CATalog[:ALL]? [<folder>] (Manual p.84)
        cmd = f"MMEMory:CATalog:ALL?{path_scpi}"
        response = self._query(cmd).strip()

        # Response format example: +1000000000,+327168572,"cmd.exe,,375808","MySetup.sta,STAT,8192"
        # Sometimes type might be empty: "somefile.txt,,1234"
        try:
            parts = response.split(',', 2)
            if len(parts) < 2:
                 raise InstrumentCommunicationError(f"Unexpected response format from MMEM:CAT?: {response}")

            bytes_used = int(parts[0])
            bytes_free = int(parts[1])
            info = FileSystemInfo(bytes_used=bytes_used, bytes_free=bytes_free)

            if len(parts) > 2 and parts[2]:
                 # Regex to find quoted file listings: "name,type,size" allowing empty type
                 # Matches: "name.ext,TYPE,1234" or "foldername,FOLD,0" or "unknown.dat,,5678"
                 file_pattern = r'"([^"]+),([^"]*),(\d+)"'
                 listings = re.findall(file_pattern, parts[2])

                 for name, ftype, size_str in listings:
                     # Default type to 'FILE' if empty in response
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


    def delete_file_or_folder(self, path: str):
        """
        Deletes a specified file or an *empty* folder from instrument memory.

        Use with extreme caution, as this operation is irreversible.

        Args:
            path: The full path to the file or empty folder to delete, using the
                  instrument's format (e.g., "USB:\\OldData.csv", "INT:\\TempFolder").
                  Ensure the path is correct for the target item type (file vs folder).

        Raises:
            InstrumentParameterError: If the path is empty.
            InstrumentCommunicationError: If the SCPI command fails (e.g., file/folder
                                          not found, folder not empty, access denied,
                                          invalid path).
        """
        if not path:
             raise InstrumentParameterError("Path cannot be empty for deletion.")

        # SCPI requires the path argument to be enclosed in quotes
        path_scpi = f'"{path}"'

        # Determine command based on likely type (heuristic or require user knowledge)
        # The SCPI commands are distinct for files (DELete) and folders (RDIRectory).
        # We rely on the user providing the correct path type. Using the wrong command
        # will likely result in an instrument error (e.g., trying RDIR on a file).
        # Let's attempt DELete first, and if it fails with a relevant error, maybe try RDIR?
        # Simpler: Require user to know if it's a file or folder, or provide separate methods.
        # For this combined method, we just send DELete and let the user handle errors if it was a folder.
        # OR: Use a flag? Let's assume DEL works for files, RDIR for folders.

        # Heuristic: Does it look like a folder (ends with separator or no extension)?
        # This is unreliable. Better to trust the user or provide separate methods.
        # Let's default to DELete as potentially safer (less likely to delete unintended folder).
        # User should ensure path is correct.

        # SCPI: MMEMory:DELete <file> (Manual p.87) - For files
        # SCPI: MMEMory:RDIRectory <folder> (Manual p.86) - For folders (must be empty)

        # We will use MMEM:DEL. If it fails because it's a non-empty folder,
        # the error check will report it. User must empty folder first then use RDIR.
        # It's safer than guessing RDIR and accidentally deleting an empty folder mistaken for a file.

        cmd = f"MMEMory:DELete {path_scpi}"
        action_logged = "file/folder" # Be generic in log as we use DELete

        try:
            self._send_command(cmd)
            self._log(f"Attempted to delete {action_logged}: '{path}' using MMEM:DELete")
            self._error_check() # Crucial: checks if deletion succeeded or why it failed
        except InstrumentCommunicationError as e:
             # Add context about potential folder issues
             code, msg = self.get_error()
             if code != 0: # Check if error queue has info
                 if "Directory not empty" in msg or "folder" in msg.lower(): # Example error checks
                     raise InstrumentCommunicationError(f"Failed to delete '{path}'. It might be a non-empty folder. "
                                                      f"Use MMEM:RDIR for empty folders. Inst Err {code}: {msg}", cause=e) from e
                 else:
                      raise InstrumentCommunicationError(f"Failed to delete '{path}'. Inst Err {code}: {msg}", cause=e) from e
             else: # If send_command failed before error check
                 raise e

