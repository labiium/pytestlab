from .instrument_config import InstrumentConfig
from .config import Config, RangeConfig, SelectionConfig, ChannelsConfig
from ..errors import InstrumentParameterError

class OscilloscopeConfig(InstrumentConfig):
    def __init__(self,
                 manufacturer,
                 model,
                 device_type,
                 serial_number,
                 trigger,
                 channels,
                 bandwidth,
                 sampling_rate,
                 memory,
                 waveform_update_rate,
                 fft,
                 function_generator,
                 franalysis=None):
        # Initialize the base class with basic instrument configuration
        super().__init__(manufacturer, model, device_type, serial_number)

        # Validate and assign oscilloscope-specific settings
        self.trigger = TriggerConfig(**trigger)
        self.channels = ChannelsConfig(*channels, ChannelConfig=OscilloscopeChannelConfig)
        self.bandwidth = self._validate_parameter(bandwidth, float, "bandwidth")
        self.sampling_rate = self._validate_parameter(sampling_rate, float, "sampling_rate")
        self.memory = self._validate_parameter(memory, float, "memory")
        self.waveform_update_rate = self._validate_parameter(waveform_update_rate, float, "waveform_update_rate")
        if fft:
            self.fft = FFTConfig(**fft)
        if function_generator:
            self.function_generator = FunctionGeneratorConfig(**function_generator)
        if franalysis:
            self.franalysis = FRanalysis(**franalysis)

class TimebaseConfig(Config):
    def __init__(self, range, horizontal_resolution):
        self.range = RangeConfig(**range)
        self.horizontal_resolution = horizontal_resolution

    def __repr__(self):
        return f"TimebaseConfig(range={self.range}, horizontal_resolution={self.horizontal_resolution})"

    
    def __contains__(self, channel):
        """
        Check if the channel is valid.

        Args:
            channel (int): The channel to validate.

        Returns:
            bool: True if the channel is valid, False otherwise.
        """
        return channel in self.channels
    
    def to_json(self):
        """
        Serialize instance to a JSON-compatible dictionary.

        Returns:
            dict: The serialized representation.
        """
        return {
            "channels": {channel: channel_config.to_json() for channel, channel_config in self.channels.items()}
        }

class OscilloscopeChannelConfig(Config):
    def __init__(self, description, channel_range, input_coupling, input_impedance, probe_attenuation, timebase):        
        self.description = self._validate_parameter(description, str, "description")
        self.channel_range = RangeConfig(**channel_range)
        self.input_coupling = SelectionConfig(input_coupling)
        self.input_impedance = self._validate_parameter(input_impedance, float, "input_impedance")
        self.probe_attenuation = SelectionConfig(probe_attenuation)
        self.timebase = TimebaseConfig(**timebase)

    def __repr__(self):
        return f"ChannelConfig(description={self.description}, channel_range={self.channel_range}, input_coupling={self.input_coupling}, input_impedance={self.input_impedance}, probe_attenuation={self.probe_attenuation}, timebase={self.timebase})"

class FFTConfig(Config):
    def __init__(self, window_types, units):
        self.window_types = SelectionConfig(window_types)
        self.units = SelectionConfig(units)

    def __repr__(self):
        return f"FFTConfig(window_types={self.window_types}, units={self.units})"

class TriggerConfig(Config):
    def __init__(self, types, modes, slopes):
        self.types = SelectionConfig(types)
        self.modes = SelectionConfig(modes)
        self.slopes = SelectionConfig(slopes)

    def __repr__(self):
        return f"TriggerConfig(modes={self.modes}, slopes={self.slopes})"


class FunctionGeneratorConfig(Config):
    def __init__(self, waveform_types, supported_states, offset, frequency, amplitude):
        self.waveform_types = SelectionConfig(waveform_types)
        self.supported_states = SelectionConfig(supported_states)
        self.offset = RangeConfig(**offset)
        self.frequency = RangeConfig(**frequency)
        self.amplitude = RangeConfig(**amplitude)

    def __repr__(self):
        return f"FunctionGeneratorConfig(waveform_types={self.waveform_types}, supported_states={self.supported_states}, offset={self.offset}, frequency={self.frequency}, amplitude={self.amplitude})"


class FRanalysis(Config):
    def __init__(self, sweep_points, load, trace, mode):
        self.sweep_points = RangeConfig(**sweep_points)
        self.load = SelectionConfig(load)
        self.trace = SelectionConfig(trace)
        self.mode = SelectionConfig(mode)

    def __repr__(self):
        return f"FRanalysis(frequency={self.frequency}, sweep_points={self.sweep_points}, load={self.load}, trace={self.trace}, mode={self.mode})"