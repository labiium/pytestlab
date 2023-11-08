import time
from typing import List
from pytestlab.instruments.instrument import SCPIInstrument
from pytestlab.MeasurementDatabase import MeasurementResult, Preamble, MeasurementValue
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
        visa_resource (str): The VISA resource string used for identifying the connected oscilloscope. Optional if a profile is provided.
        profile (dict): Information about the instrument model.
        """
        super().__init__(visa_resource=visa_resource, profile=profile, debug_mode=debug_mode)
        assert "model" in self.profile, "Oscilloscope model not specified in profile."

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

        self._wait()
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

        self._wait()

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
        self._wait()
    
    def set_channel_axis(self, channel: int, scale: float, offset: float) -> None:
        """
        Sets the channel axis of the oscilloscope. (y-axis)

        :param channel: The channel to set
        :param scale: The scale of the channel axis in volts
        :param offset: The offset of the channel in volts
        """
        self._send_command(f':CHANnel{channel}:SCALe {scale}')
        self._send_command(f':CHANnel{channel}:OFFSet {offset}')
        self._wait()
        
    def measure_voltage_peak_to_peak(self, channel):
        """
        Measure the peak-to-peak voltage for a specified channel.
        
        This method sends an SCPI query to the oscilloscope to measure the peak-to-peak voltage 
        of the given channel, then encapsulates the measurement result into a MeasurementResult object.
        
        Args:
        channel (int): The channel identifier, which can be an integer or string depending on the oscilloscope model.
        
        Returns:
        MeasurementResult: An object containing the peak-to-peak voltage measurement for the specified channel.
        
        Example:
        >>> measure_voltage_peak_to_peak(1)
        <MeasurementResult object at 0x7f1ec2a4f510>
        """
        self._check_valid_channel(channel)


        measurement_result = MeasurementResult(self.profile["model"], "V", "peak to peak voltage")

        response = self._query(f"MEAS:VPP? CHAN{channel}")
        measurement_result.add()
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

    def read_channels(self, channels: List[int], points=10000, runAfter=True, timebase=None):
        if timebase is not None:
            self.set_timebase_scale(timebase)

        self._log(points)
        self._log("starting")

        for channel in channels:
            self._check_valid_channel(channel)

        # Prepare the MeasurementResult dictionary
        sampling_rate = float(self.get_sampling_rate())
        measurement_results = {channel: MeasurementResult(instrument=f"{self.profile['manufacturer']}:{self.profile['model']}", units="V", measurement_type="Voltage", sampling_rate=sampling_rate, realtime_timestamps=True)
                            for channel in channels}

        # Setup and digitize commands
        channel_commands = ', '.join(f"CHANnel{channel}" for channel in channels)
        self._send_command(f"DIGitize {channel_commands}")
        self._send_command(f':WAVeform:SOURce CHANnel{channels[0]}')

        # Read preamble to get scaling factors
        pream = self._read_preamble()

        # Prepare the time axis once, as it is the same for all channels
        time_values = (np.arange(0, pream.points, 1) - pream.xref) * pream.xinc + pream.xorg

        for i, channel in enumerate(channels):
            data = self._read_wave_data(channel, points)
            if len(data) != pream.points:
                print('ERROR: points mismatch, please investigate')

            # Calculate the voltage values
            voltages = (data - pream.yref) * pream.yinc + pream.yorg

            # Populate the MeasurementResult object for this channel
            for voltage, time_val in zip(voltages, time_values):
                measurement_results[channel].add(MeasurementValue(voltage, timestamp=time_val))

        if runAfter:
            self._send_command(":RUN")

        return measurement_results
    
    # def set_probe_attenuation(self, channel, attenuation):
    #     """
    #     Sets the probe attenuation for a given channel.

    #     """
    #     self._check_valid_channel(channel)
    #     # Set the probe attenuation for the specified channel
    #     self._send_command(f"CHANnel{channel}:PROBe {attenuation}")

    def get_sampling_rate(self):
        # Send the SCPI command to query the current sampling rate
        response = self._query(":ACQuire:SRATe?")
        
        # Parse the response to get the sampling rate value.
        sampling_rate = float(response)
        
        return MeasurementValue(sampling_rate, "Hz")
    
    def set_probe_scale(self, channel, scale):
        """
        Sets the probe scale for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to set the scale for.
            scale (float): The probe scale value (e.g., 10.0 for 10:1, 1.0 for 1:1).
        """
        self._check_valid_channel(channel)

        # The command format is hypothetical and needs to be adjusted 
        # to match the specific oscilloscope command set.
        command = f":PROBe:CH{channel}:ATTenuation {scale}"
        self._send_command(command)

        # Confirm the action to the log
        self._log(f"Set probe scale to {scale}:1 for channel {channel}.")

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
        Set the total acquisition time for the oscilloscope.

        ARGS;
            time (float): The total acquisition time in seconds.
        """
        # Set the total time for acquisition
        self._send_command(f":TIMebase:MAIN:RANGe {time}")

    def set_sample_rate(self, rate):
        """
        Sets the sample rate for the oscilloscope.

        Args:
        rate (str): The desired sample rate. Valid values are 'MAX' and 'AUTO'.
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
        Sets the trigger level for a given channel.

        Parameters:

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

    def display_channel(self, channels, state=True) -> None:
        """
        Display the specified channels on the oscilloscope.
        
        This method sends an SCPI command to the oscilloscope to display the specified channels.
        
        Args:
        channels (list): A list of channels to display on the oscilloscope.
        
        Raises:
        ValueError: If the oscilloscope model does not support the specified channel(s).
        
        Example:
        >>> display_channel(["CH1", "CH2"])
        """
        for channel in channels:
            self._check_valid_channel(channel)
        # Implement SCPI commands to display the specified channels
        self._send_command(f"CHAN:{channels}:DISP {'ON' if state else 'OFF'}")


    def fft_display(self, state=True):
        """
        Switches on the FFT display

        :param state: The state of the FFT display
        """
        assert "fft" in self.profile, "FFT is not available on this oscilloscope."

        self._send_command(f":FFT:DISPlay {'ON' if state else 'OFF'}")
        self._log(f"FFT display {'enabled' if state else 'disabled'}.")

    def function_display(self, state=True):
        """
        Switches on the function display

        :param state: The state of the function display
        """
        
        self._send_command(f":FUNCtion:DISPlay {'ON' if state else 'OFF'}")
        self._log(f"Function display {'enabled' if state else 'disabled'}.")

    def configure_fft(self, source_channel: int, scale: float = None, offset: float = None, window_type: str = 'HANNing', units: str = 'DECibel', display: bool = True):
        """
        Configure the oscilloscope to perform an FFT on the specified channel with the given parameters.

        :param source_channel: The channel number to perform FFT on.
        :param scale: The scale of the FFT display in dB. Defaults to None.
        :param offset: The offset of the FFT display. Defaults to None.
        :param window_type: The windowing function to apply. Defaults to 'HANNing'.
        :param units: The unit of measurement for the FFT (DECibel or VRMS). Defaults to 'DECibel'.
        :param display: A boolean to turn the FFT display ON or OFF. Defaults to True.
        """

        # Ensure the oscilloscope supports FFT and the specified channel is valid
        assert "fft" in self.profile, "FFT is not available on this oscilloscope."
        assert source_channel in self.profile["channels"], f"Invalid channel {source_channel}. Supported channels: {self.profile['channels']}"
        assert window_type in self.profile["fft"]["window_types"], f"Invalid window type {window_type}. Supported window types: {self.profile['fft']['window_types']}"
        assert units in self.profile["fft"]["units"], f"Invalid units {units}. Supported units: {self.profile['fft']['units']}"

        # Set the FFT source to the specified channel
        self._send_command(f':FFT:SOURce1 CHANnel{source_channel}')
        # Configure the FFT window type
        self._send_command(f':FFT:WINDow {window_type}')
        # Configure the FFT vertical type (units)
        self._send_command(f':FFT:VTYPe {units}')
        # Set the scale if provided
        if scale is not None:
            self._send_command(f':FFT:SCALe {scale}dB')
        # Set the offset if provided
        if offset is not None:
            self._send_command(f':FFT:OFFSet {offset}')
        # Turn the FFT display on or off based on the parameter
        display_state = '1' if display else '0'
        self._send_command(f':FFT:DISPlay {display_state}')

        self._log(f"FFT configured for channel {source_channel}.")

    def _convert_binary_block_to_data(self, binary_block):
        # Process the binary data header to determine the size of the block
        header_len = int(binary_block[1])  # Assuming the length of the length field itself is 1 byte
        expected_data_points = int(binary_block[2:2+header_len])

        # Use _read_to_np to read the binary data into a NumPy array
        data = self._read_to_np()

        # Ensure that we've read the correct number of data points
        assert len(data) == expected_data_points, "Data size mismatch"

        # Data is now in a NumPy array format and can be reshaped or processed as needed
        # For FRANalysis, the data often comes in pairs representing frequency and response (magnitude/phase)
        # so we need to reshape the array accordingly
        data_points_per_entry = 2  # Assuming each data point consists of a frequency and a corresponding value
        structured_data = data.reshape((-1, data_points_per_entry))
        
    def perform_franalysis(self, input_channel, output_channel, start_freq, stop_freq, points=1000, mode='SWEep'):
        """
        Perform a frequency response analysis on the oscilloscope.

        :param input_channel: The channel number to use as the input.
        :param output_channel: The channel number to use as the output.
        :param start_freq: The start frequency of the analysis in Hz.
        :param stop_freq: The stop frequency of the analysis in Hz.
        :param points: The number of points to use for the analysis.
        """
        # Validate input
        self._check_valid_channel(input_channel)
        self._check_valid_channel(output_channel)
        assert mode in ['SWEep', 'SINGle'], 'Mode should be "SWEep" or "SINGle"'
        assert 10 <= start_freq < stop_freq <= 20000000, 'Frequency range should be within 10 Hz to 20 MHz'
        assert points > 0, 'Number of points must be positive'

        # Enable FRANalysis
        self._send_command(":FRANalysis:ENABle 1")

        # Set the start and stop frequencies
        self._send_command(f":FRANalysis:FREQuency:STARt {start_freq}Hz")
        self._send_command(f":FRANalysis:FREQuency:STOP {stop_freq}Hz")

        # Set the mode
        self._send_command(f":FRANalysis:FREQuency:MODE {mode}")

        # If single frequency mode, set the single frequency, otherwise set points for sweep
        if mode == 'SINGle':
            self._send_command(f":FRANalysis:FREQuency:SINGle {start_freq}Hz")
        else:
            # Not directly provided in the command summary, assuming there's a command for points
            assert points > 0, 'Number of points must be positive'
            # TODO remove this hard-coded limit - only for DSOX1204G
            assert points <= 1000, 'Number of points must be less than 1000'
            self._send_command(f":FRANalysis:SWEep:POINts {points}")

        # Initiate FRANalysis
        self._send_command(":FRANalysis:RUN")

        # Wait for analysis to complete and then read the data
        # The waiting mechanism is not detailed, assuming there's a method for it
        self._wait()
        # Read the FRANalysis data (binary block format)
        franalysis_data = self._query(":FRANalysis:DATA?")

        # Process the binary block data into a structured format
        # Assuming a helper function to convert binary block to numerical data
        data = self._read_preamble()
        # data = self._convert_binary_block_to_data(franalysis_data)

        # Disable FRANalysis after completion
        self._send_command(":FRANalysis:ENABle 0")

        # Return the processed data
        return data
    
    def read_fft_data(self) -> MeasurementResult:
        """
        Perform the FFT and read the data from the oscilloscope, returning it as a MeasurementResult.

        :return: A MeasurementResult object containing the FFT data.
        """
        self._log('Initiating FFT data read.')
        
        # The oscilloscope setup for FFT should be done before calling this method
        # Make sure that the acquisition is already started or in continuous mode
        
        # Assuming :FUNCtion:DATA? returns the FFT data from the oscilloscope
        self._send_command(':FUNCtion:DATA?')
        fft_data = self._read_to_np()
        
        # Now, instead of just returning fft_data, we need to encapsulate it into MeasurementValue objects
        # and then add these to a MeasurementResult object.

        # For this example, let's assume 'self.sampling_rate' is set and represents the sampling rate used for FFT
        if self.sampling_rate is None:
            raise ValueError("Sampling rate must be set to read FFT data.")
        
        # Compute the frequency bins for the FFT data
        freq = np.fft.fftfreq(len(fft_data), 1 / self.sampling_rate)
        
        units = self._query(":FFT:VTYPe?")
        # Create a new MeasurementResult for the FFT results
        fft_measurement_result = MeasurementResult(
            instrument=self.instrument,  # Replace with actual attribute, if different
            units=units,  
            measurement_type="Frequency Spectrum",
            sampling_rate=self.sampling_rate  # Including the sampling rate for reference
        )
        
        # Populate the MeasurementResult with MeasurementValue objects
        for f, magnitude in zip(freq, fft_data):
            fft_measurement_value = MeasurementValue(value=magnitude)
            # Normally, timestamp would be set to the time the measurement was taken
            # In this case, we can repurpose it to store the frequency, if that's acceptable for your design
            fft_measurement_value.timestamp = f
            fft_measurement_result.add(fft_measurement_value)
        
        return fft_measurement_result

