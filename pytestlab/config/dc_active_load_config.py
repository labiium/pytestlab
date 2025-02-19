"""
DCActiveLoadConfig.py

Configuration module for DC Active Loads. This module defines a JSON‐schema–inspired
configuration and the corresponding config classes used by PyTestLab to validate and
store instrument parameters such as channels, supported modes, maximum current/voltage/power,
and optional calibration resolution data.
"""

from .instrument_config import InstrumentConfig
from .config import Config
from ..errors import InstrumentParameterError


class DCActiveLoadConfig(InstrumentConfig):
    def __init__(self,
                 manufacturer: str,
                 model: str,
                 device_type: str,
                 serial_number: str,
                 channels: list,
                 supported_modes: dict,
                 max_current: float,
                 max_voltage: float,
                 max_power: float,
                 calibration: dict = None):
        """
        Initialize the configuration for a DC active load.

        Args:
            manufacturer (str): Manufacturer name.
            model (str): Model identifier.
            device_type (str): Should be "dc_active_load".
            serial_number (str): The device serial number.
            channels (list): A list of channel definitions. Each item is a dict with a channel number
                             as key and a dict value containing:
                                 - description (str)
                                 - min_current (number)
                                 - max_current (number)
                                 - current_resolution (number)
                                 - min_voltage (number)
                                 - max_voltage (number)
                                 - voltage_resolution (number)
            supported_modes (dict): A mapping of mode abbreviations to full descriptions. For example:
                                    {"CC": "Constant Current", "CV": "Constant Voltage",
                                     "CP": "Constant Power", "CR": "Constant Resistance"}
            max_current (float): Maximum current (A) the load can sink.
            max_voltage (float): Maximum voltage (V) the load can tolerate.
            max_power (float): Maximum power (W) the load can dissipate.
            calibration (dict, optional): Calibration-related resolution data. Expected keys are:
                                          "current_calibration_resolution" and "voltage_calibration_resolution".
        """
        super().__init__(manufacturer, model, device_type, serial_number)
        self.channels = DCALChannelsConfig(*channels)
        self.supported_modes = supported_modes  # a dictionary mapping mode abbreviations
        self.max_current = self._validate_parameter(max_current, float, "max_current")
        self.max_voltage = self._validate_parameter(max_voltage, float, "max_voltage")
        self.max_power = self._validate_parameter(max_power, float, "max_power")
        if calibration:
            self.calibration = DCALCalibrationConfig(**calibration)
        else:
            self.calibration = None

    def __repr__(self):
        return (f"DCActiveLoadConfig(manufacturer={self.manufacturer}, model={self.model}, "
                f"serial_number={self.serial_number}, channels={self.channels}, "
                f"supported_modes={self.supported_modes}, max_current={self.max_current}, "
                f"max_voltage={self.max_voltage}, max_power={self.max_power}, "
                f"calibration={self.calibration})")


class DCALChannelsConfig(Config):
    def __init__(self, *channels):
        """
        Initialize channel configurations.

        Each channel is expected to be a dictionary where the key is the channel number (int)
        and the value is a dictionary with the channel parameters.
        """
        self.channels = {}
        for ch in channels:
            for ch_id, ch_config in ch.items():
                self.channels[ch_id] = DCALChannelConfig(**ch_config)

    def __getitem__(self, key: int):
        if key not in self.channels:
            raise InstrumentParameterError(
                f"Invalid channel: {key}. Valid channels: {list(self.channels.keys())}")
        return self.channels[key]

    def validate(self, channel: int) -> int:
        if not isinstance(channel, int):
            raise InstrumentParameterError("Channel must be an integer")
        if channel not in self.channels:
            raise InstrumentParameterError(
                f"Channel {channel} not found. Available channels: {list(self.channels.keys())}")
        return channel

    def __repr__(self):
        return f"DCALChannelsConfig({self.channels})"


class DCALChannelConfig(Config):
    def __init__(self,
                 description: str,
                 min_current: float,
                 max_current: float,
                 current_resolution: float,
                 min_voltage: float,
                 max_voltage: float,
                 voltage_resolution: float):
        """
        Initialize configuration for an individual channel.

        Args:
            description (str): Channel description.
            min_current (float): Minimum current (A) this channel supports.
            max_current (float): Maximum current (A) for this channel.
            current_resolution (float): Resolution (A) of current measurements/programming.
            min_voltage (float): Minimum voltage (V) allowed.
            max_voltage (float): Maximum voltage (V) allowed.
            voltage_resolution (float): Resolution (V) of voltage measurements/programming.
        """
        self.description = self._validate_parameter(description, str, "description")
        self.min_current = float(min_current)
        self.max_current = float(max_current)
        self.current_resolution = float(current_resolution)
        self.min_voltage = float(min_voltage)
        self.max_voltage = float(max_voltage)
        self.voltage_resolution = float(voltage_resolution)

    def __repr__(self):
        return (f"DCALChannelConfig(description={self.description}, min_current={self.min_current}, "
                f"max_current={self.max_current}, current_resolution={self.current_resolution}, "
                f"min_voltage={self.min_voltage}, max_voltage={self.max_voltage}, "
                f"voltage_resolution={self.voltage_resolution})")


class DCALCalibrationConfig(Config):
    def __init__(self,
                 current_calibration_resolution: float,
                 voltage_calibration_resolution: float):
        """
        Initialize calibration configuration.

        Args:
            current_calibration_resolution (float): Resolution (A) for current calibration.
            voltage_calibration_resolution (float): Resolution (V) for voltage calibration.
        """
        self.current_calibration_resolution = float(current_calibration_resolution)
        self.voltage_calibration_resolution = float(voltage_calibration_resolution)

    def __repr__(self):
        return (f"DCALCalibrationConfig(current_calibration_resolution={self.current_calibration_resolution}, "
                f"voltage_calibration_resolution={self.voltage_calibration_resolution})")
