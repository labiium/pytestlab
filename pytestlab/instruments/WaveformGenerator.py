from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import WaveformGeneratorConfig
import numpy as np
import re
from dataclasses import dataclass

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

# Mapping dictionary for built-in waveform extra parameters.
# For each waveform type (normalized to uppercase) the supported extra parameters
# are mapped to lambdas that generate the proper SCPI command.
WAVEFORM_PARAM_COMMANDS = {
    "PULSE": {
        "duty_cycle": lambda ch, value: f"SOUR{ch}:FUNC:PULSe:DCYCle {value}",
        "edge_time": lambda ch, value: f"SOUR{ch}:FUNC:PULSe:TRANsition:LEADing {value}",
        "transition_both": lambda ch, value: f"SOUR{ch}:FUNC:PULSe:TRANsition:BOTH {value}",
        "transition_lead": lambda ch, value: f"SOUR{ch}:FUNC:PULSe:TRANsition:LEADing {value}",
        "transition_trail": lambda ch, value: f"SOUR{ch}:FUNC:PULSe:TRANsition:TRAiling {value}",
        "period": lambda ch, value: f"SOUR{ch}:FUNC:PULSe:PERiod {value}"
    },
    "SQUARE": {
        "duty_cycle": lambda ch, value: f"SOUR{ch}:FUNC:SQUare:DCYCle {value}",
        "period": lambda ch, value: f"SOUR{ch}:FUNC:SQUare:PERiod {value}"
    },
    "RAMP": {
        "symmetry": lambda ch, value: f"SOUR{ch}:FUNC:RAMP:SYMMetry {value}"
    },
    "TRIANGLE": {
        "symmetry": lambda ch, value: f"SOUR{ch}:FUNC:RAMP:SYMMetry {value}"
    },
    "SINUSOID": {
        # Sinusoid does not have additional parameters.
    }
}