# class DigitalOscilloscopeWithJitter(Oscilloscope):

#     def __init__(self, visa_resource, profile):
#         super().__init__(visa_resource, profile)

#     def _available_jitter_measurements(self, jitter_type):
#         if jitter_type not in self.profile["jitter_analysis"]["available_types"]:
#             raise ValueError(f"Invalid jitter type {jitter_type}. Supported jitter types: {self.profile['jitter_analysis']}")

#     def setup_rms_jitter_measurement(self, channel):
#         self._available_jitter_measurements("rms")
#         # Implement SCPI commands to set up the oscilloscope for jitter measurement
#         self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
#         self._send_command("MEASure:JITTer:MODE RMS")

#     def setup_peak_to_peak_jitter_measurement(self, channel):
#         self._available_jitter_measurements("peak_to_peak")
#         # Implement SCPI commands to set up the oscilloscope for jitter measurement
#         self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
#         self._send_command("MEASure:JITTer:MODE PK2PK")

#     def setup_period_jitter_measurement(self, channel):
#         self._available_jitter_measurements("period")
#         # Implement SCPI commands to set up the oscilloscope for jitter measurement
#         self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
#         self._send_command("MEASure:JITTer:MODE PERiod")

#     def setup_cycle_to_cycle_jitter_measurement(self, channel):
#         self._available_jitter_measurements("cycle_to_cycle")
#         # Implement SCPI commands to set up the oscilloscope for jitter measurement
#         self._send_command(f"MEASure:JITTer:SOURce CHANnel{channel}")
#         self._send_command("MEASure:JITTer:MODE CCYCle")

