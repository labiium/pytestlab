from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, Union

from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import PowerSupplyConfig
from ..experiments import MeasurementResult # Though not directly used for return type, good for context
from uncertainties import ufloat
from uncertainties.core import UFloat # For type hinting float | UFloat

class PSUChannelConfig:
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
            self.state = "ON" if state.upper() == "ON" or state == "1" else "OFF"
        elif isinstance(state, (int, float)): # float for query results
             self.state = "ON" if int(state) == 1 else "OFF"
        else:
            raise ValueError(f"Invalid state value: {state}")


    def __repr__(self) -> str:
        return f"PSUChannelConfig(voltage={self.voltage!r}, current={self.current!r}, state='{self.state}')"

class PowerSupply(Instrument):
    """
    A class representing a Digital Power Supply that inherits from the SCPIInstrument class.

    Provides methods for setting voltage and current, and for enabling or disabling the output.

    Attributes:
        visa_resource (str): The VISA address of the device.
        profile (dict): A dictionary containing additional information about the device.
    """

    def __init__(self, config: Optional[PowerSupplyConfig] = None, debug_mode: bool = False) -> None:
        """
        Initializes a DigitalPowerSupply instance.

        Args:
            config (PowerSupplyConfig): A class containing the device configuration.
            debug_mode (bool): Enable debug mode.
        """
        if not isinstance(config, PowerSupplyConfig):
            raise InstrumentConfigurationError("PowerSupplyConfig required to initialize PowerSupply")
        super().__init__(config=config, debug_mode=debug_mode)
    
    @classmethod
    def from_config(cls: Type[PowerSupply], config: PowerSupplyConfig, debug_mode: bool = False) -> PowerSupply:
        # Assuming PowerSupplyConfig can be instantiated from a dict-like config
        # If config is a dict that needs to be passed to PowerSupplyConfig constructor:
        # return cls(config=PowerSupplyConfig(**config), debug_mode=debug_mode)
        # If config is already a PowerSupplyConfig instance:
        return cls(config=config, debug_mode=debug_mode)
    
    def set_voltage(self, channel: int, voltage: float) -> None:
        """
        Sets the voltage for the specified channel.

        Args:
            channel (int): The channel number.
            voltage (float): The voltage value to set.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        # self._check_channel_range(channel, voltage, "voltage")
        self._send_command(f"VOLTAGE {voltage}, (@{channel})")

    def set_current(self, channel: int, current: float) -> None:
        """
        Sets the current for the specified channel.

        Args:
            channel (int): The channel number.
            current (float): The current value to set.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        # self._check_channel_range(channel, current, "current")
        self._send_command(f"CURR {current}, (@{channel})")

    def output(self, channel: Union[int, List[int]], state: bool = True) -> None:
        """
        Enables or disables the output for the specified channel(s).

        Args:
            channel (Union[int, List[int]]): The channel or list of channels.
            state (bool): True to enable output, False to disable. Default is True.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
            ValueError: If the channel type is invalid.
            OUTPut[:STATe] ON | 1 | OFF | 0[, (@<chanlist>)]

        """
        
        # for chan_item in channel: # Iterate over channel if it's a list
        #     self._check_valid_channel(chan_item)
        argument: str
        if isinstance(channel, int):
            argument = str(channel)
        elif isinstance(channel, list):
            argument = ",".join([str(chan_item) for chan_item in channel])
        else:
            raise ValueError(f"Invalid channel type: {type(channel)}. Expected int or List[int].")
        # print(argument)
        self._send_command(f"OUTPut:STATe {'ON' if state else 'OFF'}, (@{argument})")


    def display(self, state: bool) -> None:
        """
        Enables or disables the display.

        Args:
            state (bool): The state to set. True for on, False for off.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.

        DISPlay[:WINDow][:STATe] ON | OFF | 1 | 0
        """
        self._send_command(f"DISP {'ON' if state else 'OFF'}")

    def read_voltage(self, channel: int) -> float | UFloat:
        """
        Reads the output voltage for the specified channel. Incorporates uncertainty if configured.

        Args:
            channel (int): The channel number.

        Returns:
            float | UFloat: The measured voltage.
        """
        # self._check_valid_channel(channel) # Assuming channel validation happens if needed
        response_str: str = self._query(f"MEAS:VOLT? (@{channel})")
        reading: float = float(response_str)
        
        value_to_return: float | UFloat = reading

        if self.config.measurement_accuracy:
            # Key e.g., "read_voltage_ch1", "read_voltage_ch2_10v_range" (if range specific)
            # For PSU readback, it's often just per channel, not range specific unless PSU has output ranges.
            # Assuming a simple key for now.
            mode_key = f"read_voltage_ch{channel}"
            self._logger.debug(f"Attempting to find accuracy spec for read_voltage on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                sigma = spec.calculate_std_dev(reading, range_value=None) # PSU readback might not have explicit "range" like DMM
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

    def read_current(self, channel: int) -> float | UFloat:
        """
        Reads the output current for the specified channel. Incorporates uncertainty if configured.

        Args:
            channel (int): The channel number.

        Returns:
            float | UFloat: The measured current.
        """
        # self._check_valid_channel(channel)
        response_str: str = self._query(f"MEAS:CURR? (@{channel})")
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

    def get_configuration(self) -> Dict[int, PSUChannelConfig]:
        """
        Gets the measured voltages, currents, and output states for all channels.
        Voltages and currents can be ufloat objects if accuracy is configured.
        
        Returns:
            Dict[int, PSUChannelConfig]: A dictionary containing the configuration for each channel.
        """
        results: Dict[int, PSUChannelConfig] = {}
        num_channels = 0
        # Assuming self.config.channels is a list of channel configurations or similar
        # and its length represents the number of channels.
        # A more robust way might be to iterate self.config.channels if it's a dict keyed by channel number
        # or if it's a list of objects each having a 'channel_number' attribute.
        # For now, using len() as implied by original code.
        if hasattr(self.config, 'channels') and self.config.channels is not None and isinstance(self.config.channels, list):
             # If channels is a list of ChannelConfig objects, iterate based on its length
             # and assume channel numbers are 1-indexed up to len(self.config.channels)
            num_channels = len(self.config.channels)
        elif hasattr(self.config, 'channel_count') and isinstance(self.config.channel_count, int):
            num_channels = self.config.channel_count # If PowerSupplyConfig has a direct channel_count
        else:
            # Fallback or raise error if channel count cannot be determined
            self._logger.warning("Could not determine number of channels from config. Assuming 0.")


        for channel_num in range(1, num_channels + 1): # Assuming 1-indexed channels
            # Use the new read_voltage and read_current methods
            voltage_val: float | UFloat = self.read_voltage(channel_num)
            current_val: float | UFloat = self.read_current(channel_num)
            state_str: str = self._query(f"OUTPut:STate? (@{channel_num})")
            
            results[channel_num] = PSUChannelConfig(
                voltage=voltage_val,
                current=current_val,
                state=state_str.strip() # State might be '0\n' or '1\n'
            )
        return results