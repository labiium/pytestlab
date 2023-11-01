import time
from pytestlab.instruments.instrument import SCPIInstrument
from pytestlab.MeasurementDatabase import MeasurementResult, Preamble
from pytestlab.errors import SCPICommunicationError, SCPIValueError, InstrumentNotFoundError, IntrumentConfigurationError
import numpy as np
class Oscilloscope(SCPIInstrument):
    """
    Provides an interface for controlling and acquiring data from an oscilloscope using SCPI commands.

    This class inherits from SCPIInstrument and implements specific methods to interact with 
    oscilloscope features such as voltage measurement and timebase scaling.

    Attributes:
    visa_resource (str): The VISA resource string used for identifying the connected oscilloscope.
    profile (dict): Information about the instrument model.
    """
    def __init__(self, visa_resource=None, profile=None, debug_mode=False):
        """
        Initialize the Oscilloscope class with the given VISA resource and profile information.
        
        Args:
        visa_resource (str): The VISA resource string used for identifying the connected oscilloscope.
        profile (dict): Information about the instrument model.
        """
        super().__init__(visa_resource=visa_resource, profile=profile, debug_mode=debug_mode)
        if not self.profile:
            raise ValueError("Oscilloscope profile not found.")

    def _read_preamble(self):
        """Reads the preamble from the oscilloscope.

        :param inst: The instrument object from pyscpi or pyvisa
        :param debug: Print debug messages
        :return: A Preamble object

        """

        peram = self._query(':WAVeform:PREamble?')
        peram = peram.split(',')
        self._log(peram)

        pre = Preamble(peram[0], peram[1], int(peram[2]), float(peram[4]), float(
            peram[5]), float(peram[6]), float(peram[7]), float(peram[8]), float(peram[9]))

        return pre

    def _read_wave_data(self, channel: int, points: int) -> np.ndarray:

        self._query('*OPC?')
        self._send_command(f':WAVeform:SOURce CHANnel{channel}')
        self._query('*OPC?')
        self._log('Reading channel ' + str(channel))

        self._send_command(':WAVeform:FORMat BYTE')
        self._send_command(':WAVeform:POINts:MODE MAXimum')

        self._log('Reading points')

        if points > 0:
            self._send_command(f':WAVeform:POINts {points}')
        else:
            self._send_command(':WAVeform:POINts MAXimum')

        self._query('*OPC?')

        self._log('Reading data')

        self._send_command(':WAVeform:DATA?')
        data = self._read_to_np()

        return data
    def auto_scale(self):
        """
        Auto scale the oscilloscope display.
        
        This method sends an SCPI command to the oscilloscope to auto scale the display.
        
        Example:
        >>> auto_scale()
        """
        self._send_command(":AUToscale")

    def set_time_axis(self, scale: float, position: float) -> None:
        """
        Sets the time axis of the Oscilloscope. (x-axis)

        :param scale: scale The scale of the axis in seconds 
        :param position: The position of the time axis from the trigger in seconds
        """
    
        self._send_command(f':TIMebase:SCALe {scale}')
        self._send_command(f':TIMebase:POSition {position}')
        self._query('*OPC?')
    
    def set_channel_axis(self, channel: int, scale: float, offset: float) -> None:
        """
        Sets the channel axis of the oscilloscope. (y-axis)

        :param channel: The channel to set
        :param scale: The scale of the channel axis in volts
        :param offset: The offset of the channel in volts
        """
        self._send_command(f':CHANnel{channel}:SCALe {scale}')
        self._send_command(f':CHANnel{channel}:OFFSet {offset}')
        self._query('*OPC?')
        
    def measure_voltage_peak_to_peak(self, channel):
        """
        Measure the peak-to-peak voltage for a specified channel.
        
        This method sends an SCPI query to the oscilloscope to measure the peak-to-peak voltage 
        of the given channel, then encapsulates the measurement result into a MeasurementResult object.
        
        Args:
        channel (int/str): The channel identifier, which can be an integer or string depending on the oscilloscope model.
        
        Returns:
        MeasurementResult: An object containing the peak-to-peak voltage measurement for the specified channel.
        
        Example:
        >>> measure_voltage_peak_to_peak("CH1")
        <MeasurementResult object at 0x7f1ec2a4f510>
        """
        self._check_valid_channel(channel)


        measurement_result = MeasurementResult(self.profile["model"], "V", "peak to peak voltage")

        response = self._query(f"MEAS:VPP? CHAN{channel}")
        measurement_result.add(response)
        return measurement_result

    def measure_rms_voltage(self, channel: int) -> MeasurementResult:
        """
        Measure the root-mean-square (RMS) voltage for a specified channel.
        
        This method sends an SCPI query to the oscilloscope to measure the RMS voltage 
        of the given channel, then encapsulates the measurement result into a MeasurementResult object.
        
        Args:
        channel (int/str): The channel identifier, which can be an integer or string depending on the oscilloscope model.
        
        Returns:
        MeasurementResult: An object containing the RMS voltage measurement for the specified channel.
        
        Example:
        >>> measure_rms_voltage("CH1")
        <MeasurementResult object at 0x7f1ec2a4f590>
        """
        #Error Handling
        self._check_valid_channel(channel)


        measurement_result = MeasurementResult(self.profile["model"], "V", "rms voltage")
        response = self._query(f"MEAS:VRMS? CHAN{channel}")
        measurement_result.add(response)
        return measurement_result

    def read_channels(self, channels, points=1, runAfter=True, time_interval=None):
        if time_interval is not None:
        # convert time interval to points
            self._send_command(f":TIMebase:MAIN:RANGe {time_interval}")
            self._send_command(f"ACQuire:SRATe {1/time_interval}")
            points = int(time_interval * 1e9)
        # check channels exist
        self. _log(points)
        self._log("starting")
        for channel in channels:
            self._check_valid_channel(channel)
        
        command = ""
        # set up channels
        for channel in channels:
            channel = command + f"CHANnel{channel}, "

        command = command[:-2]

        self._send_command(f"DIGitize {command}")
        self._send_command(f':WAVeform:SOURce CHANnel{channels[0]}')

        # set up points
        pream = self._read_preamble()

        all_data = np.empty([pream.points, len(channels)])

        for i in range(len(channels)):
            # _log(f'Reading channel {channels[i]}', debug)
            data = self._read_wave_data(channels[i], points)
            if len(data) != (pream.points):
                print('ERROR: points mismatch, please investigate')
            all_data[:, i] = data

        voltCH = (all_data-pream.yref) * pream.yinc + pream.yorg

        time = (np.arange(0, pream.points, 1)-pream.xref) * pream.xinc + pream.xorg

        if runAfter:
            self._send_command(":RUN")

        # error = self.profile["channels"][channels[0]]["error"]
        return time, voltCH
       
    def set_timebase_scale(self, scale):
        """
        Set the timebase scale of the oscilloscope.
        
        This method sends an SCPI command to adjust the timebase scale on the oscilloscope display.
        
        Args:
        scale (float): The timebase scale in seconds per division.
        
        Example:
        >>> set_timebase_scale(0.002)
        """
        self._send_command(f"TIM:SCAL {scale}")

    def get_timebase_scale(self):
        """
        Retrieve the current timebase scale setting from the oscilloscope.
        
        This method sends an SCPI query to get the current timebase scale and encapsulates 
        the result into a MeasurementResult object.
        
        Returns:
        MeasurementResult: An object containing the current timebase scale setting.
        
        Example:
        >>> get_timebase_scale()
        <MeasurementResult object at 0x7f1ec2a4f650>
        """
        measurement_result = MeasurementResult(self.profile["model"], "s", "timebase scale")
        response = self._query("TIM:SCAL?")

        measurement_result.add(response)
        return measurement_result

    def set_acquisition_time(self, time):
        """
        
        """
        # Set the total time for acquisition
        self._send_command(f":TIMebase:MAIN:RANGe {time}")

    def set_sample_rate(self, rate):
        """
        
        """
        rate = rate.upper()
        valid_values = ["MAX", "AUTO"]
        if rate not in valid_values:
            raise ValueError(f"Invalid Valid: supported = {valid_values}")
        # Set the sample rate for acquisition
        self._send_command(f"ACQuire:SRATe {rate}")

    def set_bandwidth_limit(self, channel, bandwidth):
        """
        
        """
        self._check_valid_channel(channel)
        # Limit the bandwidth to a specified frequency to reduce noise
        self._send_command(f"CHANnel{channel}:BANDwidth {bandwidth}")

    # def set_filtering(self, channel, filter_type, frequency):
    #     self._check_valid_channel(channel)
    #     # Configure a filter on the channel to isolate the desired frequency components
    #     if self.profile["channels"][channel]["filtering"] != "available":
    #         raise ValueError(f"Filtering is not available on Channel {channel}.")
        
    #     if channel not in self.profile["channels"]:
    #         raise ValueError(f"Invalid channel {channel}. Supported channels: {self.profile['channels']}")

    #     self._send_command(f"CHANnel{channel}:FILTer:{filter_type} {frequency}")

    def set_trigger(self, channel, trigger_level):
        """
        
        """
        self._check_valid_channel(channel)
        # Set the trigger level for the specified channel
        self._send_command(f"TRIGger:LEVel CHANnel{channel},{trigger_level}")

    # def set_trigger_mode(self, mode):
    #     """
        
    #     """
    #     if mode not in self.profile["trigger_modes"]:
    #         raise ValueError(f"Invalid trigger mode {mode}. Supported trigger modes: {self.profile['trigger_modes']}")
    #     # Set the trigger mode to either edge or pulse
    #     self._send_command(f"TRIGger:MODE {mode}")

    def set_trigger_source(self, channel):
        """
        
        """
        self._check_valid_channel(channel)
        # Set the trigger source to the specified channel
        self._send_command(f"TRIGger:SOURce CHANnel{channel}")

    # def set_trigger_edge_slope(self, slope):
    #     """"""
    #     # Set the edge slope to either rising or falling
    #     self._send_command(f"TRIGger:EDGE:SLOPe {slope}")

    # def set_trigger_pulse_polarity(self, polarity):
    #     # Set the pulse polarity to either positive or negative
    #     self._send_command(f"TRIGger:PULSe:POLarity {polarity}")

    # def set_trigger_pulse_width(self, width):
    #     # Set the pulse width to the specified value
    #     self._send_command(f"TRIGger:PULSe:WIDth {width}")

    # def set_trigger_pulse_delay(self, delay):
    #     # Set the pulse delay to the specified value
    #     self._send_command(f"TRIGger:PULSe:DELay {delay}")

    # def set_trigger_pulse_transition(self, transition):
    #     # Set the pulse transition to either positive or negative
    #     self._send_command(f"TRIGger:PULSe:TRANsition {transition}")

    # def set_trigger_pulse_condition(self, condition):
    #     # Set the pulse condition to either width or delay
    #     self._send_command(f"TRIGger:PULSe:CONdition {condition}")

    def wave_gen(self, state: bool):
        """
        Enable or disable the waveform generator of the oscilloscope.

        This method sends an SCPI command to enable or disable the function generator in the oscilloscope.
        
        Args:
        state (str): The desired state ('ON' or 'OFF') for the waveform generator.
        
        Raises:
        ValueError: If the oscilloscope model does not have a waveform generator or if the state is not supported.
        
        Example:
        >>> set_wave_gen('ON')
        """
        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        # if state not in self.profile["function_generator"]:
        #     raise ValueError(f"Invalid state {state}. Supported states: {self.profile['function_generator']}")
        
        self._send_command(f"WGEN:OUTP {'ON' if state else 'OFF'}")

    def set_wave_gen_func(self, state):
        """
        Set the waveform function for the oscilloscope's waveform generator.

        This method sends an SCPI command to change the function (e.g., 'SINE', 'SQUARE') of the waveform generator.
        
        Args:
        state (str): The desired function ('SINE', 'SQUARE', etc.) for the waveform generator.

        Raises:
        ValueError: If the oscilloscope model does not have a waveform generator or if the state is not supported.

        Example:
        >>> set_wave_gen_func('SINE')
        """
        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        if state not in self.profile["function_generator"]["waveform_types"]:
            raise ValueError(f"Invalid state {state}. Supported states: {self.profile['function_generator']['waveform_types']}")
        
        self._send_command(f"WGEN:FUNC {state}")

    def set_wave_gen_freq(self, freq):
        """
        Set the frequency for the waveform generator.

        This method sends an SCPI command to set the frequency of the waveform generator.
        
        Args:
        freq (float): The desired frequency for the waveform generator in Hz.

        Raises:
        ValueError: If the oscilloscope model does not have a waveform generator or if the frequency is out of range.

        Example:
        >>> set_wave_gen_freq(1000.0)
        """
        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        if freq < self.profile["function_generator"]["frequency"]["min"] or freq > self.profile["function_generator"]["frequency"]["max"]:
            raise ValueError(f"Invalid frequency {freq}. Supported frequency range: {self.profile['function_generator']['frequency']['min']} to {self.profile['function_generator']['frequency']['max']}")

        self._send_command(f"WGEN:FREQ {freq}")

    def set_wave_gen_amp(self, amp):
        """
        Set the amplitude for the waveform generator.

        This method sends an SCPI command to set the amplitude of the waveform generator.
        
        Args:
        amp (float): The desired amplitude for the waveform generator in volts.

        Raises:
        ValueError: If the oscilloscope model does not have a waveform generator or if the amplitude is out of range.

        Example:
        >>> set_wave_gen_amp(1.0)
        """
        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        if amp < self.profile["function_generator"]["amplitude"]["min"] or amp > self.profile["function_generator"]["amplitude"]["max"]:
            raise ValueError(f"Invalid amplitude {amp}. Supported amplitude range: {self.profile['function_generator']['amplitude']['min']} to {self.profile['function_generator']['amplitude']['max']}")

        self._send_command(f"WGEN:VOLT {amp}")

    def set_wave_gen_offset(self, offset):
        """
        Set the voltage offset for the waveform generator.

        This method sends an SCPI command to set the voltage offset of the waveform generator.
        
        Args:
        offset (float): The desired voltage offset for the waveform generator in volts.

        Raises:
        ValueError: If the oscilloscope model does not have a waveform generator or if the offset is out of range.

        Example:
        >>> set_wave_gen_offset(0.1)
        """
        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        if offset < self.profile["function_generator"]["offset"]["min"] or offset > self.profile["function_generator"]["offset"]["max"]:
            raise ValueError(f"Invalid offset {offset}. Supported offset range: {self.profile['function_generator']['offset']['min']} to {self.profile['function_generator']['offset']['max']}")
        
        self._send_command(f"WGEN:VOLT:OFFSet {offset}")

    def set_wgen_sin(self, amp: float, offset: float, freq: float) -> None:
        """Sets the waveform generator to a sine wave. (Only available on specific models)

        :param amp: The amplitude of the sine wave in volts
        :param offset: The offset of the sine wave in volts
        :param freq: The frequency of the sine wave in Hz. The frequency can be adjusted from 100 mHz to 20 MHz.
        """
        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        if offset < self.profile["function_generator"]["offset"]["min"] or offset > self.profile["function_generator"]["offset"]["max"]:
            raise ValueError(f"Invalid offset {offset}. Supported offset range: {self.profile['function_generator']['offset']['min']} to {self.profile['function_generator']['offset']['max']}")
        if amp < self.profile["function_generator"]["amplitude"]["min"] or amp > self.profile["function_generator"]["amplitude"]["max"]:
            raise ValueError(f"Invalid amplitude {amp}. Supported amplitude range: {self.profile['function_generator']['amplitude']['min']} to {self.profile['function_generator']['amplitude']['max']}")
        if freq < self.profile["function_generator"]["frequency"]["min"] or freq > self.profile["function_generator"]["frequency"]["max"]:
            raise ValueError(f"Invalid frequency {freq}. Supported frequency range: {self.profile['function_generator']['frequency']['min']} to {self.profile['function_generator']['frequency']['max']}")

        self._send_command('WGEN:FUNCtion SINusoid')
        self._send_command(f':WGEN:VOLTage {amp}')
        self._send_command(f':WGEN:VOLTage:OFFSet {offset}')
        self._send_command(f':WGEN:FREQuency {freq}')


    def set_wgen_square(self, v0: float, v1: float, freq: float, dutyCycle: int) -> None:
        """Sets the waveform generator to a square wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the square wave in Hz. The frequency can be adjusted from 100 mHz to 10 MHz.
        :param dutyCycle: The duty cycle can be adjusted from 1% to 99% up to 500 kHz. At higher frequencies, the adjustment range narrows so as not to allow pulse widths less than 20 ns.
        """

        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        
        self._send_command('WGEN:FUNCtion SQUare')
        self._send_command(f':WGEN:VOLTage:LOW {v0}')
        self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        self._send_command(f':WGEN:FREQuency {freq}')
        self._send_command(f':WGEN:FUNCtion:SQUare:DCYCle {dutyCycle}')


    def set_wgen_ramp(self, v0: float, v1: float, freq: float, symmetry: int) -> None:
        """Sets the waveform generator to a ramp wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the ramp wave in Hz. The frequency can be adjusted from 100 mHz to 100 kHz.
        :param symmetry: Symmetry represents the amount of time per cycle that the ramp waveform is rising and can be adjusted from 0% to 100%.
        """

        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        
        self._send_command('WGEN:FUNCtion RAMP')
        self._send_command(f':WGEN:VOLTage:LOW {v0}')
        self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        self._send_command(f':WGEN:FREQuency {freq}')
        self._send_command(f':WGEN:FUNCtion:RAMP:SYMMetry {symmetry}')


    def set_wgen_pulse(self, v0: float, v1: float, period: float, pulseWidth: float) -> None:
        """Sets the waveform generator to a pulse wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param period: The period of the pulse wave in seconds. The period can be adjusted from 10 ns to 10 s.
        :param pulseWidth: The pulse width can be adjusted from 20 ns to the period minus 20 ns.
        """

        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")

        self._send_command('WGEN:FUNCtion PULSe')
        self._send_command(f':WGEN:VOLTage:LOW {v0}')
        self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        self._send_command(f':WGEN:PERiod {period}')
        self._send_command(f':WGEN:FUNCtion:PULSe:WIDTh {pulseWidth}')


    def set_wgen_dc(self, offset: float) -> None:
        """Sets the waveform generator to a DC wave. (Only available on specific models)

        :param offset: The offset of the DC wave in volts
        """

        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        if offset < self.profile["function_generator"]["offset"]["min"] or offset > self.profile["function_generator"]["offset"]["max"]:
            raise ValueError(f"Invalid offset {offset}. Supported offset range: {self.profile['function_generator']['offset']['min']} to {self.profile['function_generator']['offset']['max']}")
        
        self._send_command('WGEN:FUNCtion DC')
        self._send_command(f':WGEN:VOLTage:OFFSet {offset}')


    def set_wgen_noise(self, v0: float, v1: float, offset: float) -> None:
        """Sets the waveform generator to a noise wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param offset: The offset of the noise wave in volts
        """
        
        if "function_generator" not in self.profile:
            raise ValueError(f"Waveform generator is not available on this oscilloscope.")
        
        self._send_command('WGEN:FUNCtion NOISe')
        self._send_command(f':WGEN:VOLTage:LOW {v0}')
        self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        self._send_command(f':WGEN:VOLTage:OFFSet {offset}')


class DigitalOscilloscopeWithJitter(Oscilloscope):

    def __init__(self, visa_resource, profile):
        super().__init__(visa_resource, profile)

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
        