#     def configure_trigger(self, trigger_source, trigger_level):
#         # Implement SCPI commands to configure trigger settings for jitter measurement
#         self._send_command(f"TRIGger:SOURce CHANnel{trigger_source}")
#         self._send_command(f"TRIGger:LEVel CHANnel{trigger_source},{trigger_level}")

#     def acquire_jitter_data(self):
#         # Implement SCPI commands to acquire jitter data from the oscilloscope
#         self._send_command("ACQuire:STATE RUN")

#     def analyze_jitter_data(self):
#         measurement_result = MeasurementResult(self.profile["model"], "s", "jitter")
#         jitter_value = self._query_command("MEASure:JITTer?")
#         measurement_result.add_measurement(jitter_value)
#         return measurement_result
    
#     def perform_rms_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
#         self.setup_rms_jitter_measurement(channel)
#         self.configure_trigger(trigger_source, trigger_level)
#         self.acquire_jitter_data()
#         return self.analyze_jitter_data()
    
#     def perform_peak_to_peak_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
#         """
#         Perform a peak-to-peak jitter measurement on a specified channel with given trigger settings.
        
#         This method sets up the measurement, configures the trigger, acquires the jitter data and 
#         then analyzes the data to return a MeasurementResult object containing the results of 
#         the jitter measurement.
        
