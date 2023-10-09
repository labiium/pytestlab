import time
import warnings

from scpi_abstraction.instrument import SCPIInstrument
from scpi_abstraction.utilities import MeasurementResult
from scpi_abstraction.errors import SCPICommunicationError, SCPIValueError, InstrumentNotFoundError, IntrumentConfigurationError
class Oscilloscope(SCPIInstrument):
    def __init__(self, visa_resource, profile):
        super().__init__(visa_resource)
        self.profile = profile

    def __init__(self, visa_resource):
        super().__init__(visa_resource)
        warnings.warn("Instrument profile not provided. Your commands will not be validated. Using default profile.", UserWarning)

    def _check_channel_range(self, channel, value, profile):
        if channel not in self.profile["channels"]:
            raise ValueError(f"Invalid channel {channel}. Supported channels: {self.profile['channels']}")

        channel_limits = self.profile["channels"][channel]
        if value < channel_limits["min"] or value > channel_limits["max"]:
            raise ValueError(f"Invalid value for {profile} on Channel {channel}. Supported range: {channel_limits['min']} to {channel_limits['max']}")

    def measure_voltage_peak_to_peak(self, channel):
        measurement_result = MeasurementResult(self.profile["model"], "V", "peak to peak voltage")
        self._check_channel_range(channel, channel, "channel")
        response = self._query(f"MEAS:VPP? CHAN{channel}")
        measurement_result.add_measurement(response)
        return measurement_result

    def measure_rms_voltage(self, channel):
        measurement_result = MeasurementResult(self.profile["model"], "V", "rms voltage")
        self._check_channel_range(channel, channel, "channel")
        response = self._query(f"MEAS:VRMS? CHAN{channel}")
        measurement_result.add_measurement(response)
        return measurement_result

    def set_timebase_scale(self, scale):
        self._check_channel_range(1, scale, "timebase scale")
        self._send_command(f"TIM:SCAL {scale}")

    def get_timebase_scale(self):
        measurement_result = MeasurementResult(self.profile["model"], "s", "timebase scale")
        response = self._query("TIM:SCAL?")

        measurement_result.add_measurement(response)
        return measurement_result

    # get voltage over time data
    def get_voltage_stream(self, channel, time_interval, duration):

        measurement_result = MeasurementResult(self.profile["model"], "V", "voltage over time")
        for _ in range(duration):
            response = self._query(f"CHAN{channel}:DATA?")
            
            measurement_result.add_measurement(response)
            time.sleep(time_interval)


        return measurement_result

    def set_acquisition_time(self, time):
        # Set the total time for acquisition
        self._send_command(f"ACQuire:TIME {time}")

    def set_sample_rate(self, rate):
        # Set the sample rate for acquisition
        self._send_command(f"ACQuire:SRATe {rate}")

    def set_bandwidth_limit(self, channel, bandwidth):
        # Limit the bandwidth to a specified frequency to reduce noise
        self._send_command(f"CHANnel{channel}:BANDwidth {bandwidth}")

    def set_filtering(self, channel, filter_type, frequency):
        # Configure a filter on the channel to isolate the desired frequency components
        self._send_command(f"CHANnel{channel}:FILTer:{filter_type} {frequency}")

    def set_trigger(self, channel, trigger_level):
        # Set the trigger level for the specified channel
        self._send_command(f"TRIGger:LEVel CHANnel{channel},{trigger_level}")

    def set_trigger_mode(self, mode):
        # Set the trigger mode to either edge or pulse
        self._send_command(f"TRIGger:MODE {mode}")

    def set_trigger_source(self, channel):
        # Set the trigger source to the specified channel
        self._send_command(f"TRIGger:SOURce CHANnel{channel}")

    def set_trigger_edge_slope(self, slope):
        # Set the edge slope to either rising or falling
        self._send_command(f"TRIGger:EDGE:SLOPe {slope}")

    def set_trigger_pulse_polarity(self, polarity):
        # Set the pulse polarity to either positive or negative
        self._send_command(f"TRIGger:PULSe:POLarity {polarity}")

    def set_trigger_pulse_width(self, width):
        # Set the pulse width to the specified value
        self._send_command(f"TRIGger:PULSe:WIDth {width}")

    def set_trigger_pulse_delay(self, delay):
        # Set the pulse delay to the specified value
        self._send_command(f"TRIGger:PULSe:DELay {delay}")

    def set_trigger_pulse_transition(self, transition):
        # Set the pulse transition to either positive or negative
        self._send_command(f"TRIGger:PULSe:TRANsition {transition}")

    def set_trigger_pulse_condition(self, condition):
        # Set the pulse condition to either width or delay
        self._send_command(f"TRIGger:PULSe:CONdition {condition}")

    # Add more methods for other oscilloscope functionalities as needed
