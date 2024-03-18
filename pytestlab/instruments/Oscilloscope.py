import time
import numpy as np
from typing import List
from dataclasses import dataclass
from PIL import Image
from io import BytesIO, StringIO
import polars as pl
from .instrument import Instrument
from ..config import OscilloscopeConfig, ConfigRequires
from ..errors import InstrumentConfigurationError, InstrumentParameterError
from ..experiments import MeasurementResult

@dataclass
class Preamble:
    """A class to store the preamble data from the oscilloscope channel.

    :param format: The format of the data
    :param type: The type of the data
    :param points: The number of points
    :param xinc: The x increment
    :param xorg: The x origin
    :param xref: The x reference
    :param yinc: The y increment
    :param yorg: The y origin
    :param yref: The y reference
    """

    format: str
    type: str
    points: int
    xinc: float
    xorg: float
    xref: float
    yinc: float
    yorg: float
    yref: float


class Oscilloscope(Instrument):
    """
    Provides an interface for controlling and acquiring data from an oscilloscope using SCPI commands.

    This class inherits from SCPIInstrument and implements specific methods to interact with 
    oscilloscope features such as voltage measurement and timebase scaling.

    Attributes:
    visa_resource (str): The VISA resource string used for identifying the connected oscilloscope.
    profile (dict): Information about the instrument model.
    """
    def __init__(self, visa_resource=None, config=None, debug_mode=False):
        """
        Initialize the Oscilloscope class with the given VISA resource and profile information.
        
        Args:
        visa_resource (str): The VISA resource string used for identifying the connected oscilloscope. Optional if a profile is provided.
        profile (dict): Information about the instrument model.
        """
        if not isinstance(config, OscilloscopeConfig):
            raise InstrumentConfigurationError("Invalid configuration provided.")
        super().__init__(visa_resource=visa_resource, config=config, debug_mode=debug_mode)

    @classmethod
    def from_config(cls, config: OscilloscopeConfig, debug_mode=False):
        return cls(config=OscilloscopeConfig(**config), debug_mode=debug_mode)
    
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

    def _check_valid_channel(self, channel: int) -> None:
        if channel not in self.config.channels:
            raise InstrumentParameterError(f"Invalid channel {channel}. Supported channels: {self.config.channels}")
        
    def _read_wave_data(self, channel: int, points: int) -> np.ndarray:

        self._wait()
        self._send_command(f':WAVeform:SOURce CHANnel{channel}')
        
        self._wait()
        
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

        self._send_command(':WAVeform:DATA?', skip_check=True)
        data = self._read_to_np()

        return data
    
    def lock_panel(self, lock=True):
        """
        Locks the panel of the instrument

        Args:
            lock (bool): True to lock the panel, False to unlock it
        """
        if lock:
            self._send_command(":SYSTem:LOCK ON")
        else:
            self._send_command(":SYSTem:LOCK OFF")

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

    def get_time_axis(self) -> List[float]:
        """
        Gets the time axis of the oscilloscope. (x-axis)

        :return: A list containing the time axis scale and position
        """
        scale = self._query(":TIMebase:SCALe?")
        position = self._query(":TIMebase:POSition?")
        return [np.float64(scale), np.float64(position)]
    
    def set_channel_axis(self, channel: int, scale: float, offset: float) -> None:
        """
        Sets the channel axis of the oscilloscope. (y-axis)

        :param channel: The channel to set
        :param scale: The scale of the channel axis in volts
        :param offset: The offset of the channel in volts
        """
        self._check_valid_channel(channel)
        
        self._send_command(f':CHANnel{channel}:SCALe {scale}')
        self._send_command(f':CHANnel{channel}:OFFSet {offset}')
        self._wait()

    def get_channel_axis(self, channel: int) -> List[float]:
        """
        Gets the channel axis of the oscilloscope. (y-axis)

        :param channel: The channel to get the axis for
        :return: A list containing the channel axis scale and offset
        """
        self._check_valid_channel(channel)
        
        scale = self._query(f":CHANnel{channel}:SCALe?")
        offset = self._query(f":CHANnel{channel}:OFFSet?")
        return [np.float64(scale), np.float64(offset)]
        
        
    def configure_trigger(self, channel: int, level: float, trigger_type="HIGH", slope: str = "POS", mode: str = "EDGE") -> None:
        """
        Sets the trigger for the oscilloscope.
        
        :param channel: The channel to set the trigger for
        :param slope: The slope of the trigger. Default is 'POS'
        :param trigger_type: The type of trigger. Default is 'HIGH'
        :param level: The trigger level in volts
        :param mode: The trigger mode. Default is 'EDGE'
        """
        
        self._check_valid_channel(channel)

        self._send_command(f':TRIG:SOUR CHAN{channel}')
        self._send_command(f':TRIGger:LEVel:{self.config.trigger.types[trigger_type]} {level}, CHAN{channel}')
        self._send_command(f':TRIGger:SLOPe {self.config.trigger.slopes[slope]}')
        self._send_command(f':TRIGger:MODE {self.config.trigger.modes[mode]}')
        self._wait()
        
        self._log("""Trigger set with the following parameters:
                  Trigger Source: {channel}
                  Trigger Level: {level}
                  Trigger Slope: {slope}
                  Trigger Mode: {mode}""")
        
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

        response = self._query(f"MEAS:VPP? CHAN{channel}")

        measurement_result = MeasurementResult(
            values=response,
            units="V",
            instrument=self.config.model,
            measurement_type="P2PV",
        )

        self._log("Peak to Peak Voltage: " + str(response))
        
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

        response = self._query(f"MEAS:VRMS? CHAN{channel}")
        
        self._log("RMS Voltage: " + str(response))
        
        measurement_result = MeasurementResult(float(response),self.config.model, "V", "rms voltage")
        return measurement_result

    def read_channels(self, channels: List[int] | int, points=10000, runAfter=True, timebase=None, recursive_depth=0):
        """
        Reads the specified channels from the oscilloscope.
        
        This method sends an SCPI command to the oscilloscope to read the specified channels.
        
        Args:
        channels (list|int): A list of channel numbers to read.
        points (int): The number of points to read from each channel.
        timebase (float): The timebase scale to use for the measurement.
        
        Returns:
        dict: A dictionary containing the measurement results for each channel.
        
        Example:
        >>> read_channels([1, 2, 3, 4])

        """
        if timebase is not None:
            self.set_timebase_scale(timebase)



        self._log(points)
        self._log("starting")

        if isinstance(channels, int):
            channels = [channels]
            
        for channel in channels:
            self._check_valid_channel(channel)

        # Prepare the MeasurementResult dictionary
        sampling_rate = float(self.get_sampling_rate())

        # Setup and digitize commands
        channel_commands = ', '.join(f"CHANnel{channel}" for channel in channels)
        self._send_command(f"DIGitize {channel_commands}")
        self._send_command(f':WAVeform:SOURce CHANnel{channels[0]}')

        # Read preamble to get scaling factors
        pream = self._read_preamble()

        # Prepare the time axis once, as it is the same for all channels
        time_values = (np.arange(0, pream.points, 1) - pream.xref) * pream.xinc + pream.xorg

        measurement_results = {}

        for i, channel in enumerate(channels):
            data = self._read_wave_data(channel, points)
            # Calculate the voltage values
            voltages = (data - pream.yref) * pream.yinc + pream.yorg 
            if len(data) != pream.points and recursive_depth < 5:
                return self.read_channels(channels, points=points, runAfter=runAfter, timebase=timebase, recursive_depth=recursive_depth+1)
            elif recursive_depth >= 5:
                raise InstrumentParameterError("Could not resolve point mismatch")
            elif len(voltages) == len(time_values):
                # Populate the 2D numpy array with the voltage values
                measurement_results[channel] = MeasurementResult(instrument=self.config.model,
                                                                    units="V",
                                                                    measurement_type="VoltageTime",
                                                                    sampling_rate=sampling_rate,
                                                                    values=np.vstack((
                                                                        time_values,
                                                                        voltages
                                                                    )))
                if points != len(voltages):
                    print("WARNING: points mismatch please investigate configuration")
                if runAfter:
                    self._send_command(":RUN")

        return measurement_results


    def get_sampling_rate(self):
        """
        Get the current sampling rate of the oscilloscope.
        """
        # Send the SCPI command to query the current sampling rate
        response = self._query(":ACQuire:SRATe?")
        
        # Parse the response to get the sampling rate value.
        sampling_rate = np.float64(response)
        return sampling_rate
        # return MeasurementResult(sampling_rate, self.config.model, "Hz", "sampling rate")
    
    def get_probe_attenuation(self, channel):
        """
        Gets the probe attenuation for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to get the probe attenuation for.

        Returns:
            str: The probe attenuation value (e.g., '10:1', '1:1').

        """
        self._check_valid_channel(channel)
        # Set the probe attenuation for the specified channel
        response = self._query(f"CHANnel{channel}:PROBe?")
        response = f"{response}:1"

        return response
        
    def set_probe_attenuation(self, channel, scale):
        """
        Sets the probe scale for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to set the scale for.
            scale (float): The probe scale value (e.g., 10.0 for 10:1, 1.0 for 1:1).
        """
        self._check_valid_channel(channel)
        
        self._send_command(f":CH{channel}:PROBe {self.config.channels[channel].probe_attenuation[scale]}")

        # Confirm the action to the log
        self._log(f"Set probe scale to {scale}:1 for channel {channel}.")

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
            raise InstrumentParameterError(f"Invalid Valid: supported = {valid_values}")
        # Set the sample rate for acquisition
        self._send_command(f"ACQuire:SRATe {rate}")

    def set_bandwidth_limit(self, channel, bandwidth):
        """
        
        """
        self._check_valid_channel(channel)
        # Limit the bandwidth to a specified frequency to reduce noise
        self._send_command(f"CHANnel{channel}:BANDwidth {bandwidth}")

    @ConfigRequires("function_generator")
    def wave_gen(self, state: bool):
        """
        Enable or disable the waveform generator of the oscilloscope.

        This method sends an SCPI command to enable or disable the function generator in the oscilloscope.
        
        Args:
        state (str): The desired state ('ON' or 'OFF') for the waveform generator.
        
        Raises:
        InstrumentParameterError: If the oscilloscope model does not have a waveform generator or if the state is not supported.
        
        Example:
        >>> set_wave_gen('ON')
        """
        self._send_command(f"WGEN:OUTP {'ON' if state else 'OFF'}")

    @ConfigRequires("function_generator")
    def set_wave_gen_func(self, state):
        """
        Set the waveform function for the oscilloscope's waveform generator.

        This method sends an SCPI command to change the function (e.g., 'SINE', 'SQUARE') of the waveform generator.
        
        Args:
        state (str): The desired function ('SINE', 'SQUARE', etc.) for the waveform generator.

        Raises:
        InstrumentParameterError: If the oscilloscope model does not have a waveform generator or if the state is not supported.

        Example:
        >>> set_wave_gen_func('SINE')
        """
        
        self._send_command(f"WGEN:FUNC {self.config.function_generator.waveform_types[state]}")

    @ConfigRequires("function_generator")
    def set_wave_gen_freq(self, freq):
        """
        Set the frequency for the waveform generator.

        This method sends an SCPI command to set the frequency of the waveform generator.
        
        Args:
        freq (float): The desired frequency for the waveform generator in Hz.

        Raises:
        InstrumentParameterError: If the oscilloscope model does not have a waveform generator or if the frequency is out of range.

        Example:
        >>> set_wave_gen_freq(1000.0)
        """
        
        self._send_command(f"WGEN:FREQ {self.config.function_generator.frequency.in_range(freq)}")

    @ConfigRequires("function_generator")
    def set_wave_gen_amp(self, amp):
        """
        Set the amplitude for the waveform generator.

        This method sends an SCPI command to set the amplitude of the waveform generator.
        
        Args:
        amp (float): The desired amplitude for the waveform generator in volts.

        Raises:
        InstrumentParameterError: If the oscilloscope model does not have a waveform generator or if the amplitude is out of range.

        Example:
        >>> set_wave_gen_amp(1.0)
        """

        print(self.config.function_generator)
        self._send_command(f"WGEN:VOLT {self.config.function_generator.amplitude.in_range(amp)}")

    @ConfigRequires("function_generator")
    def set_wave_gen_offset(self, offset):
        """
        Set the voltage offset for the waveform generator.

        This method sends an SCPI command to set the voltage offset of the waveform generator.
        
        Args:
        offset (float): The desired voltage offset for the waveform generator in volts.

        Raises:
        InstrumentParameterError: If the oscilloscope model does not have a waveform generator or if the offset is out of range.

        Example:
        >>> set_wave_gen_offset(0.1)
        """
        
        self._send_command(f"WGEN:VOLT:OFFSet {self.config.function_generator.offset.in_range(offset)}")

    @ConfigRequires("function_generator")
    def set_wgen_sin(self, amp: float, offset: float, freq: float) -> None:
        """Sets the waveform generator to a sine wave. (Only available on specific models)

        :param amp: The amplitude of the sine wave in volts
        :param offset: The offset of the sine wave in volts
        :param freq: The frequency of the sine wave in Hz. The frequency can be adjusted from 100 mHz to 20 MHz.
        """

        self._send_command('WGEN:FUNCtion SINusoid')
        self._send_command(f':WGEN:VOLTage {self.config.function_generator.amplitude.in_range(amp)}')
        self._send_command(f':WGEN:VOLTage:OFFSet {self.config.function_generator.offset.in_range(offset)}')
        self._send_command(f':WGEN:FREQuency {self.config.function_generator.frequency.in_range(freq)}')


    @ConfigRequires("function_generator")
    def set_wgen_square(self, v0: float, v1: float, freq: float, dutyCycle: int) -> None:
        """Sets the waveform generator to a square wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the square wave in Hz. The frequency can be adjusted from 100 mHz to 10 MHz.
        :param dutyCycle: The duty cycle can be adjusted from 1% to 99% up to 500 kHz. At higher frequencies, the adjustment range narrows so as not to allow pulse widths less than 20 ns.
        """
        def clamp(number):
            number = min(number, 99)
            number = max(number, 1)
            return number

        self._send_command('WGEN:FUNCtion SQUare')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.voltage.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.voltage.in_range(v1)}')
        self._send_command(f':WGEN:FREQuency {self.config.fun}')
        self._send_command(f':WGEN:FUNCtion:SQUare:DCYCle {clamp(dutyCycle)}')


    @ConfigRequires("function_generator")
    def set_wgen_ramp(self, v0: float, v1: float, freq: float, symmetry: int) -> None:
        """Sets the waveform generator to a ramp wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the ramp wave in Hz. The frequency can be adjusted from 100 mHz to 100 kHz.
        :param symmetry: Symmetry represents the amount of time per cycle that the ramp waveform is rising and can be adjusted from 0% to 100%.
        """
        
        def clamp(number):
            number = min(number, 100)
            number = max(number, 0)
            return number


        self._send_command('WGEN:FUNCtion RAMP')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.voltage.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.voltage.in_range(v1)}')
        self._send_command(f':WGEN:FREQuency {self.config.function_generator.frequency.in_range(freq)}')
        self._send_command(f':WGEN:FUNCtion:RAMP:SYMMetry {clamp(symmetry)}')


    @ConfigRequires("function_generator")
    def set_wgen_pulse(self, v0: float, v1: float, period: float, pulseWidth: float) -> None:
        """Sets the waveform generator to a pulse wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param period: The period of the pulse wave in seconds. The period can be adjusted from 10 ns to 10 s.
        :param pulseWidth: The pulse width can be adjusted from 20 ns to the period minus 20 ns.
        """
        
        def clamp(number):
            number = min(number, 10)
            number = max(number, 0.00000001)
            return number

        self._send_command('WGEN:FUNCtion PULSe')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.voltage.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.voltage.in_range(v1)}')
        self._send_command(f':WGEN:PERiod {period}')
        self._send_command(f':WGEN:FUNCtion:PULSe:WIDTh {clamp(pulseWidth)}')


    @ConfigRequires("function_generator")
    def set_wgen_dc(self, offset: float) -> None:
        """Sets the waveform generator to a DC wave. (Only available on specific models)

        :param offset: The offset of the DC wave in volts
        """
        
        self._send_command('WGEN:FUNCtion DC')
        self._send_command(f':WGEN:VOLTage:OFFSet {self.config.function_generator.offset.in_range(offset)}')


    @ConfigRequires("function_generator")
    def set_wgen_noise(self, v0: float, v1: float, offset: float) -> None:
        """Sets the waveform generator to a noise wave. (Only available on specific models)

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param offset: The offset of the noise wave in volts
        """
        
        self._send_command('WGEN:FUNCtion NOISe')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.voltage.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.voltage.in_range(v1)}')
        self._send_command(f':WGEN:VOLTage:OFFSet {self.config.function_generator.offset.in_range(offset)}')

    def display_channel(self, channels: list | int, state=True) -> None:
        """
        Display the specified channels on the oscilloscope.
        
        This method sends an SCPI command to the oscilloscope to display the specified channels.
        
        Args:
        channels (list|int): A list of channel numbers to display.
        Raises:
        InstrumentParameterError: If the oscilloscope model does not support the specified channel(s).
        
        Example:
        >>> display_channel([1, 2])
        """
        if isinstance(channels, int):
            channels = [channels]
        
        for channel in channels:
            self._check_valid_channel(channel)
        # Implement SCPI commands to display the specified channels
        for channel in channels:
            self._send_command(f"CHAN{channel}:DISP {'ON' if state else 'OFF'}")

    @ConfigRequires("fft")
    def fft_display(self, state=True):
        """
        Switches on the FFT display

        :param state: The state of the FFT display
        """
        
        self._send_command(f":FFT:DISPlay {'ON' if state else 'OFF'}")
        self._log(f"FFT display {'enabled' if state else 'disabled'}.")
        
    @ConfigRequires("function_generator")
    def function_display(self, state=True):
        """
        Switches on the function display

        :param state: The state of the function display
        """
        
        self._send_command(f":FUNCtion:DISPlay {'ON' if state else 'OFF'}")
        self._log(f"Function display {'enabled' if state else 'disabled'}.")

    @ConfigRequires("fft")
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
        # if source_channel not in self.profile["channels"]:
        #     raise InstrumentParameterError(f"Invalid channel {source_channel}. Supported channels: {self.profile['channels']}")
        # if window_type not in self.profile["fft"]["window_types"]:
        #     raise InstrumentParameterError(f"Invalid window type {window_type}. Supported window types: {self.profile['fft']['window_types']}")
        # if units not in self.profile["fft"]["units"]:
        #     raise InstrumentParameterError(f"Invalid units {units}. Supported units: {self.profile['fft']['units']}")
        
        
        # Set the FFT source to the specified channel
        self._send_command(f':FFT:SOURce1 CHANnel{source_channel}')
        # Configure the FFT window type
        self._send_command(f':FFT:WINDow {window_type}')
        # configure Center span
        self._send_command(f':FFT:CENTer:SPAn 0')
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
        if len(data) != expected_data_points:
            raise InstrumentParameterError("Data size mismatch")
        
        # Data is now in a NumPy array format and can be reshaped or processed as needed
        # For FRANalysis, the data often comes in pairs representing frequency and response (magnitude/phase)
        # so we need to reshape the array accordingly
        data_points_per_entry = 2  # Assuming each data point consists of a frequency and a corresponding value
        structured_data = data.reshape((-1, data_points_per_entry))

    @ConfigRequires("fft")
    def read_fft_data(self) -> MeasurementResult:
        """
        Perform the FFT and read the data from the oscilloscope, returning it as a MeasurementResult.

        :return: A MeasurementResult object containing the FFT data.
        """
        self._log('Initiating FFT data read.')
        
        # The oscilloscope setup for FFT should be done before calling this method
        # Make sure that the acquisition is already started or in continuous mode
        
        # Assuming :FUNCtion:DATA? returns the FFT data from the oscilloscope
        data = self._query_raw(':FUNCtion:DATA?')
        fft_data = self._read_to_np(data)
        
        # Now, instead of just returning fft_data, we need to encapsulate it into MeasurementValue objects
        # and then add these to a MeasurementResult object.

        # For this example, let's assume 'self.sampling_rate' is set and represents the sampling rate used for FFT
        if self.sampling_rate is None:
            raise InstrumentParameterError("Sampling rate must be set to read FFT data.")
        
        # Compute the frequency bins for the FFT data
        freq = np.fft.fftfreq(len(fft_data), 1 / self.sampling_rate)
        
        units = self._query(":FFT:VTYPe?")
        # Create a new MeasurementResult for the FFT results
        fft_measurement_result = MeasurementResult(
            instrument=self.instrument,  # Replace with actual attribute, if different
            units=units,  
            measurement_type="FFT",
            sampling_rate=self.sampling_rate,  # Including the sampling rate for reference
            values= np.array([freq, fft_data])
        )
        
        # Populate the MeasurementResult with MeasurementValue objects
        # for f, magnitude in zip(freq, fft_data):
            # fft_measurement_value = MeasurementValue(value=magnitude)
            # # Normally, timestamp would be set to the time the measurement was taken
            # # In this case, we can repurpose it to store the frequency, if that's acceptable for your design
            # fft_measurement_value.timestamp = f


            # fft_measurement_result.add(fft_measurement_value)
        
        return fft_measurement_result

    def screenshot(self):
        """
        Capture a screenshot of the oscilloscope display.

        :return Image: A PIL Image object containing the screenshot.
        """
        binary_data = self._query_raw(":DISPlay:DATA? PNG, COLor")
        length_of_length = int(chr(binary_data[1]))  # Convert the length indicator to an integer
        data_length = int(binary_data[2:2+length_of_length].decode())  # Extract the length of the image data
        image_data = binary_data[2+length_of_length:2+length_of_length+data_length]  # Extract the image data
        return Image.open(BytesIO(image_data))


    @ConfigRequires("franalysis")
    @ConfigRequires("function_generator")
    def franalysis_sweep(self, input_channel, output_channel, start_freq, stop_freq, amplitude, points=1000, trace="none", load="onemeg", disable_on_complete=True):
        """
        Perform a frequency response analysis sweep on the oscilloscope.

        Parameters:
            :param input_channel: The channel number to use as the input.
            :param output_channel: The channel number to use as the output.
            :param start_freq: The start frequency of the analysis in Hz.
            :param stop_freq: The stop frequency of the analysis in Hz.
            :param points: The number of points to use for the analysis.

        Returns:
            MeasurementResult: A MeasurementResult object containing the frequency response analysis data.
        """
        # Validate input
        self._check_valid_channel(input_channel)
        self._check_valid_channel(output_channel)

        # Enable FRANalysis
        self._send_command(":FRANalysis:ENABle 1")

        self._send_command(f":FRANalysis:SOURce:INPut CHANnel{input_channel}")
        self._send_command(f":FRANalysis:SOURce:OUTPut CHANnel{output_channel}")

        self._send_command(f":FRANalysis:FREQuency:MODE SWEep")
        self._send_command(f":FRANalysis:SWEep:POINts {points}")
        
        self._send_command(f":FRANalysis:FREQuency:STARt {self.config.function_generator.frequency.in_range(start_freq)}Hz")
        self._send_command(f":FRANalysis:FREQuency:STOP {self.config.function_generator.frequency.in_range(stop_freq)}Hz")
    
        self._send_command(f":FRANalysis:WGEN:LOAD {self.config.franalysis.load[load]}")
        self._send_command(f":FRANalysis:TRACE {self.config.franalysis.trace[trace]}")

        self._send_command(f"WGEN:VOLT {self.config.function_generator.amplitude.in_range(amplitude)}")

        self._send_command(f":FRANalysis:RUN")

