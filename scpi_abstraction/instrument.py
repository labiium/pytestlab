import pyvisa
from scpi_abstraction.errors import SCPIConnectionError, SCPICommunicationError

class SCPIInstrument:
    def __init__(self, visa_resource):
        self.visa_resource = visa_resource
        self._connect()

    def _connect(self):
        try:
            self.instrument = pyvisa.ResourceManager().open_resource(self.visa_resource)
        except pyvisa.Error as e:
            raise SCPIConnectionError(f"Failed to connect to the instrument: {str(e)}")

    def _send_command(self, command):
        try:
            self.instrument.write(command)
        except pyvisa.Error as e:
            raise SCPICommunicationError(f"Failed to send command: {str(e)}")

    def _query(self, query):
        try:
            return self.instrument.query(query)
        except pyvisa.Error as e:
            raise SCPICommunicationError(f"Failed to query instrument: {str(e)}")

    def close(self):
        self.instrument.close()

    def reset(self):
        self._send_command("*RST")

    def set_channel_voltage(self, channel, voltage):
        self._send_command(f"CHAN{channel}:VOLT {voltage}")

    def get_channel_voltage(self, channel):
        response = self._query(f"CHAN{channel}:VOLT?")
        return float(response)

    def measure_frequency(self, channel):
        response = self._query(f"MEAS:FREQ? CHAN{channel}")
        return float(response)

