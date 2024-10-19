from .instrument_config import InstrumentConfig
from .config import Config, RangeConfig, SelectionConfig
from ..errors import InstrumentParameterError

class PowerSupplyConfig(InstrumentConfig):
    def __init__(self, manufacturer, model, device_type, serial_number, channels, total_power, line_regulation, load_regulation):
        # Initialize the base class with basic instrument configuration
        super().__init__(manufacturer, model, device_type, serial_number)

        # Validate and assign power supply specific settings
        self.channels = PSChannelsConfig(*channels)
        self.total_power = self._validate_parameter(total_power, float, "total_power")
        self.line_regulation = self._validate_parameter(line_regulation, float, "line_regulation")
        self.load_regulation = self._validate_parameter(load_regulation, float, "load_regulation")
        # self.programming_accuracy = AccuracyConfig(**programming_accuracy)
        # self.readback_accuracy = AccuracyConfig(**readback_accuracy)
        # self.interfaces = SelectionConfig(interfaces)
        # self.remote_control = SelectionConfig(remote_control)

class PSChannelsConfig(Config):
    def __init__(self, *args):
        self.outputs = {}
        # print(args)
        for i, data in enumerate(args):
            self.outputs[i] = OutputConfig(**data)

    def __getitem__(self, output):
        if not isinstance(output, int):
            raise ValueError(f"Output must be an integer. Received: {output}")

        if output not in self.outputs:
            raise InstrumentParameterError(f"Invalid output: {output}. Valid outputs: {list(self.outputs.keys())}")

        return self.outputs[output]
    
    def __repr__(self):
        return f"OutputsConfig({self.outputs})"
    
    def to_json(self):
        # export dict and call to_json on each output
        return {output: output_config.to_json() for output, output_config in self.outputs.items()}

class OutputConfig(Config):
    def __init__(self, description, voltage, current, accuracy):
        # pri
        self.description = description
        self.voltage = RangeConfig(**voltage)
        self.current = RangeConfig(**current)
        self.accuracy = AccuracyConfig(**accuracy)
    def __repr__(self):
        return f"OutputConfig(voltage={self.voltage}, current={self.current})"

class AccuracyConfig(Config):
    def __init__(self, voltage, current):
        self.voltage =self._validate_parameter(voltage, float, "voltage")
        self.current = self._validate_parameter(current, float, "current")

    def __repr__(self):
        return f"AccuracyConfig(voltage={self.voltage}, current={self.current})"

