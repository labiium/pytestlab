from .instrument_config import InstrumentConfig
from .config import Config, RangeConfig, SelectionConfig, ChannelsConfig
from ..errors import InstrumentParameterError

class WaveformGeneratorConfig(InstrumentConfig):
    def __init__(self, manufacturer, model, device_type, channels, waveforms):
        super().__init__(manufacturer, model, device_type)

        # Validate and assign AWG-specific settings
        self.channels = ChannelsConfig(*channels, ChannelConfig=AWGChannelConfig)
        self.waveforms = WaveformsConfig(**waveforms)


class AWGChannelConfig(Config):
    def __init__(self, description, frequency, amplitude, dc_offset, accuracy):
        self.description = description
        self.amplitude = RangeConfig(**amplitude)
        self.frequency = RangeConfig(**frequency)
        self.dc_offset = RangeConfig(**dc_offset)
        self.accuracy = AccuracyConfig(**accuracy)

class WaveformsConfig(Config):
    def __init__(self, built_in, arbitrary):
        self.built_in = SelectionConfig(built_in)
        self.arbitrary = ArbitraryConfig(**arbitrary)

class ArbitraryConfig(Config):
    def __init__(self, memory, max_length, sampling_rate, resolution):
        self.memory = self._validate_parameter(memory, float, "memory")
        self.max_length = self._validate_parameter(max_length, float, "max_length")
        self.sampling_rate = RangeConfig(**sampling_rate)
        self.resolution = self._validate_parameter(resolution, int, "resolution")

class AccuracyConfig(Config):
    def __init__(self, amplitude, frequency):
        self.amplitude = self._validate_parameter(amplitude, float, "amplitude")
        self.frequency = self._validate_parameter(frequency, float, "frequency")
