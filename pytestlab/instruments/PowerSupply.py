from __future__ import annotations

from typing import List, Optional, Union, Self, Any, Dict
from pydantic import validate_call # Added validate_call

from .instrument import Instrument
from .scpi_engine import SCPIEngine
from ..errors import InstrumentConfigurationError, InstrumentParameterError
from ..config import PowerSupplyConfig # V2 model
from ..common.enums import SCPIOnOff # Added SCPIOnOff
from uncertainties import ufloat


class PSUChannelFacade:
    """Provides a simplified, chainable interface for a single PSU channel.

    This facade abstracts the underlying SCPI commands for common channel
    operations, allowing for more readable and fluent test scripts. For example:
    `psu.channel(1).set(voltage=5.0, current_limit=0.1).on()`

    Attributes:
        _psu: The parent `PowerSupply` instance.
        _channel: The channel number (1-based) this facade controls.
    """
    def __init__(self, psu: 'PowerSupply', channel_num: int):
        self._psu = psu
        self._channel = channel_num
        pass

    @validate_call
    def set(self, voltage: Optional[float] = None, current_limit: Optional[float] = None) -> Self:
        """Sets the voltage and/or current limit for this channel.

        Args:
            voltage: The target voltage in Volts.
            current_limit: The current limit in Amperes.

        Returns:
            The `PSUChannelFacade` instance for method chaining.
        """
        if voltage is not None:
            self._psu.set_voltage(self._channel, voltage)
        if current_limit is not None:
            self._psu.set_current(self._channel, current_limit)
        return self

    @validate_call
    def slew(self, duration_s: Optional[float] = None, enabled: bool = True) -> Self:
        """Configures the slew rate (ramp time) for this channel.

        Args:
            duration_s: The time in seconds for the voltage to ramp to its
                        set value. If None, the duration is not changed.
            enabled:    True to enable slew, False to disable.

        Returns:
            The `PSUChannelFacade` instance for method chaining.
        """
        if duration_s is not None:
            self._psu.set_slew_rate(self._channel, duration_s)
        self._psu.enable_slew_rate(self._channel, enabled)
        return self



    @validate_call
    def on(self) -> Self:
        """Enables the output of this channel."""
        self._psu.output(self._channel, True)
        return self

    @validate_call
    def off(self) -> Self:
        """Disables the output of this channel."""
        self._psu.output(self._channel, False)
        return self

    def get_voltage(self) -> float:
        """Reads the measured voltage from this channel."""
        return self._psu.read_voltage(self._channel)

    def get_current(self) -> float:
        """Reads the measured current from this channel."""
        return self._psu.read_current(self._channel)

    def get_output_state(self) -> bool:
        """Checks if the channel output is enabled (ON).

        Returns:
            True if the output is on, False otherwise.

        Raises:
            InstrumentParameterError: If the instrument returns an unexpected state.
        """
        commands = self._psu.scpi_engine.build("get_output_state", channel=self._channel)
        state_str = self._psu.scpi_engine.parse("get_output_state", self._psu._query(commands[0]))
        if state_str in ("1", "ON"):
            return True
        elif state_str in ("0", "OFF"):
            return False
        raise InstrumentParameterError(f"Unexpected output state '{state_str}' for channel {self._channel}")


class PSUChannelConfig:
    """A data class to hold the measured configuration of a single PSU channel.

    This class is used to structure the data returned by `get_configuration`,
    providing a snapshot of a channel's state. It is not a Pydantic model for
    loading configurations from files.

    Attributes:
        voltage: The measured voltage of the channel.
        current: The measured current of the channel.
        state: The output state of the channel ("ON" or "OFF").
    """
    def __init__(self, voltage: float, current: float, state: Union[int, str]) -> None:
        """Initializes the PSUChannelConfig.

        Args:
            voltage: The voltage value for the channel.
            current: The current value for the channel.
            state: The state of the channel (e.g., 0, 1, "ON", "OFF").
        """
        self.voltage: float = voltage
        self.current: float = current
        self.state: str # Store state as string "ON" or "OFF" for consistency
        if isinstance(state, str):
            # Normalize state from various string inputs like "1", "0", "ON", "OFF"
            state_upper = state.upper().strip()
            if state_upper == SCPIOnOff.ON.value or state_upper == "1":
                self.state = SCPIOnOff.ON.value
            elif state_upper == SCPIOnOff.OFF.value or state_upper == "0":
                self.state = SCPIOnOff.OFF.value
            else:
                raise ValueError(f"Invalid string state value: {state}")
        elif isinstance(state, (int, float)): # float for query results that might be like 1.0
             self.state = SCPIOnOff.ON.value if int(state) == 1 else SCPIOnOff.OFF.value
        else:
            raise ValueError(f"Invalid state value type: {type(state)}, value: {state}")


    def __repr__(self) -> str:
        return f"PSUChannelConfig(voltage={self.voltage!r}, current={self.current!r}, state='{self.state}')"

