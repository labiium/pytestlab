from scpi_abstraction.instrument import SCPIInstrument, SCPIConnectionError, SCPICommunicationError

class DigitalPowerSupply(SCPIInstrument):
    def __init__(self, visa_resource, description):
        super().__init__(visa_resource)
        self.description = description

    def set_voltage(self, voltage, channel=1):
        self._check_channel_range(channel, voltage, "voltage")
        self._send_command(f"VOLTAGE{channel} {voltage}")

    def set_current(self, current, channel=1):
        self._check_channel_range(channel, current, "current")
        self._send_command(f"CURRENT{channel} {current}")

    def enable_output(self, channel=1):
        self._send_command(f"OUTPUT{channel} ON")

    def disable_output(self, channel=1):
        self._send_command(f"OUTPUT{channel} OFF")

    # Add more methods for other digital power supply functionalities as needed
