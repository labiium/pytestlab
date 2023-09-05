from scpi_abstraction.instrument import SCPIInstrument

class WaveformGenerator(SCPIInstrument):
    """
    A class representing a Waveform Generator that inherits from the SCPIInstrument class.

    Provides methods to set waveform characteristics like type, frequency, amplitude, and offset.
    """

    def set_waveform(self, channel, waveform_type):
        """
        Sets the waveform type for the specified channel.

        Args:
            channel (int or str): The channel for which to set the waveform.
            waveform_type (str): The type of waveform to set. Must be one of ['SINE', 'SQUARE', 'TRIANGLE', 'RAMP', 'NOISE'].

        Raises:
            ValueError: If an invalid waveform type is provided.
        """
        valid_waveforms = ['SINE', 'SQUARE', 'TRIANGLE', 'RAMP', 'NOISE']
        if waveform_type.upper() not in valid_waveforms:
            raise ValueError(f"Invalid waveform type: {waveform_type}. Must be one of {valid_waveforms}")
        self._send_command(f"SOUR{channel}:FUNC {waveform_type.upper()}")

    def set_frequency(self, channel, frequency):
        """
        Sets the frequency for the specified channel.

        Args:
            channel (int or str): The channel for which to set the frequency.
            frequency (float): The frequency value to set.
        """
        self._send_command(f"SOUR{channel}:FREQ {frequency}")

    def set_amplitude(self, channel, amplitude):
        """
        Sets the amplitude for the specified channel.

        Args:
            channel (int or str): The channel for which to set the amplitude.
            amplitude (float): The amplitude value to set.
        """
        self._send_command(f"SOUR{channel}:AMPL {amplitude}")

    def set_offset(self, channel, offset):
        """
        Sets the offset for the specified channel.

        Args:
            channel (int or str): The channel for which to set the offset.
            offset (float): The offset value to set.
        """
        self._send_command(f"SOUR{channel}:OFFS {offset}")

    def enable_output(self, channel):
        """
        Enables the output for the specified channel.

        Args:
            channel (int or str): The channel for which to enable the output.
        """
        self._send_command(f"OUTP{channel} ON")

    def disable_output(self, channel):
        """
        Disables the output for the specified channel.

        Args:
            channel (int or str): The channel for which to disable the output.
        """
        self._send_command(f"OUTP{channel} OFF")

class PatternGenerator(SCPIInstrument):
    """
    A class representing a Pattern Generator that inherits from the SCPIInstrument class.

    Provides methods to set pattern characteristics like type.
    """

    def set_pattern(self, channel, pattern):
        """
        Sets the pattern for the specified channel.

        Args:
            channel (int or str): The channel for which to set the pattern.
            pattern (str): The type of pattern to set. Must be one of ['PRBS', 'USER'].

        Raises:
            ValueError: If an invalid pattern is provided.
        """
        valid_patterns = ['PRBS', 'USER']
        if pattern.upper() not in valid_patterns:
            raise ValueError(f"Invalid pattern: {pattern}. Must be one of {valid_patterns}")
        self._send_command(f"SOUR{channel}:FUNC {pattern.upper()}")