class PowerSupply(Instrument[PowerSupplyConfig]):
    """Drives a multi-channel Power Supply Unit (PSU).

    This class provides a high-level interface for controlling a programmable
    power supply. It builds upon the base `Instrument` class and adds methods
    for setting and reading voltage and current on a per-channel basis. It also
    supports incorporating measurement uncertainty if configured.

    A key feature is the `channel()` method, which returns a `PSUChannelFacade`
    for a simplified, chainable programming experience.

    Attributes:
        config: The Pydantic configuration object (`PowerSupplyConfig`)
                containing settings specific to this PSU.
        scpi_engine: The SCPI engine for building and parsing commands.
    """
    model_config = {"arbitrary_types_allowed": True}
    config: PowerSupplyConfig

    def __init__(self, config: PowerSupplyConfig, **kwargs: Any):
        super().__init__(config=config, **kwargs)
        # Initialize SCPI engine from the config if available
        if config.scpi:
            self.scpi_engine = SCPIEngine(config.scpi, variant=config.scpi_variant)
        else:
            # SCPI configuration is optional for power supplies
            self.scpi_engine = None

        # Initialize safety limit properties
        self._voltage_limit = None
        self._current_limit = None
        self._voltage_value = 0.0
        self._current_value = 0.0

    # PowerSupply uses the base Instrument.__init__ method

    @validate_call
    def set_voltage(self, channel: int, voltage: float) -> None:
        """Sets the output voltage for a specific channel.

        Args:
            channel: The channel number (1-based).
            voltage: The target voltage in Volts.

        Raises:
            InstrumentParameterError: If the channel number is invalid or the
                                      voltage is outside the configured range for
                                      that channel.
        """
        # Validate that the channel number is within the configured range
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")

        # Validate the voltage against the limits defined in the configuration
        channel_config = self.config.channels[channel - 1]
        channel_config.voltage_range.assert_in_range(voltage, name=f"Voltage for channel {channel}")

        # Build and send the SCPI command
        commands = self.scpi_engine.build("set_voltage", channel=channel, voltage=voltage)
        self._send_command(commands[0])

    @validate_call
    def set_current(self, channel: int, current: float) -> None:
        """Sets the current limit for a specific channel.

        Args:
            channel: The channel number (1-based).
            current: The current limit in Amperes.

        Raises:
            InstrumentParameterError: If the channel number is invalid or the
                                      current is outside the configured range for
                                      that channel.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")

        channel_config = self.config.channels[channel - 1] # channel is 1-based
        channel_config.current_limit_range.assert_in_range(current, name=f"Current for channel {channel}") # Assuming current_limit_range from example
        commands = self.scpi_engine.build("set_current", channel=channel, current=current)
        self._send_command(commands[0])

    @validate_call
    def set_slew_rate(self, channel: int, duration_s: float) -> None:
        """Sets the slew rate (ramp duration) for a specific channel.

        Args:
            channel: The channel number (1-based).
            duration_s: The time in seconds for the voltage to ramp to the set value.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")

        duration_ms = int(duration_s * 1000)
        commands = self.scpi_engine.build("set_slew_rate", channel=channel, duration_ms=duration_ms)
        self._send_command(commands[0])

    @validate_call
    def enable_slew_rate(self, channel: int, state: bool) -> None:
        """Enables or disables the slew rate feature for a specific channel.

        Args:
            channel: The channel number (1-based).
            state: True to enable slew, False to disable.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")

        command_name = "enable_slew_rate" if state else "disable_slew_rate"
        commands = self.scpi_engine.build(command_name, channel=channel)
        self._send_command(commands[0])

    @validate_call
    def output(self, channel: Union[int, List[int]], state: bool = True) -> None:
        """Enables or disables the output for one or more channels.

        Args:
            channel: A single channel number (1-based) or a list of channel numbers.
            state: True to enable the output (ON), False to disable (OFF).

        Raises:
            InstrumentParameterError: If any channel number is invalid.
            ValueError: If the `channel` argument is not an int or a list of ints.
        """
        channels_to_process: List[int]
        if isinstance(channel, int):
            channels_to_process = [channel]
        elif isinstance(channel, list):
            # Ensure all elements in the list are integers
            if not all(isinstance(ch, int) for ch in channel):
                raise ValueError("All elements in channel list must be integers.")
            channels_to_process = channel
        else:
            # This case should ideally be caught by validate_call if type hints are precise enough,
            # but an explicit check remains good practice.
            raise ValueError(f"Invalid channel type: {type(channel)}. Expected int or List[int].")

        num_configured_channels = len(self.config.channels) if self.config.channels else 0
        for ch_num in channels_to_process:
            if not (1 <= ch_num <= num_configured_channels):
                raise InstrumentParameterError(f"Channel number {ch_num} is out of range (1-{num_configured_channels}).")

        # Send command for each channel individually
        for ch_num in channels_to_process:
            commands = self.scpi_engine.build("set_output", channel=ch_num, state=state)
            self._send_command(commands[0])

    @validate_call
    def display(self, state: bool) -> None:
        """Enables or disables the instrument's front panel display.

        Args:
            state: True to turn the display on, False to turn it off.
        """
        commands = self.scpi_engine.build("set_display", state=state)
        self._send_command(commands[0])

    @validate_call
    def read_voltage(self, channel: int) -> Any:
        """Reads the measured output voltage from a specific channel.

        Args:
            channel: The channel number to measure (1-based).

        Returns:
            The measured voltage as a float.

        Raises:
            InstrumentParameterError: If the channel number is invalid.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")
        commands = self.scpi_engine.build("measure_voltage", channel=channel)
        reading: float = self.scpi_engine.parse("measure_voltage", self._query(commands[0]))

        value_to_return: Any = reading

        if self.config.measurement_accuracy:
            mode_key = f"read_voltage_ch{channel}"
            self._logger.debug(f"Attempting to find accuracy spec for read_voltage on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                sigma = spec.calculate_std_dev(reading, range_value=None)
                if sigma > 0:
                    try:
                        value_to_return = ufloat(reading, sigma)
                    except:
                        value_to_return = reading
                    self._logger.debug(f"Applied accuracy spec '{mode_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{mode_key}' resulted in sigma=0. Returning float.")
            else:
                self._logger.debug(f"No accuracy spec found for read_voltage on channel {channel} with key '{mode_key}'. Returning float.")
        else:
            self._logger.debug(f"No measurement_accuracy configuration in instrument for read_voltage on channel {channel}. Returning float.")

        return value_to_return

    @validate_call
    def read_current(self, channel: int) -> Any:
        """Reads the measured output current from a specific channel.

        Args:
            channel: The channel number to measure (1-based).

        Returns:
            The measured current as a float.

        Raises:
            InstrumentParameterError: If the channel number is invalid.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")
        commands = self.scpi_engine.build("measure_current", channel=channel)
        reading: float = self.scpi_engine.parse("measure_current", self._query(commands[0]))

        value_to_return: Any = reading

        if self.config.measurement_accuracy:
            mode_key = f"read_current_ch{channel}"
            self._logger.debug(f"Attempting to find accuracy spec for read_current on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                sigma = spec.calculate_std_dev(reading, range_value=None)
                if sigma > 0:
                    try:
                        value_to_return = ufloat(reading, sigma)
                    except:
                        value_to_return = reading
                    self._logger.debug(f"Applied accuracy spec '{mode_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{mode_key}' resulted in sigma=0. Returning float.")
            else:
                self._logger.debug(f"No accuracy spec found for read_current on channel {channel} with key '{mode_key}'. Returning float.")
        else:
            self._logger.debug(f"No measurement_accuracy configuration in instrument for read_current on channel {channel}. Returning float.")

        return value_to_return

    @validate_call
    def get_configuration(self) -> Dict[int, PSUChannelConfig]:
        """Reads the live state of all configured PSU channels.

        This method iterates through all channels defined in the configuration,
        queries their current voltage, current, and output state, and returns
        the collected data.

        Returns:
            A dictionary where keys are channel numbers (1-based) and values are
            `PSUChannelConfig` objects representing the state of each channel.
        """
        results: Dict[int, PSUChannelConfig] = {}
        if not self.config.channels:
            self._logger.warning("No channels defined in the PowerSupplyConfig. Cannot get configuration.")
            return results

        num_channels = len(self.config.channels)

        for channel_num in range(1, num_channels + 1): # Iterate 1-indexed channel numbers
            voltage_val: float = self.read_voltage(channel_num) # Already uses @validate_call
            current_val: float = self.read_current(channel_num) # Already uses @validate_call
            # Query output state using SCPI engine
            commands = self.scpi_engine.build("get_output_state", channel=channel_num)
            state_str: str = self.scpi_engine.parse("get_output_state", self._query(commands[0]))

            results[channel_num] = PSUChannelConfig(
                voltage=voltage_val,
                current=current_val,
                state=state_str.strip()
            )
        return results

    @validate_call
    def channel(self, ch_num: int) -> PSUChannelFacade:
        """
        Returns a facade for interacting with a specific channel.

        Args:
            ch_num (int): The channel number (1-based).

        Returns:
            PSUChannelFacade: A facade object for the specified channel.

        Raises:
            InstrumentParameterError: If channel number is invalid.
        """
        if not self.config.channels or not (1 <= ch_num <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {ch_num} is out of range (1-{num_ch}).")
        return PSUChannelFacade(self, ch_num)

    def id(self) -> str:
        """
        Queries the instrument identification string.

        Returns:
            str: The instrument identification string.
        """
        commands = self.scpi_engine.build("identify")
        return self.scpi_engine.parse("identify", self._query(commands[0]))

    def reset(self) -> None:
        """
        Resets the instrument to its factory default settings.
        """
        commands = self.scpi_engine.build("reset")
        self._send_command(commands[0])

    @property
    def voltage_limit(self) -> Optional[float]:
        """Get the current voltage safety limit."""
        return self._voltage_limit

    @voltage_limit.setter
    def voltage_limit(self, value: float) -> None:
        """Set the voltage safety limit."""
        from ..bench import SafetyLimitError

        if value < 0:
            raise SafetyLimitError(f"Voltage limit cannot be negative: {value}V")

        # Check against current voltage setting
        if hasattr(self, '_voltage_value') and self._voltage_value > value:
            raise SafetyLimitError(
                f"Cannot set voltage limit {value}V below current voltage setting {self._voltage_value}V"
            )

        self._voltage_limit = value

    @property
    def current_limit(self) -> Optional[float]:
        """Get the current safety limit."""
        return self._current_limit

    @current_limit.setter
    def current_limit(self, value: float) -> None:
        """Set the current safety limit."""
        from ..bench import SafetyLimitError

        if value < 0:
            raise SafetyLimitError(f"Current limit cannot be negative: {value}A")

        # Check against current setting
        if hasattr(self, '_current_value') and self._current_value > value:
            raise SafetyLimitError(
                f"Cannot set current limit {value}A below current setting {self._current_value}A"
            )

        self._current_limit = value

    @property
    def voltage(self) -> float:
        """Get the current voltage value."""
        return self._voltage_value

    @voltage.setter
    def voltage(self, value: float) -> None:
        """Set the voltage value with safety checking."""
        from ..bench import SafetyLimitError

        if self._voltage_limit is not None and value > self._voltage_limit:
            raise SafetyLimitError(
                f"Refusing to set voltage {value}V, which is above the safety limit of {self._voltage_limit}V."
            )

        self._voltage_value = value
        # In a real implementation, this would call set_voltage for channel 1
        # For safety testing, we just store the value

    @property
    def current(self) -> float:
        """Get the current value."""
        return self._current_value

    @current.setter
    def current(self, value: float) -> None:
        """Set the current value with safety checking."""
        from ..bench import SafetyLimitError

        if self._current_limit is not None and value > self._current_limit:
            raise SafetyLimitError(
                f"Refusing to set current {value}A, which is above the safety limit of {self._current_limit}A."
            )

        self._current_value = value
        # In a real implementation, this would call set_current for channel 1
        # For safety testing, we just store the value
