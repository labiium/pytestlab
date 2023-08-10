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

    def measure_resistance(self, channel=1):
        if channel not in self.description["resistance_channels"]:
            raise ValueError(f"Invalid resistance channel {channel}. Supported resistance channels: {self.description['resistance_channels']}")

        resistance = self._query(f"MEASURE:RESISTANCE? (@{channel})")
        return float(resistance)

    def measure_frequency(self, channel=1):
        if channel not in self.description["frequency_channels"]:
            raise ValueError(f"Invalid frequency channel {channel}. Supported frequency channels: {self.description['frequency_channels']}")

        frequency = self._query(f"MEASURE:FREQUENCY? (@{channel})")
        return float(frequency)

    def test_continuity(self, channel=1):
        if channel not in self.description["continuity_channels"]:
            raise ValueError(f"Invalid continuity channel {channel}. Supported continuity channels: {self.description['continuity_channels']}")

        continuity = self._query(f"TEST:CONTINUITY? (@{channel})")
        return bool(int(continuity)) # Assuming continuity returns 1 for True and 0 for False
