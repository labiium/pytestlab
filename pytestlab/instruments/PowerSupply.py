from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, Union, Generic, Self
from pydantic import validate_call # Added validate_call

from .instrument import Instrument
from .scpi_maps import KeysightEDU36311APSU_SCPI # Import the SCPI map
from ..errors import InstrumentConfigurationError, InstrumentParameterError
from ..config import PowerSupplyConfig # V2 model
from ..common.enums import SCPIOnOff # Added SCPIOnOff
# from ..experiments import MeasurementResult # Though not directly used for return type, good for context
from uncertainties import ufloat
from uncertainties.core import UFloat # For type hinting float | UFloat


class PSUChannelFacade:
    """Provides a simplified, chainable interface for a single PSU channel.

    This facade abstracts the underlying SCPI commands for common channel
    operations, allowing for more readable and fluent test scripts. For example:
    `await psu.channel(1).set(voltage=5.0, current_limit=0.1).on()`

    Attributes:
        _psu: The parent `PowerSupply` instance.
        _channel: The channel number (1-based) this facade controls.
    """
    def __init__(self, psu: 'PowerSupply', channel_num: int):
        self._psu = psu
        self._channel = channel_num

    @validate_call
    async def set(self, voltage: Optional[float] = None, current_limit: Optional[float] = None) -> Self:
        """Sets the voltage and/or current limit for this channel.

        Args:
            voltage: The target voltage in Volts.
            current_limit: The current limit in Amperes.

        Returns:
            The `PSUChannelFacade` instance for method chaining.
        """
        if voltage is not None:
            await self._psu.set_voltage(self._channel, voltage)
        if current_limit is not None:
            await self._psu.set_current(self._channel, current_limit)
        return self

    async def on(self) -> Self:
        """Enables the output of this channel."""
        await self._psu.output(self._channel, True)
        return self

    async def off(self) -> Self:
        """Disables the output of this channel."""
        await self._psu.output(self._channel, False)
        return self

    async def get_voltage(self) -> float | UFloat:
        """Reads the measured voltage from this channel."""
        return await self._psu.read_voltage(self._channel)

    async def get_current(self) -> float | UFloat:
        """Reads the measured current from this channel."""
        return await self._psu.read_current(self._channel)

    async def get_output_state(self) -> bool:
        """Checks if the channel output is enabled (ON).

        Returns:
            True if the output is on, False otherwise.

        Raises:
            InstrumentParameterError: If the instrument returns an unexpected state.
        """
        command = f"{self._psu.SCPI_MAP.OUTPUT_STATE_QUERY_BASE} (@{self._channel})"
        state_str = (await self._psu._query(command)).strip().upper()
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
    def __init__(self, voltage: float | UFloat, current: float | UFloat, state: Union[int, str]) -> None:
        """Initializes the PSUChannelConfig.

        Args:
            voltage: The voltage value for the channel.
            current: The current value for the channel.
            state: The state of the channel (e.g., 0, 1, "ON", "OFF").
        """
        self.voltage: float | UFloat = voltage
        self.current: float | UFloat = current
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
        SCPI_MAP: An object that maps generic functions to model-specific SCPI commands.
    """
    model_config = {"arbitrary_types_allowed": True}
    config: PowerSupplyConfig
    SCPI_MAP = KeysightEDU36311APSU_SCPI() # Instance of the map

    # __init__ already expects PowerSupplyConfig V2 due to class Generic type and type hint
    # def __init__(self, config: PowerSupplyConfig, backend: _Backend, **kwargs: Any): # backend not in current code
    #     super().__init__(config=config, backend=backend, **kwargs)
    #     # self.config is now a validated PowerSupplyConfig V2 instance
    # No change needed to __init__ based on current file content, it already takes PowerSupplyConfig

    @classmethod
    def from_config(cls: Type['PowerSupply'], config: PowerSupplyConfig, **kwargs: Any) -> 'PowerSupply':
        return cls(config=config, **kwargs)
    
    @validate_call
    async def set_voltage(self, voltage: float, channel: int = 1) -> None:
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

        # Construct and send the SCPI command
        command = f"{self.SCPI_MAP.VOLTAGE_SET_BASE} {voltage}, (@{channel})"
        await self._send_command(command)

    @validate_call
    async def set_current(self, current: float, channel: int = 1) -> None:
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
        command = f"{self.SCPI_MAP.CURRENT_SET_BASE} {current}, (@{channel})"
        await self._send_command(command)

    @validate_call
    async def output(self, channel: Union[int, List[int]], state: bool = True) -> None:
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
        
        argument = ",".join(map(str, channels_to_process))
        scpi_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        command = f"{self.SCPI_MAP.OUTPUT_STATE_SET_BASE} {scpi_state}, (@{argument})"
        await self._send_command(command)

    @validate_call
    async def display(self, state: bool) -> None:
        """Enables or disables the instrument's front panel display.

        Args:
            state: True to turn the display on, False to turn it off.
        """
        scpi_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        await self._send_command(f"DISP {scpi_state}")

    @validate_call
    async def read_voltage(self, channel: int) -> float | UFloat:
        """Reads the measured output voltage from a specific channel.

        If measurement accuracy is defined in the configuration, this method
        will return a `UFloat` object containing the value and its uncertainty.
        Otherwise, it returns a standard float.

        Args:
            channel: The channel number to measure (1-based).

        Returns:
            The measured voltage as a float or `UFloat`.

        Raises:
            InstrumentParameterError: If the channel number is invalid.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")
        command = f"{self.SCPI_MAP.MEAS_VOLTAGE_QUERY_BASE} (@{channel})"
        response_str: str = await self._query(command)
        reading: float = float(response_str)
        
        value_to_return: float | UFloat = reading

        if self.config.measurement_accuracy:
            mode_key = f"read_voltage_ch{channel}"
            self._logger.debug(f"Attempting to find accuracy spec for read_voltage on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                sigma = spec.calculate_std_dev(reading, range_value=None)
                if sigma > 0:
                    value_to_return = ufloat(reading, sigma)
                    self._logger.debug(f"Applied accuracy spec '{mode_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{mode_key}' resulted in sigma=0. Returning float.")
            else:
                self._logger.debug(f"No accuracy spec found for read_voltage on channel {channel} with key '{mode_key}'. Returning float.")
        else:
            self._logger.debug(f"No measurement_accuracy configuration in instrument for read_voltage on channel {channel}. Returning float.")
        
        return value_to_return

    @validate_call
    async def read_current(self, channel: int) -> float | UFloat:
        """Reads the measured output current from a specific channel.

        If measurement accuracy is defined in the configuration, this method
        will return a `UFloat` object containing the value and its uncertainty.
        Otherwise, it returns a standard float.

        Args:
            channel: The channel number to measure (1-based).

        Returns:
            The measured current as a float or `UFloat`.

        Raises:
            InstrumentParameterError: If the channel number is invalid.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")
        command = f"{self.SCPI_MAP.MEAS_CURRENT_QUERY_BASE} (@{channel})"
        response_str: str = await self._query(command)
        reading: float = float(response_str)

        value_to_return: float | UFloat = reading

        if self.config.measurement_accuracy:
            mode_key = f"read_current_ch{channel}"
            self._logger.debug(f"Attempting to find accuracy spec for read_current on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                sigma = spec.calculate_std_dev(reading, range_value=None)
                if sigma > 0:
                    value_to_return = ufloat(reading, sigma)
                    self._logger.debug(f"Applied accuracy spec '{mode_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{mode_key}' resulted in sigma=0. Returning float.")
            else:
                self._logger.debug(f"No accuracy spec found for read_current on channel {channel} with key '{mode_key}'. Returning float.")
        else:
            self._logger.debug(f"No measurement_accuracy configuration in instrument for read_current on channel {channel}. Returning float.")

        return value_to_return

    @validate_call
    async def get_configuration(self) -> Dict[int, PSUChannelConfig]:
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
            voltage_val: float | UFloat = await self.read_voltage(channel_num) # Already uses @validate_call
            current_val: float | UFloat = await self.read_current(channel_num) # Already uses @validate_call
            # Query output state using SCPI_MAP
            output_state_command = f"{self.SCPI_MAP.OUTPUT_STATE_QUERY_BASE} (@{channel_num})"
            state_str: str = await self._query(output_state_command)
            
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

    async def id(self) -> str:
        """
        Queries the instrument identification string.

        Returns:
            str: The instrument identification string.
        """
        return await self._query(self.SCPI_MAP.IDN)

    async def reset(self) -> None:
        """
        Resets the instrument to its factory default settings.
        """
        await self._send_command(self.SCPI_MAP.RESET)