class DigitalOscilloscopeWithJitter(Oscilloscope):
    def __init__(self, visa_resource, profile):
        super().__init__(visa_resource)
        self.profile = profile

    def _available_jitter_measurements(self, jitter_type):
        if jitter_type not in self.profile["jitter_analysis"]["available_types"]:
            raise ValueError(f"Invalid jitter type {jitter_type}. Supported jitter types: {self.profile['jitter_analysis']}")

    def setup_rms_jitter_measurement(self, channel):
        self._available_jitter_measurements("rms")
        # Implement SCPI commands to set up the oscilloscope for jitter measurement
        self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
        self._send_command("MEASure:JITTer:MODE RMS")

    def setup_peak_to_peak_jitter_measurement(self, channel):
        self._available_jitter_measurements("peak_to_peak")
        # Implement SCPI commands to set up the oscilloscope for jitter measurement
        self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
        self._send_command("MEASure:JITTer:MODE PK2PK")

    def setup_period_jitter_measurement(self, channel):
        self._available_jitter_measurements("period")
        # Implement SCPI commands to set up the oscilloscope for jitter measurement
        self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
        self._send_command("MEASure:JITTer:MODE PERiod")

    def setup_cycle_to_cycle_jitter_measurement(self, channel):
        self._available_jitter_measurements("cycle_to_cycle")
        # Implement SCPI commands to set up the oscilloscope for jitter measurement
        self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
        self._send_command("MEASure:JITTer:MODE CCYCle")

    def configure_trigger(self, trigger_source, trigger_level):
        # Implement SCPI commands to configure trigger settings for jitter measurement
        self._send_command(f"TRIGger:SOURce CHANnel{trigger_source}")
        self._send_command(f"TRIGger:LEVel CHANnel{trigger_source},{trigger_level}")

    def acquire_jitter_data(self):
        # Implement SCPI commands to acquire jitter data from the oscilloscope
        self._send_command("ACQuire:STATE RUN")

    def analyze_jitter_data(self):
        measurement_result = MeasurementResult(self.profile["model"], "s", "jitter")
        jitter_value = self._query_command("MEASure:JITTer?")
        measurement_result.add_measurement(jitter_value)
        return measurement_result
    
    def perform_rms_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
        self.setup_rms_jitter_measurement(channel)
        self.configure_trigger(trigger_source, trigger_level)
        self.acquire_jitter_data()
        return self.analyze_jitter_data()
    
def perform_peak_to_peak_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
    """
    Perform a peak-to-peak jitter measurement on a specified channel with given trigger settings.
    
    This method sets up the measurement, configures the trigger, acquires the jitter data and 
    then analyzes the data to return a MeasurementResult object containing the results of 
    the jitter measurement.
    
    Args:
    channel (str/int): The identifier for the channel on which the measurement is to be performed.
                       This could be an integer representing the channel number or a string representing
                       the channel name, depending on the implementation.
    trigger_source (str/int): The identifier for the trigger source. This could be an integer or a 
                              string representing the source depending on the implementation.
    trigger_level (float): The trigger level for the measurement in volts. This value sets the voltage 
                           level at which the trigger event occurs.
    
    Returns:
    MeasurementResult: An object containing the results of the peak-to-peak jitter measurement.
    
    Raises:
    NotImplementedError: If any of the method calls within this function (e.g., setup_peak_to_peak_jitter_measurement, 
                         configure_trigger, acquire_jitter_data, analyze_jitter_data) are not implemented.
    MeasurementError: If there is an error during the measurement process.
    
    Example:
    >>> perform_peak_to_peak_jitter_measurement("CH1", "External", 0.5)
    <MeasurementResult object at 0x7f9bd8134f50>
    """
    self.setup_peak_to_peak_jitter_measurement(channel)
    self.configure_trigger(trigger_source, trigger_level)
    self.acquire_jitter_data()
    return self.analyze_jitter_data()

    
def perform_period_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
    self.setup_period_jitter_measurement(channel)
    self.configure_trigger(trigger_source, trigger_level)
    self.acquire_jitter_data()
    return self.analyze_jitter_data()

def perform_cycle_to_cycle_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
    self.setup_cycle_to_cycle_jitter_measurement(channel)
    self.configure_trigger(trigger_source, trigger_level)
    self.acquire_jitter_data()
    return self.analyze_jitter_data()
    