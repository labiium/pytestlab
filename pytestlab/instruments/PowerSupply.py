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
    def __init__(self, psu: 'PowerSupply', channel_num: int):
        self._psu = psu
        self._channel = channel_num

    @validate_call
    async def set(self, voltage: Optional[float] = None, current_limit: Optional[float] = None) -> Self:
        if voltage is not None:
            await self._psu.set_voltage(self._channel, voltage)
        if current_limit is not None:
            await self._psu.set_current(self._channel, current_limit)
        return self

    async def on(self) -> Self:
        await self._psu.output(self._channel, True)
        return self

    async def off(self) -> Self:
        await self._psu.output(self._channel, False)
        return self

    async def get_voltage(self) -> float | UFloat:
        return await self._psu.read_voltage(self._channel)

    async def get_current(self) -> float | UFloat:
        return await self._psu.read_current(self._channel)

    async def get_output_state(self) -> bool:
        """Checks if the channel output is ON."""
        command = f"{self._psu.SCPI_MAP.OUTPUT_STATE_QUERY_BASE} (@{self._channel})"
        state_str = (await self._psu._query(command)).strip()
        if state_str in ("1", "ON"):
            return True
        elif state_str in ("0", "OFF"):
            return False
        raise InstrumentParameterError(f"Unexpected output state '{state_str}' for channel {self._channel}")


class PSUChannelConfig: # This is a helper data class, not a Pydantic config model for file loading
    def __init__(self, voltage: float | UFloat, current: float | UFloat, state: Union[int, str]) -> None:
        """
        
        Args:
            voltage (float | UFloat): The voltage value for the channel.
            current (float | UFloat): The current value for the channel.
            state (Union[int, str]): The state of the channel. 0 for off, 1 for on, or "ON"/"OFF".
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
    model_config = {"arbitrary_types_allowed": True}
    config: PowerSupplyConfig # This is now the V2 validated model instance
    """
    A class representing a Digital Power Supply that inherits from the Instrument class.

    Provides methods for setting voltage and current, and for enabling or disabling the output.

    Attributes:
        config (PowerSupplyConfig): The validated Pydantic V2 configuration object for the instrument.
    """
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
    async def set_voltage(self, channel: int, voltage: float) -> None:
        """
        Sets the voltage for the specified channel.

        Args:
            channel (int): The channel number (1-based).
            voltage (float): The voltage value to set.

        Raises:
            InstrumentParameterError: If channel number is invalid or voltage is out of configured range.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {channel} is out of range (1-{num_ch}).")
        
        channel_config = self.config.channels[channel - 1] # channel is 1-based
        # Pydantic's validate_call handles type of channel and voltage.
        # The Range.assert_in_range is business logic validation within the config model, keep it.
        channel_config.voltage_range.assert_in_range(voltage, name=f"Voltage for channel {channel}")
        command = f"{self.SCPI_MAP.VOLTAGE_SET_BASE} {voltage}, (@{channel})"
        await self._send_command(command)

    @validate_call
    async def set_current(self, channel: int, current: float) -> None:
        """
        Sets the current for the specified channel.

        Args:
            channel (int): The channel number (1-based).
            current (float): The current value to set.

        Raises:
            InstrumentParameterError: If channel number is invalid or current is out of configured range.
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
        """
        Enables or disables the output for the specified channel(s).

        Args:
            channel (Union[int, List[int]]): The channel (1-based) or list of channels.
            state (bool): True to enable output (ON), False to disable (OFF). Default is True.

        Raises:
            InstrumentParameterError: If any channel number is invalid.
            ValueError: If the channel type is invalid.
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
        """
        Enables or disables the display.

        Args:
            state (bool): The state to set. True for on (ON), False for off (OFF).
        """
        scpi_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        await self._send_command(f"DISP {scpi_state}")

    @validate_call
    async def read_voltage(self, channel: int) -> float | UFloat:
        """
        Reads the output voltage for the specified channel. Incorporates uncertainty if configured.

        Args:
            channel (int): The channel number (1-based).

        Returns:
            float | UFloat: The measured voltage.
        
        Raises:
            InstrumentParameterError: If channel number is invalid.
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
        """
        Reads the output current for the specified channel. Incorporates uncertainty if configured.

        Args:
            channel (int): The channel number (1-based).

        Returns:
            float | UFloat: The measured current.

        Raises:
            InstrumentParameterError: If channel number is invalid.
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
        """
        Gets the measured voltages, currents, and output states for all channels.
        Voltages and currents can be ufloat objects if accuracy is configured.
        
        Returns:
            Dict[int, PSUChannelConfig]: A dictionary containing the configuration for each channel.
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