class WaveformGenerator(Instrument):
    """
    Provides full control over waveform creation (arbitrary and built-in)
    including all SCPI-based operations like setting frequency, amplitude, offset,
    phase, symmetry, voltage limits, impedance, output polarity, voltage unit and coupling,
    as well as waveform-specific extra parameters (duty cycle, edge/transition times, etc.).
    """
    def __init__(self, config=None, debug_mode=False):
        """
        Initialize a WaveformGenerator instance with a device profile.

        Args:
            config (WaveformGeneratorConfig): Configuration object with device-specific settings.
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
        Validates that the requested waveform type is supported by the instrument.

        Args:
            waveform_type (str): The waveform type to validate.

        Raises:
            ValueError: If the waveform type is not supported.
        """
        self.config.waveforms.built_in[waveform_type]
    def set_arbitrary_waveform(self, channel, waveform, scale=True, name="pytestlabArb"):
        """
        Sets an arbitrary waveform for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            waveform (numpy.ndarray or list): Waveform data, expected within [-32768, 32767].
            scale (bool): If True, scale waveform data to fully use the DAC range.
            name (str): Identifier for the arbitrary waveform (alphanumeric, underscores allowed).

        Raises:
            ValueError: If the waveform data is out of range or the name is invalid.
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
            
        if not re.match("^[a-zA-Z0-9_]*$", name):
            raise ValueError(f"Name must be alphanumeric (underscores allowed): {name}")
            
        formatted_data = ', '.join(map(str, waveform_np.astype(int)))
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:DATA:VOL:CLEAR")
        self._send_command(f"SOUR{validated_channel}:DATA:ARB:DAC {name}, {formatted_data}")
        self._send_command(f"SOUR{validated_channel}:FUNC:ARB \"{name}\"")
        self._send_command(f"SOUR{validated_channel}:FUNC:ARB:FILT NORM")
        self._send_command(f"SOUR{validated_channel}:FUNC ARB")
        
        self._log(f"Arbitrary waveform '{name}' set on channel {validated_channel}")
    
    def set_waveform(self, channel, waveform_type, **kwargs):
        """
        Sets a built-in waveform for the specified channel and applies extra parameters
        (e.g., duty cycle, edge times, symmetry) if supported.

        Args:
            channel (int or str): The channel to configure.
            waveform_type (str): The built-in waveform type to set.

        Keyword Args:
            duty_cycle (float): For pulse/square waveforms, percentage (0-100).
            edge_time (float): For pulse waveform, applied as transition leading time. 
            transition_both (float): For pulse waveform, set both leading and trailing transition times.
            transition_lead (float): For pulse waveform, set leading transition time.
            transition_trail (float): For pulse waveform, set trailing transition time.
            period (float): For pulse or square waveform, period in seconds.
            symmetry (float): For ramp/triangle waveforms, symmetry percentage (0-100).

        Raises:
            ValueError: If the waveform type or any parameter is invalid or not supported.
        """
        print(waveform_type)
        self._validate_waveform(waveform_type)
        validated_channel = self.config.channels.validate(channel)
        built_in_cmd = self.config.waveforms.built_in[waveform_type]
        self._send_command(f"SOUR{validated_channel}:FUNC {built_in_cmd}")
        self._log(f"Waveform set to {waveform_type} on channel {validated_channel}")

        # Normalize waveform type to uppercase for mapping lookup.
        waveform_key = waveform_type.upper()
        if kwargs:
            param_cmds = WAVEFORM_PARAM_COMMANDS.get(waveform_key)
            if not param_cmds:
                raise ValueError(f"No extra parameters are supported for waveform type '{waveform_type}'")
            for param, value in kwargs.items():
                if param in param_cmds:
                    if param == "duty_cycle" and not (0 <= value <= 100):
                        raise ValueError("Duty cycle must be between 0 and 100")
                    if param == "symmetry" and not (0 <= value <= 100):
                        raise ValueError("Symmetry must be between 0 and 100")
                    cmd = param_cmds[param](validated_channel, value)
                    self._send_command(cmd)
                    self._log(f"{param.replace('_', ' ').capitalize()} set to {value} on channel {validated_channel}")
                else:
                    raise ValueError(f"Parameter '{param}' is not supported for waveform type '{waveform_type}'")
    
    def set_frequency(self, channel, frequency):
        """
        Sets the frequency for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            frequency (float): Frequency in Hz.

        Raises:
            ValueError: If frequency is out of the valid range.
        """
        validated_channel = self.config.channels.validate(channel)
        freq_value = self.config.channels[validated_channel].frequency.in_range(frequency)
        self._send_command(f"SOUR{validated_channel}:FREQ {freq_value}")
        self._log(f"Frequency set to {frequency} Hz on channel {validated_channel}")
    
    def set_amplitude(self, channel, amplitude):
        """
        Sets the amplitude for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            amplitude (float): Amplitude value.
        """
        validated_channel = self.config.channels.validate(channel)
        amp_value = self.config.channels[validated_channel].amplitude.in_range(amplitude)
        self._send_command(f"SOUR{validated_channel}:VOLTage:AMPL {amp_value}")
        self._log(f"Amplitude set to {amplitude} on channel {validated_channel}")
    
    def set_offset(self, channel, offset):
        """
        Sets the DC offset for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            offset (float): DC offset value.
        """
        validated_channel = self.config.channels.validate(channel)
        offset_value = self.config.channels[validated_channel].dc_offset.in_range(offset)
        self._send_command(f"SOUR{validated_channel}:VOLTage:OFFSet {offset_value}")
        self._log(f"Offset set to {offset} on channel {validated_channel}")
    
    def set_phase(self, channel, phase):
        """
        Sets the phase offset for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            phase (float): Phase offset in degrees.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:PHASe {phase}")
        self._log(f"Phase set to {phase} degrees on channel {validated_channel}")
    
    def set_phase_reference(self, channel):
        """
        Resets the phase reference for the specified channel.

        Args:
            channel (int or str): The channel to configure.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:PHASe:REFerence")
        self._log(f"Phase reference reset on channel {validated_channel}")
    
    def synchronize_phase(self):
        """
        Synchronizes the phase of all channels to a common reference.
        """
        self._send_command("PHASe:SYNChronize")
        self._log("Phases synchronized across channels")
    
    def set_symmetry(self, channel, symmetry):
        """
        Sets the symmetry (ramp symmetry) for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            symmetry (float): Symmetry percentage (0-100).
        """
        if not (0 <= symmetry <= 100):
            raise ValueError("Symmetry must be between 0 and 100")
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:FUNC:RAMP:SYMMetry {symmetry}")
        self._log(f"Symmetry set to {symmetry}% on channel {validated_channel}")
    
    def set_phase_unlock_error_state(self, state):
        """
        Configures whether an error should be generated if the instrument loses phase lock.
        (Only applicable to channel 1.)

        Args:
            state (bool): True to enable error generation, False to disable.
        """
        cmd_state = "ON" if state else "OFF"
        self._send_command(f"SOUR1:PHASe:UNLock:ERRor:STATe {cmd_state}")
        self._log(f"Phase unlock error state set to {cmd_state} on channel 1")
    
    def set_impedance(self, channel, impedance):
        """
        Sets the load impedance for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            impedance (float or str): Impedance value in ohms or special strings (e.g., 'INFinity').
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"OUTPut{validated_channel}:LOAD {impedance}")
        self._log(f"Impedance set to {impedance} on channel {validated_channel}")
    
    def get_impedance(self, channel):
        """
        Retrieves the load impedance for the specified channel.

        Args:
            channel (int or str): The channel to query.

        Returns:
            float or str: The current load impedance.
        """
        validated_channel = self.config.channels.validate(channel)
        response = self._query(f"OUTPut{validated_channel}:LOAD?")
        self._log(f"Impedance on channel {validated_channel}: {response}")
        try:
            return float(response)
        except ValueError:
            return response.strip()
    
    def set_voltage_limits(self, channel, low, high):
        """
        Sets the voltage limits for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            low (float): Lower voltage limit.
            high (float): Upper voltage limit.
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
            channel (int or str): The channel to configure.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:VOLT:LIMit:STATe OFF")
        self._log(f"Voltage limits disabled on channel {validated_channel}")
    
    def enable_voltage_limits(self, channel):
        """
        Enables the voltage limits for the specified channel.

        Args:
            channel (int or str): The channel to configure.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"SOUR{validated_channel}:VOLT:LIMit:STATe ON")
        self._log(f"Voltage limits enabled on channel {validated_channel}")
    
    def output(self, channel, state):
        """
        Sets the output state (ON/OFF) for the specified channel.

        Args:
            channel (int or str): The channel to control.
            state (bool): True to turn ON, False to turn OFF.
        """
        validated_channel = self.config.channels.validate(channel)
        self._send_command(f"OUTPut{validated_channel} {'ON' if state else 'OFF'}")
        self._log(f"Output for channel {validated_channel} set to {'ON' if state else 'OFF'}")
    
    def set_output_polarity(self, channel, polarity):
        """
        Sets the output polarity for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            polarity (str): 'normal' or 'inverted'.

        Raises:
            ValueError: If polarity is not valid.
        """
        validated_channel = self.config.channels.validate(channel)
        if polarity.lower() in ["normal", "norm"]:
            polarity_cmd = "NORMal"
        elif polarity.lower() in ["inverted", "invert"]:
            polarity_cmd = "INVerted"
        else:
            raise ValueError("Polarity must be 'normal' or 'inverted'")
        self._send_command(f"OUTPut{validated_channel}:POLarity {polarity_cmd}")
        self._log(f"Output polarity set to {polarity_cmd} on channel {validated_channel}")
    
    def set_voltage_unit(self, channel, unit):
        """
        Sets the voltage unit for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            unit (str): Voltage unit, one of 'VPP', 'VRMS', 'DBM'.

        Raises:
            ValueError: If an invalid unit is provided.
        """
        validated_channel = self.config.channels.validate(channel)
        unit = unit.upper()
        if unit not in {"VPP", "VRMS", "DBM"}:
            raise ValueError("Voltage unit must be one of: 'VPP', 'VRMS', 'DBM'")
        self._send_command(f"SOUR{validated_channel}:VOLTage:UNIT {unit}")
        self._log(f"Voltage unit set to {unit} on channel {validated_channel}")
    
    def set_voltage_coupling(self, channel, state):
        """
        Sets the voltage coupling state for the specified channel.

        Args:
            channel (int or str): The channel to configure.
            state (bool): True to enable coupling, False to disable.
        """
        validated_channel = self.config.channels.validate(channel)
        coupling_state = "ON" if state else "OFF"
        self._send_command(f"SOUR{validated_channel}:VOLTage:COUPle:STATe {coupling_state}")
        self._log(f"Voltage coupling set to {coupling_state} on channel {validated_channel}")
    
    def get_config(self, channel):
        """
        Retrieves the current configuration of the specified channel.

        Args:
            channel (int or str): The channel to query.

        Returns:
            WaveformConfigResult: An object containing current settings (waveform, frequency,
                                  amplitude, offset, phase, symmetry, and output state).
        """
        validated_channel = self.config.channels.validate(channel)
        waveform = self._query(f"SOUR{validated_channel}:FUNCtion?").strip()
        frequency = float(self._query(f"SOUR{validated_channel}:FREQ?").strip())
        amplitude = float(self._query(f"SOUR{validated_channel}:VOLTage:AMPL?").strip())
        offset = float(self._query(f"SOUR{validated_channel}:VOLTage:OFFSet?").strip())
        
        try:
            phase_resp = self._query(f"SOUR{validated_channel}:PHASe?")
            phase = float(phase_resp)
        except Exception:
            phase = None
        
        if waveform.upper().startswith("RAMP") or waveform.upper().startswith("TRI"):
            try:
                sym_resp = self._query(f"SOUR{validated_channel}:FUNC:RAMP:SYMMetry?")
                symmetry = float(sym_resp.strip())
            except Exception:
                symmetry = None
        else:
            symmetry = None
        
        output_state = self._query(f"OUTPut{validated_channel}?").strip().upper() == "ON"
        
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
