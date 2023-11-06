from pytestlab.instruments.instrument import SCPIInstrument
from pytestlab.errors import SCPIConnectionError, SCPICommunicationError, SCPIValueError, InstrumentNotFoundError, IntrumentConfigurationError
import numpy as np

class WaveformGenerator(SCPIInstrument):
    def __init__(self, profile):
        """
        Initialize a WaveformGenerator instance with a device profile.

        Args:
            profile (dict): A dictionary containing device profile information.

        """
        super().__init__()
        self.profile = profile

    def _validate_waveform(self, waveform_type):
        """
        Validate if the waveform type is supported by the device.

        Args:
            waveform_type (str): The type of waveform to validate.

        Raises:
            ValueError: If the waveform type is not supported.

        """
        standard_waveforms = [w.upper() for w in self.profile.get('waveforms', {}).get('standard', [])]
        if waveform_type.upper() not in standard_waveforms:
            raise ValueError(f"Invalid waveform type: {waveform_type}. Supported types: {standard_waveforms}")

    def _validate_frequency(self, frequency):
        """
        Validate if the frequency is within the device's supported range.

        Args:
            frequency (float): The frequency to validate.

        Raises:
            ValueError: If the frequency is out of range.

        """
        max_frequency = self.profile.get('max_frequency')
        if frequency > max_frequency:
            raise ValueError(f"Frequency out of range. Max supported frequency: {max_frequency}")

    def _validate_amplitude(self, amplitude):
        """
        Validate if the amplitude is within the device's supported range.

        Args:
            amplitude (float): The amplitude to validate.

        Raises:
            ValueError: If the amplitude is out of range.

        """
        min_amplitude = self.profile.get('amplitude', {}).get('min', 0)
        max_amplitude = self.profile.get('amplitude', {}).get('max', float('inf'))
        if not min_amplitude <= amplitude <= max_amplitude:
            raise ValueError(f"Amplitude out of range. Supported range: {min_amplitude} to {max_amplitude}")

    def _validate_offset(self, offset):
        """
        Validate if the offset is within the device's supported range.

        Args:
            offset (float): The offset to validate.

        Raises:
            ValueError: If the offset is out of range.

        """
        min_offset = self.profile.get('dc_offset', {}).get('min', float('-inf'))
        max_offset = self.profile.get('dc_offset', {}).get('max', float('inf'))
        if not min_offset <= offset <= max_offset:
            raise ValueError(f"Offset out of range. Supported range: {min_offset} to {max_offset}")

    def set_arbitrary_waveform(self, channel, waveform, scale=True):
        """
        Sets the arbitrary waveform for the specified channel.

        Args:
            channel (int or str): The channel for which to set the waveform.
            waveform (list): The arbitrary waveform to set.

        """
        waveform_np = np.array(waveform)
        awg_max_voltage = self.profile["amplitude"]["max"]
        awg_min_voltage = self.profile["amplitude"]["min"]

        max_length = self.profile["waveforms"]["arbitrary"]["max_length"]
        if scale:
            waveform_normalized = (waveform - np.min(waveform)) / (np.max(waveform) - np.min(waveform))
            waveform_scaled = waveform_normalized * (awg_max_voltage - awg_min_voltage) + awg_min_voltage
            waveform_np = np.array(waveform_scaled)
            if len(waveform_np) > max_length:
                # squash into max_length by approximating
                waveform_np = waveform_np[::int(len(waveform_np) / max_length)] # TODO: improve this approximation
        else:
            if len(waveform_np) > max_length:
                raise ValueError(f"Waveform length exceeds maximum length: {max_length}")
            if np.max(waveform_np) > awg_max_voltage or np.min(waveform_np) < awg_min_voltage:
                raise ValueError(f"Waveform exceeds amplitude range: {awg_min_voltage} to {awg_max_voltage}")

        binary_waveform = waveform_np.tobytes()

        self._send_command(f"SOURCE{channel}:DATA:VOL:CLEAR")  # Clear the volatile memory
        self._send_command(f"SOURCE{channel}:FUNCTION ARBITRAR")  # Set the source to arbitrary waveform
        self._send_command(f"SOURCE{channel}:DATA:ARB:DAC {binary_waveform}, (@1)")

    def set_waveform(self, channel, waveform_type):
        """
        Sets the waveform type for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the waveform.
            waveform_type (str): The type of waveform to set.

        """
        self._validate_waveform(waveform_type)
        self._send_command(f"SOUR{channel}:FUNC {waveform_type.upper()}")

    def set_frequency(self, channel, frequency):
        """
        Sets the frequency for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the frequency.
            frequency (float): The frequency to set.

        """
        self._validate_frequency(frequency)
        self._send_command(f"SOUR{channel}:FREQ {frequency}")

    def set_amplitude(self, channel, amplitude):
        """
        Sets the amplitude for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the amplitude.
            amplitude (float): The amplitude to set.

        """
        self._validate_amplitude(amplitude)
        self._send_command(f"SOUR{channel}:AMPL {amplitude}")

    def set_offset(self, channel, offset):
        """
        Sets the offset for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the offset.
            offset (float): The offset to set.

        """
        self._validate_offset(offset)
        self._send_command(f"SOUR{channel}:OFFS {offset}")

# Similar approach can be taken for PatternGenerator
class PatternGenerator(SCPIInstrument):
    def __init__(self, profile):
        """
        Initialize a PatternGenerator instance with a device profile.

        Args:
            profile (dict): A dictionary containing device profile information.

        """
        super().__init__()
        self.profile = profile

    def _validate_pattern(self, pattern):
        """
        Validate if the pattern is supported by the device.

        Args:
            pattern (str): The type of pattern to validate.

        Raises:
            ValueError: If the pattern is not supported.

        """
        standard_patterns = [p.upper() for p in self.profile.get('waveforms', {}).get('standard', [])]
        if pattern.upper() not in standard_patterns:
            raise ValueError(f"Invalid pattern: {pattern}. Supported types: {standard_patterns}")

    def set_pattern(self, channel, pattern):
        """
        Sets the pattern for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the pattern.
            pattern (str): The type of pattern to set.

        """
        self._validate_pattern(pattern)
        self._send_command(f"SOUR{channel}:FUNC {pattern.upper()}")
