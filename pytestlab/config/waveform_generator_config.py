from .instrument_config import InstrumentConfig
from .config import Config, RangeConfig, SelectionConfig
from ..errors import InstrumentParameterError

class WaveformGeneratorConfig(InstrumentConfig):
    def __init__(self, manufacturer, model, vendor_id, product_id, device_type, channels, max_frequency, waveforms, modulation_types, amplitude, dc_offset, accuracy, interfaces, remote_control):
        super().__init__(manufacturer, model, vendor_id, product_id, device_type)

        # Validate and assign AWG-specific settings
        self.channels = ChannelsConfig(**channels)
        self.max_frequency = self._validate_parameter(max_frequency, float, "max_frequency")
        self.waveforms = WaveformsConfig(**waveforms)
        self.modulation_types = SelectionConfig(modulation_types)
        self.amplitude = RangeConfig(**amplitude)
        self.dc_offset = RangeConfig(**dc_offset)
        self.accuracy = AccuracyConfig(**accuracy)
        self.interfaces = SelectionConfig(interfaces)
        self.remote_control = SelectionConfig(remote_control)

class ChannelsConfig(Config):
    # Similar to the OscilloscopeConfig ChannelsConfig
    def __init__(self, **kwargs):
        self.channels = {}
        for channel, channel_config in kwargs.items():
            self.channels[int(channel)] = channel_config
            self.channels[int(channel)] = channel_config
    def __getitem__(self, channel):
        """
        Validate and return the channel if it is within the range.

        Args:
            channel (int): The channel to validate.

        Returns:
            ChannelConfig: The validated channel.

        Raises:
            InstrumentParameterError: If the channel is not valid.
        """
        if not isinstance(channel, int):
            raise ValueError(f"channel must be an integer. Received: {channel}")

        if channel not in self.channels:
            raise InstrumentParameterError(f"Invalid channel: {channel}. Valid channels: {list(self.channels.keys())}")
        # returns the channel
        return channel
    
    def to_json(self):
        return self.channels
class WaveformsConfig(Config):
    def __init__(self, standard, built_in, arbitrary):
        self.standard = SelectionConfig(standard)
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
