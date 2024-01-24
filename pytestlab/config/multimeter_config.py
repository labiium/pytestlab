from .instrument_config import InstrumentConfig
from ..errors import InstrumentParameterError
from .config import SelectionConfig

class MultimeterConfig(InstrumentConfig):
    def __init__(self, manufacturer, model, vendor_id, product_id, device_type, channels, resolution, max_voltage, max_resistance, max_current, max_capacitance, max_frequency, configuration):
        # Initialize the base class with basic instrument configuration
        super().__init__(manufacturer, model, vendor_id, product_id, device_type)

        # Validate and assign multimeter-specific settings
        self.channels = self._validate_channels(channels)
        self.resolution = self._validate_parameter(resolution, float, "resolution")
        self.max_voltage = self._validate_parameter(max_voltage, float, "max_voltage")
        self.configuration = DMMConf(**configuration)
        self.max_resistance = self._validate_parameter(max_resistance, float, "max_resistance")
        self.max_current = self._validate_parameter(max_current, float, "max_current")
        self.max_capacitance = self._validate_parameter(max_capacitance, float, "max_capacitance")
        self.max_frequency = self._validate_parameter(max_frequency, float, "max_frequency")

    @staticmethod
    def _validate_channels(channels):
        if not isinstance(channels, list) or not all(isinstance(ch, int) for ch in channels):
            raise ValueError("channels must be a list of integers")
        return channels

    def __repr__(self):
        return f"MultimeterConfig(manufacturer={self.manufacturer}, model={self.model}, vendor_id={self.vendor_id}, product_id={self.product_id}, device_type={self.device_type}, channels={self.channels}, resolution={self.resolution}, max_voltage={self.max_voltage}, max_resistance={self.max_resistance}, max_current={self.max_current}, max_capacitance={self.max_capacitance}, max_frequency={self.max_frequency})"


class DMMConf:
    def __init__(self, current, voltage, resolution):
        self.current = SelectionConfig(current)
        self.voltage = SelectionConfig(voltage)
        self.resolution = SelectionConfig(resolution)