#         Args:
#         channel (str/int): The identifier for the channel on which the measurement is to be performed.
#                         This could be an integer representing the channel number or a string representing
#                         the channel name, depending on the implementation.
#         trigger_source (str/int): The identifier for the trigger source. This could be an integer or a 
#                                 string representing the source depending on the implementation.
#         trigger_level (float): The trigger level for the measurement in volts. This value sets the voltage 
#                             level at which the trigger event occurs.
        
#         Returns:
#         MeasurementResult: An object containing the results of the peak-to-peak jitter measurement.
        
#         Raises:
#         NotImplementedError: If any of the method calls within this function (e.g., setup_peak_to_peak_jitter_measurement, 
#                             configure_trigger, acquire_jitter_data, analyze_jitter_data) are not implemented.
#         MeasurementError: If there is an error during the measurement process.
        
#         Example:
#         >>> perform_peak_to_peak_jitter_measurement("CH1", "External", 0.5)
#         <MeasurementResult object at 0x7f9bd8134f50>
#         """
#         self.setup_peak_to_peak_jitter_measurement(channel)
#         self.configure_trigger(trigger_source, trigger_level)
#         self.acquire_jitter_data()
#         return self.analyze_jitter_data()

        
#     def perform_period_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
#         self.setup_period_jitter_measurement(channel)
#         self.configure_trigger(trigger_source, trigger_level)
#         self.acquire_jitter_data()
#         return self.analyze_jitter_data()

#     def perform_cycle_to_cycle_jitter_measurement(self, channel, trigger_source, trigger_level) -> MeasurementResult:
#         self.setup_cycle_to_cycle_jitter_measurement(channel)
#         self.configure_trigger(trigger_source, trigger_level)
#         self.acquire_jitter_data()
#         return self.analyze_jitter_data()
        