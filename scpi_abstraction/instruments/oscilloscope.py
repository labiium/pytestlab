from scpi_abstraction.instrument import SCPIInstrument

class Oscilloscope(SCPIInstrument):
    def __init__(self, visa_resource, description):
        super().__init__(visa_resource)
        self.description = description

    def _check_channel_range(self, channel, value, description):
        if channel not in self.description["channels"]:
            raise ValueError(f"Invalid channel {channel}. Supported channels: {self.description['channels']}")

        channel_limits = self.description["channels"][channel]
        if value < channel_limits["min"] or value > channel_limits["max"]:
            raise ValueError(f"Invalid value for {description} on Channel {channel}. Supported range: {channel_limits['min']} to {channel_limits['max']}")

    def measure_voltage_peak_to_peak(self, channel):
        self._check_channel_range(channel, channel, "channel")
        response = self._query(f"MEAS:VPP? CHAN{channel}")
        return float(response)

    def measure_rms_voltage(self, channel):
        self._check_channel_range(channel, channel, "channel")
        response = self._query(f"MEAS:VRMS? CHAN{channel}")
        return float(response)

    def set_timebase_scale(self, scale):
        self._check_channel_range(1, scale, "timebase scale")
        self._send_command(f"TIM:SCAL {scale}")

    def get_timebase_scale(self):
        response = self._query("TIM:SCAL?")
        return float(response)

    # Add more methods for other oscilloscope functionalities as needed
class DigitalOscilloscopeWithJitter(SCPIInstrument):
    def __init__(self, visa_resource, description):
        super().__init__(visa_resource)
        self.description = description

    def setup_jitter_measurement(self, channel):
        # Implement SCPI commands to set up the oscilloscope for jitter measurement
        self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
        self._send_command("MEASure:JITTer:MODE RMS")

    def configure_trigger(self, trigger_source, trigger_level):
        # Implement SCPI commands to configure trigger settings for jitter measurement
        self._send_command(f"TRIGger:SOURce CHANnel{trigger_source}")
        self._send_command(f"TRIGger:LEVel CHANnel{trigger_source},{trigger_level}")

    def acquire_jitter_data(self):
        # Implement SCPI commands to acquire jitter data from the oscilloscope
        self._send_command("ACQuire:STATE RUN")

    def analyze_jitter_data(self):
        # Implement SCPI commands to analyze jitter data and calculate jitter metrics
        # For example, you might read and return the measured jitter values
        jitter_value = self._query_command("MEASure:JITTer?")
        return {"Jitter": float(jitter_value)}

