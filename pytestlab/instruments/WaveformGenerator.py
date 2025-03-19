from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import WaveformGeneratorConfig
import numpy as np
import re
from dataclasses import dataclass

# @dataclass
# class WaveformPhase:
#     """
#     Data class to store the phase offset of a waveform.
#     """
#     minimum: float
#     maximum: float
#     default: float

@dataclass
class WaveformConfigResult:
    """
    Data class to store the waveform configuration of a channel.
    """
    channel: int
    waveform: str
    frequency: float
    amplitude: float
    offset: float
    phase: float = None
    symmetry: float = None
    output_state: bool = None


class WaveformGenerator(Instrument):
    def __init__(self, config=None, debug_mode=False):
        """
        Initialize a WaveformGenerator instance with a device profile.

        Args:
            config (WaveformGeneratorConfig): A configuration object containing device-specific settings.
            debug_mode (bool): If True, enable debug logging.
        """
        if not isinstance(config, WaveformGeneratorConfig):
            raise InstrumentConfigurationError("WaveformGeneratorConfig required to initialize WaveformGenerator")
        super().__init__(config=config, debug_mode=debug_mode)
        
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
            waveform (numpy.ndarray or list): The arbitrary waveform data. Values are expected to be within [-32768, 32767].
            scale (bool): If True, the waveform is linearly scaled to fill the available DAC range.
            name (str): The identifier for the arbitrary waveform. Must be alphanumeric (underscores allowed).

        Raises:
            ValueError: If the waveform exceeds the allowable range or if the name is not alphanumeric.
        """
        self._log(f"Setting arbitrary waveform for channel {channel}")
        
        max_val = 32767
        min_val = -32768
        waveform_np = np.array(waveform)
        if scale:
            scaled_data = (waveform_np - np.min(waveform_np)) / (np.max(waveform_np) - np.min(waveform_np))
            waveform_np = scaled_data * (max_val - min_val) + min_val
        else:
            if np.max(waveform_np) > max_val or np.min(waveform_np) < min_val:
                self._log(f"Waveform exceeds range: {min_val} to {max_val}")
                raise ValueError(f"Waveform exceeds range: {min_val} to {max_val}")
            
        # check that the name is alphanumeric (underscores allowed)
        if not re.match("^[a-zA-Z0-9_]*$", name):
            raise ValueError(f"Name must be alphanumeric: {name}")
            
        formatted_data = ', '.join(map(str, waveform_np.astype(int)))
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:DATA:VOL:CLEAR")
        self._send_command(f"SOUR{validated_channel}:DATA:ARB:DAC {name}, {formatted_data}")
        self._send_command(f"SOUR{validated_channel}:FUNC:ARB \"{name}\"")
        self._send_command(f"SOUR{validated_channel}:FUNC:ARB:FILT NORM")
        self._send_command(f"SOUR{validated_channel}:FUNC ARB")
        
        self._log(f"Waveform set to Arbitrary wave '{name}' on channel {validated_channel}")  

    def set_waveform(self, channel, waveform_type, **kwargs):
        """
        Sets the waveform type for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the waveform.
            waveform_type (str): The type of waveform to set.

        
        Keyword Args:
            duty_cycle (float): The duty cycle for square and pulse waveforms (0 to 100). Only available for square and pulse waveforms.

        Raises:
            ValueError: If the waveform type is not supported.
        """
        self._validate_waveform(waveform_type)
        validated_channel = self.config.channels.validate(channel)
        built_in_cmd = self.config.waveforms.built_in[waveform_type]
        self._send_command(f"SOUR{validated_channel}:FUNC {built_in_cmd}")
        self._log(f"Waveform set to {waveform_type} on channel {validated_channel}")

        if "duty_cycle" in kwargs:
            duty_cycle = kwargs.pop("duty_cycle")
            if waveform_type in ["SQUare", "PULSe"]:
                # Validate duty cycle (assumed percentage: 0 to 100)
                if not (0 <= duty_cycle <= 100):
                    raise ValueError("Duty cycle must be between 0 and 100")
                # Here we assume the command syntax for duty cycle is as follows.
                self._send_command(f"SOUR{validated_channel}:FUNC:{waveform_type}:DCYC {duty_cycle}")
                self._log(f"Duty cycle set to {duty_cycle}% on channel {validated_channel}")
            else:
                raise ValueError(f"Duty cycle setting is not applicable for waveform type '{waveform_type}'")

        
        if kwargs:
            raise ValueError(f"Unsupported keyword arguments: {kwargs.keys()}")

    def set_frequency(self, channel, frequency):
        """
        Sets the frequency for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the frequency.
            frequency (float): The frequency in Hz.

        Raises:
            ValueError: If the frequency is out of range.
        """
        validated_channel = self.config.channels.validate(channel)
        freq_value = self.config.channels[validated_channel].frequency.in_range(frequency)
        self._send_command(f"SOUR{validated_channel}:FREQ {freq_value}")
        self._log(f"Frequency set to {frequency} Hz on channel {validated_channel}")

    def set_amplitude(self, channel, amplitude):
        """
        Sets the amplitude for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the amplitude.
            amplitude (float): The amplitude value.
        """
        validated_channel = self.config.channels.validate(channel)
        amp_value = self.config.channels[validated_channel].amplitude.in_range(amplitude)
        self._send_command(f"SOUR{validated_channel}:VOLTage:AMPL {amp_value}")
        self._log(f"Amplitude set to {amplitude} on channel {validated_channel}")

    def set_offset(self, channel, offset):
        """
        Sets the DC offset for the specified channel after validation.

        Args:
            channel (int or str): The channel for which to set the offset.
            offset (float): The DC offset value.
        """
        validated_channel = self.config.channels.validate(channel)
        offset_value = self.config.channels[validated_channel].dc_offset.in_range(offset)
        self._send_command(f"SOUR{validated_channel}:VOLTage:OFFSet {offset_value}")
        self._log(f"Offset set to {offset} on channel {validated_channel}")

    def output(self, channel, state):
        """
        Sets the output state for the specified channel.

        Args:
            channel (int or str): The channel to control.
            state (bool): True to turn output ON; False for OFF.
        """
        self._send_command(f"OUTP{channel} {'ON' if state else 'OFF'}")
        self._log(f"Output for channel {channel} set to {'ON' if state else 'OFF'}")

    # --- New functionality for impedance and voltage limits ---

    def set_impedance(self, channel, impedance):
        """
        Sets the expected load impedance for the specified channel. This informs the instrument
        about the connected termination so that it can scale amplitude readings appropriately.

        Args:
            channel (int or str): The channel for which to set the impedance.
            impedance (float or str): The impedance value in ohms, or one of the special strings 
                                      (e.g. "INFinity", "MINimum", "MAXimum", "DEFault").

        Example:
            set_impedance(1, 50)   # Sets channel 1 impedance to 50 ohms.
            set_impedance(2, "INF") # Sets channel 2 to high impedance mode.
        """
        validated_channel = self.config.channels.validate(channel)
        # You might add further validation here using self.config if available.
        self._send_command(f"OUTP{validated_channel}:LOAD {impedance}")
        self._log(f"Impedance set to {impedance} on channel {validated_channel}")

    def get_impedance(self, channel):
        """
        Queries the currently configured load impedance for the specified channel.

        Args:
            channel (int or str): The channel to query.

        Returns:
            float or str: The load impedance as a float (if numeric) or as a string (e.g. 'INF').
        """
        validated_channel = self.config.channels.validate(channel)
        response = self._query(f"OUTP{validated_channel}:LOAD?")
        self._log(f"Impedance on channel {validated_channel} is {response}")
        try:
            return float(response)
        except ValueError:
            return response.strip()

    def set_voltage_limits(self, channel, low, high):
        """
        Sets the voltage limits for the specified channel to protect the connected device.

        This method sends separate commands to set the low and high voltage limits and then enables the limits.
        The instrument will clip amplitude/offset settings that exceed these limits and may generate a settings
        conflict error if the current settings violate the limits.

        Args:
            channel (int or str): The channel for which to set voltage limits.
            low (float): The lower voltage limit.
            high (float): The upper voltage limit.

        Example:
            set_voltage_limits(1, -2.5, 2.5)
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:VOLT:LIMit:LOW {low}")
        self._send_command(f"SOUR{validated_channel}:VOLT:LIMit:HIGH {high}")
        self._send_command(f"SOUR{validated_channel}:VOLT:LIMit:STATe ON")
        self._log(f"Voltage limits set to Low={low}, High={high} on channel {validated_channel}")

    def disable_voltage_limits(self, channel):
        """
        Disables the voltage limits for the specified channel.

        Args:
            channel (int or str): The channel for which to disable voltage limits.

        Example:
            disable_voltage_limits(1)
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:VOLT:LIMit:STATe OFF")
        self._log(f"Voltage limits disabled on channel {validated_channel}")

    def enable_voltage_limits(self, channel):
        """
        Enables the voltage limits for the specified channel.

        Args:
            channel (int or str): The channel for which to enable voltage limits.

        Example:
            enable_voltage_limits(1)
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:VOLT:LIMit:STATe ON")
        self._log(f"Voltage limits enabled on channel {validated_channel}")

    # --- Existing phase and symmetry methods ---

    def set_phase(self, channel, phase):
        """
        Sets the phase offset for the specified channel.

        Args:
            channel (int or str): The channel to set phase for.
            phase (float): The desired phase offset (in degrees, max 360, min -360).

        Example:
            set_phase(1, 90)  # sets channel 1 phase offset to 90 degrees.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:PHASe {phase}")
        self._log(f"Phase set to {phase} on channel {validated_channel}")

    def set_phase_reference(self, channel):
        """
        Resets the phase reference for the specified channel without changing its output.

        Args:
            channel (int or str): The channel to reset phase reference for.

        Example:
            set_phase_reference(1)  # Resets channel 1's phase reference.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:PHASe:REFerence")
        self._log(f"Phase reference reset on channel {validated_channel}")

    def synchronize_phase(self):
        """
        Synchronizes the phase of all internal channels (or modulating sources) to a common reference.
        This is useful in two-channel instruments where the relative phase is important.

        Example:
            synchronize_phase()
        """
        self._send_command("PHASe:SYNChronize")
        self._log("Phases synchronized across channels")

    def set_symmetry(self, channel, symmetry):
        """
        Sets the ramp (or triangular) waveform symmetry percentage for the specified channel.
        Note: This command is applicable only if the current waveform is of type 'RAMP' (or a variant such as TRIangle).

        Args:
            channel (int or str): The channel to set symmetry for.
            symmetry (float): The symmetry percentage (typically 0 to 100, where 50% yields a triangle wave if used with a ramp).

        Example:
            set_symmetry(1, 50)  # Sets channel 1 to 50% symmetry.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:FUNC:RAMP:SYMMetry {symmetry}")
        self._log(f"Ramp symmetry set to {symmetry}% on channel {validated_channel}")

    def set_phase_unlock_error_state(self, state):
        """
        Configures whether an error should be generated if the instrument loses phase lock.
        This command is only applicable to channel 1.

        Args:
            state (bool): True to enable error generation on phase unlock; False to disable.

        Example:
            set_phase_unlock_error_state(True)
        """
        cmd_state = "ON" if state else "OFF"
        self._send_command(f"SOUR1:PHASe:UNLock:ERRor:STATe {cmd_state}")
        self._log(f"Phase unlock error state set to {cmd_state} on channel 1")

    def get_config(self, channel):
        """
        Retrieves the current waveform configuration for the specified channel.
        
        This method queries the instrument for key parameters such as:
          - Waveform type (function)
          - Frequency (Hz)
          - Amplitude
          - Offset (DC)
          - Phase offset (if applicable)
          - Ramp symmetry (if applicable)
          - Output state (ON/OFF)
        
        Args:
            channel (int or str): The channel to query.
            
        Returns:
            WaveformConfigResult: An object containing the current configuration for that channel.
        """
        validated_channel = self.config.channels.validate(channel)
        # Query basic settings using the _query helper
        waveform = self._query(f"SOUR{validated_channel}:FUNCtion?").strip()
        frequency = float(self._query(f"SOUR{validated_channel}:FREQ?").strip())
        amplitude = float(self._query(f"SOUR{validated_channel}:VOLTage:AMPL?").strip())
        offset = float(self._query(f"SOUR{validated_channel}:VOLTage:OFFSet?").strip())
        
        # Some waveforms (e.g. RAMP/ TRIangle) support a phase query
        try:
            phase_resp = self._query(f"SOUR{validated_channel}:PHASe?")
            phase = float(phase_resp)
        except Exception:
            phase = None
        
        # For ramp-type waveforms, try to get symmetry info.
        if waveform.upper().startswith("RAMP") or waveform.upper().startswith("TRI"):
            try:
                sym_resp = self._query(f"SOUR{validated_channel}:FUNC:RAMP:SYMMetry?")
                symmetry = float(sym_resp.strip())
            except Exception:
                symmetry = None
        else:
            symmetry = None

        # Query the output state.
        output_state = self._query(f"OUTP{validated_channel}?").strip().upper() == "ON"
        
        config_obj = WaveformConfigResult(
            channel=validated_channel,
            waveform=waveform,
            frequency=frequency,
            amplitude=amplitude,
            offset=offset,
            phase=phase,
            symmetry=symmetry,
            output_state=output_state
        )
        return config_obj
