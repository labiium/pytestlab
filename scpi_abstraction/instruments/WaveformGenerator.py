from scpi_abstraction.instrument import SCPIInstrument

class WaveformGenerator(SCPIInstrument):
    def set_waveform(self, channel, waveform_type):
        """Sets the waveform type for the specified channel."""
        valid_waveforms = ['SINE', 'SQUARE', 'TRIANGLE', 'RAMP', 'NOISE']
        if waveform_type.upper() not in valid_waveforms:
            raise ValueError(f"Invalid waveform type: {waveform_type}. Must be one of {valid_waveforms}")
        self._send_command(f"SOUR{channel}:FUNC {waveform_type.upper()}")

    def set_frequency(self, channel, frequency):
        """Sets the frequency for the specified channel."""
        self._send_command(f"SOUR{channel}:FREQ {frequency}")

    def set_amplitude(self, channel, amplitude):
        """Sets the amplitude for the specified channel."""
        self._send_command(f"SOUR{channel}:AMPL {amplitude}")

    def set_offset(self, channel, offset):
        """Sets the offset for the specified channel."""
        self._send_command(f"SOUR{channel}:OFFS {offset}")

    def enable_output(self, channel):
        """Enables the output for the specified channel."""
        self._send_command(f"OUTP{channel} ON")

    def disable_output(self, channel):
        """Disables the output for the specified channel."""
        self._send_command(f"OUTP{channel} OFF")

class PatternGenerator(SCPIInstrument):
    def set_pattern(self, channel, pattern):
        """Sets the pattern for the specified channel."""
        valid_patterns = ['PRBS', 'USER']
        if pattern.upper() not in valid_patterns:
            raise ValueError(f"Invalid pattern: {pattern}. Must be one of {valid_patterns}")
        self._send_command(f"SOUR{channel}:FUNC {pattern.upper()}")