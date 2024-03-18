from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import WaveformGeneratorConfig
import numpy as np
import re

class WaveformGenerator(Instrument):
    def __init__pd(self, visa_resource=None, config=None, debug_mode=False):
        """
        Initialize a WaveformGenerator instance with a device profile.

        Args:
            profile (dict): A dictionary containing device profile information.

        """
        if not isinstance(config, WaveformGenerator):
            raise InstrumentConfigurationError("WaveformGeneratorConfig required to initialize WaveformGenerator")
        super().__init__(visa_resource=visa_resource, config=config, debug_mode=debug_mode)
        
    @classmethod
    def from_config(cls, config: WaveformGeneratorConfig, debug_mode=False):
        return cls(config=WaveformGeneratorConfig(**config), debug_mode=debug_mode)
    
    def _validate_waveform(self, waveform_type):
        """
        Validate if the waveform type is supported by the device.

        Args:
            waveform_type (str): The type of waveform to validate.

        Raises:
            ValueError: If the waveform type is not supported.

        """
        # TODO: MERGE STANDARD AND BUILT-IN WAVEFORMS
        pass

    def _validate_frequency(self, frequency):
        """
        Validate if the frequency is within the device's supported range.

        Args:
            frequency (float): The frequency to validate.

        Raises:
            ValueError: If the frequency is out of range.

        """
        # TODO: add frequency range to config
        max_frequency = self.config.max_frequency
        if frequency > max_frequency:
            raise ValueError(f"Frequency out of range. Max supported frequency: {max_frequency}")

    def set_arbitrary_waveform(self, channel, waveform, scale=True, name="pytestlabArb"):
        """
        Sets the arbitrary waveform for the specified channel.

        Args:
            channel (int or str): The channel for which to set the waveform.
            waveform (list): The arbitrary waveform to set. Max and min values are 32767 to -32768, respectively.
            scale (bool): Whether to scale the waveform to the max and min values.
            name (str): The name of the arbitrary waveform, default is "pytestlabArb".
        """
        self._log(f"Setting arbitrary waveform for channel {channel}")
        
        max_val = 32767
        min_val = -32768
        if scale:
            scaled_data = (waveform - np.min(waveform)) / (np.max(waveform) - np.min(waveform))
            waveform = scaled_data * (max_val - min_val) + min_val

        else:
            if np.max(waveform) > max_val or np.min(waveform) < min_val:
                self._log(f"Waveform exceeds range: {min_val} to {max_val}")
                raise ValueError(f"Waveform exceeds range: {min_val} to {max_val}")
            
        # check name is only alphanumeric
        if not re.match("^[a-zA-Z0-9_]*$", name):
            raise ValueError(f"Name must be alphanumeric: {name}")
            
        formatted_data = ', '.join(map(str, waveform.astype(int)))
        # waveform_np = np.normalize(waveform)
        self._send_command(f"SOUR{channel}:DATA:VOL:CLEAR")
        self._send_command(f"SOUR{channel}:DATA:ARB:DAC {name}, {formatted_data}")
        self._send_command(f"SOUR{channel}:FUNC:ARB \"{name}\"")
        self._send_command(f"SOUR{channel}:FUNC:ARB:FILT NORM")
        self._send_command(f"SOUR{channel}:FUNC ARB")
        
        self._log(f"Waveform set to Arbitrary wave {name}")  

    def set_waveform(self, channel, waveform_type):
        """
        Sets the waveform type for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the waveform.
            waveform_type (str): The type of waveform to set.

        """ 
        # TODO: merge standard and built-in waveforms
        self._validate_waveform(waveform_type)
        self._send_command(f"SOUR{self.config.channels[channel]}:FUNC {waveform_type.upper()}")
        self._log(f"Waveform set to {waveform_type}")

    def set_frequency(self, channel, frequency):
        """
        Sets the frequency for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the frequency.
            frequency (float): The frequency to set.

        """
        self._send_command(f"SOUR{self.config.channels[channel]}:FREQ {frequency}")
        self._log(f"Frequency set to {frequency} Hz")

    def set_amplitude(self, channel, amplitude):
        """
        Sets the amplitude for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the amplitude.
            amplitude (float): The amplitude to set.

        """
        self.config.amplitude.in_range(amplitude)
        self._send_command(f"SOUR{channel}:VOLTage:AMPL {amplitude}")

    def set_offset(self, channel, offset):
        """
        Sets the offset for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the offset.
            offset (float): The offset to set.

        """
        self.config.dc_offset.in_range(offset)
        self._send_command(f"SOUR{channel}:VOLTage:OFFSet {offset}")

    def output(self, channel, state):
        """
        Sets the output state for the specified channel. By default, the output is turned off.

        Args:
            channel (int or str): The channel for which to set the output state.
            state (str): The state to set.

        """
        self._send_command(f"OUTP{channel} {'ON' if state else 'OFF'}")