<<<<<<< HEAD
        self._log(f"Frequency response analysis sweep completed. Data points: {len(data)}")
=======
        self._wait()
        self._wait_event()

        # data = self._convert_binary_block_to_data(self._query_raw(":FRANalysis:DATA?"))

        data = self._query(":FRANalysis:DATA?")
>>>>>>> 0667221b0eb807572fc2da5757058f81be453ffd
        if disable_on_complete:
            self._send_command(":FRANalysis:ENABle 0")

        df = pl.read_csv(StringIO(data))
        # self.
        return df
        # if disable_on_complete:
        #     self._send_command(":FRANalysis:ENABle 0")

        # freq_points = np.linspace(start_freq, stop_freq, points) 
        # return MeasurementResult(
        #     instrument="Oscilloscope",
        #     units="phase",
        #     measurement_type="franalysis",
        #     values=np.vstaskack((freq_points, data))
        # )

    @ConfigRequires("franalysis")
    def franalysis_disable(self, state=True):
        """
        Fully disables the frequency response analysis feature of the oscilloscope.
        :param state: The state of the frequency response analysis feature.
        """
        
        self._send_command(f":FRANalysis:ENABle {'0' if state else '1'}")
        self._log(f"Frequency response analysis is {'disabled' if state else 'enabled'}.")