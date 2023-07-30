from scpi_abstraction.instrument import SCPIInstrument, SCPIConnectionError, SCPICommunicationError

class DigitalMultimeter(SCPIInstrument):
    def __init__(self, visa_resource, description):
        super().__init__(visa_resource)
        self.description = description

    def measure_voltage(self, channel=1):
        if channel not in self.description["voltage_channels"]:
            raise ValueError(f"Invalid voltage channel {channel}. Supported voltage channels: {self.description['voltage_channels']}")

        voltage = self._query(f"MEASURE:VOLTAGE:DC? (@{channel})")
        return float(voltage)

    def measure_current(self, channel=1):
        if channel not in self.description["current_channels"]:
            raise ValueError(f"Invalid current channel {channel}. Supported current channels: {self.description['current_channels']}")

        current = self._query(f"MEASURE:CURRENT:DC? (@{channel})")
        return float(current)

    # Add more methods for other digital multimeter functionalities as needed
