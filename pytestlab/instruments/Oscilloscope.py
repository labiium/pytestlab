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
from matplotlib import pyplot as plt

_ACQ_TYPE_MAP: dict[str, str] = {
    "NORMAL": "NORMal",
    "AVERAGE": "AVERage",
    "HIGH_RES": "HRESolution",
    "PEAK": "PEAK",
}

_ACQ_MODE_MAP: dict[str, str] = {
    "REAL_TIME": "RTIMe",
    "SEGMENTED": "SEGMented",
}

class ChannelReadingResult(MeasurementResult):

    """
    A class to represent the results of a channel reading from an oscilloscope.

    Attributes:
    values (polars.DataFrame): A DataFrame containing the channel data.
    """
    def plot(self):
        """
        Plots the channel voltages over time.
        # For Notebook use
        """
        channel_columns = self.values.columns[1:]
        # Plotting each channel
        time_data = self.values['Time (s)']
        plt.figure(figsize=(10, 6))  # Set the figure size for better visibility
        for channel in channel_columns:
            channel_data = self.values[channel]

            # Creating the plot
            plt.plot(time_data, channel_data, label=channel)


        # Display the plotf(V)
        plt.title(f"Channel Voltages over time ({','.join(channel_columns)})")
        plt.xlabel("Time (s)")
        plt.ylabel("Channel Signal")
        plt.legend()
        plt.grid(True)
        plt.show()

    def __getitem__(self, channel):
        # extract correct columns of polars dataframe
        try:
            df = self.values[["Time (s)", f"Channel {channel} (V)"]]
            df_renamed = df.rename({f"Channel {channel} (V)": "Voltage (V)"})
            return VoltageReadingResult(
                instrument=self.instrument,
                units="V",
                measurement_type="VoltageTime",
                values=df_renamed
            )
                
        except pl.PolarsError as e:
            raise KeyError(f"Channel {channel} not found in data")

class FFTResult(MeasurementResult):
    """
    A class to represent the results of an FFT analysis.

    Attributes:
    values (polars.DataFrame): A DataFrame containing the FFT data.
    """
    def plot(self):
        channel_columns = self.values.columns[1:]
        # Plotting each channel

        frequency_data = self.values['Frequency (Hz)']
        y_label = self.values.columns[1]
        magnitude_data = self.values[y_label]
        # Plotting from Polars data
        plt.figure(figsize=(10, 6))
        plt.title("FFT Magnitude vs. Frequency")
        plt.xlabel("Frequency (Hz)")
        # get column label
        plt.ylabel(y_label)
        plt.plot(frequency_data, magnitude_data, 'r-o', label=y_label)
        plt.grid(True, which="both", ls="--")
        # plt.legend(loc='upper left')
        plt.show()

class VoltageReadingResult(MeasurementResult):
    """
    
    A class to represent the results of a voltage reading from an oscilloscope.

    Attributes:
    values (polars.DataFrame): A DataFrame containing the voltage data.
    """

    def plot(self, title="Voltage over Time"):
        plt.figure(figsize=(10, 6))
        plt.plot(self.values["Time (s)"], self.values["Voltage (V)"])
        plt.title(title)
        plt.xlabel("Time (s)")
        plt.ylabel("Voltage (V)")
        plt.grid(True)
        plt.show()

    def __getitem__(self, key):
        return self.values[key]

class FRanalysisResult(MeasurementResult):

    """
    A class to represent the results of a frequency response analysis from an oscilloscope.

    Attributes:
    values (polars.DataFrame): A DataFrame containing the frequency response data.
    """
    def plot(self, title="Gain and Phase vs. Frequency"):
        plt.figure(figsize=(12, 6))

        frequency = self.values[:,1].to_numpy()
        gain = self.values[:,3].to_numpy()
        phase = self.values[:,4].to_numpy()

        # Plotting from Polars data
        plt.figure(figsize=(12, 6))

        # Plot Gain vs. Frequency
        plt.subplot(2, 1, 1)
        plt.semilogx(frequency, gain, 'r-o', label='Gain (dB)')
        plt.title(title)
        plt.ylabel('Gain (dB)')
        plt.grid(True, which="both", ls="--")
        plt.legend(loc='upper left')

        # Plot Phase vs. Frequency
        plt.subplot(2, 1, 2)
        plt.semilogx(frequency, phase, 'b-o', label='Phase (°)')
        plt.xlabel('Frequency (Hz)')
        plt.ylabel('Phase (°)')
        plt.grid(True, which="both", ls="--")
        plt.legend(loc='upper left')

        plt.tight_layout()
        plt.show()

    def __getitem__(self, key):
        return self.values[key]

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
        super().__init__(config=config, debug_mode=debug_mode)

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

    # def _check_valid_channel(self, channel: int) -> None:
    #     if channel not in self.config.channels:
    #         raise InstrumentParameterError(f"Invalid channel {channel}. Supported channels: {self.config.channels}")
        
    def _read_wave_data(self, source: str) -> np.ndarray:

        self._wait()
        self._send_command(f':WAVeform:SOURce {source}')
        
        self._wait()
        
        self._log(f"Reading data from {source}")

        self._send_command(':WAVeform:FORMat BYTE')

        if source != "FFT":
            self._send_command(':WAVeform:POINts:MODE RAW')

        self._log('Reading points')

        self._wait()

        self._log('Reading data')

        raw_data = self._query_raw(':WAVeform:DATA?')
        data = self._read_to_np(raw_data)
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
        self.config.channels.validate(channel)
        
        self._send_command(f':CHANnel{channel}:SCALe {scale}')
        self._send_command(f':CHANnel{channel}:OFFSet {offset}')
        self._wait()

    def get_channel_axis(self, channel: int) -> List[float]:
        """
        Gets the channel axis of the oscilloscope. (y-axis)

        :param channel: The channel to get the axis for
        :return: A list containing the channel axis scale and offset
        """
        self.config.channels.validate(channel)
        
        scale = self._query(f":CHANnel{channel}:SCALe?")
        offset = self._query(f":CHANnel{channel}:OFFSet?")
        return [np.float64(scale), np.float64(offset)]
        
        
    def configure_trigger(self, channel: int, level: float, source=None, trigger_type="HIGH", slope: str = "POS", mode: str = "EDGE") -> None:
        """
        Sets the trigger for the oscilloscope.
        
        :param channel: The channel to set the trigger for
        :param slope: The slope of the trigger. Default is 'POS'
        :param trigger_type: The type of trigger. Default is 'HIGH'
        :param level: The trigger level in volts
        :param mode: The trigger mode. Default is 'EDGE'
        :param source: The source of the trigger. Default behaviour is to use the channel Valid options CHANnel<n> | EXTernal | LINE | WGEN
        """
        
        self.config.channels.validate(channel)


        if source is None:
            source = f"CHANnel{channel}"
        else:
            source = source.upper()
            # validate sources
            # validate in scenario where source is potential a channel
            if source.startswith("CHAN"):
                last_char = source[-1]
                if not last_char.isdigit():
                    raise InstrumentParameterError(f"Invalid source {source}.")
                channel = int(last_char)
                self.config.channels.validate(channel)
            elif source not in ["EXTernal", "LINE", "WGEN"]:
                raise InstrumentParameterError(f"Invalid source {source}.")


        self._send_command(f':TRIG:SOUR {source}')
        # self._send_command(f':TRIGger:LEVel:{self.config.trigger.types[trigger_type]} {level}, CHAN{channel}')
        self._send_command(f':TRIGger:LEVel {level}, CHAN{channel}')
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
        self.config.channels.validate(channel)

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
        self.config.channels.validate(channel)

        response = self._query(f"MEAS:VRMS? CHAN{channel}")
        
        self._log("RMS Voltage: " + str(response))
        
        measurement_result = MeasurementResult(float(response),self.config.model, "V", "rms voltage")
        return measurement_result

    def read_channels(self, *channels: List[int] | int, points=None, runAfter=True, timebase=None):
        """
        Reads the specified channels from the oscilloscope.
        
        This method sends an SCPI command to the oscilloscope to read the specified channels.
        
        Args:
        channels (list|int): A list of channel numbers to read.
        timebase (float): The timebase scale to use for the measurement.
        
        Returns:
        dict: A dictionary containing the measurement results for each channel.
        
        Example:
        >>> read_channels([1, 2, 3, 4])
        >>> read_channels(1,2,3,4)
        >>> read_channels(1)
        """
        if timebase is not None:
            self.set_timebase_scale(timebase)

        if points != None:
            print("DEPRECATED: points argument is deprecated. Use set_time_axis instead.")

        self._log(points)
        self._log("starting")

        if (isinstance(channels[0], list) or isinstance(channels[0], tuple)) and len(channels) == 1:
            channels = channels[0]            
        elif not isinstance(channels, list) and not isinstance(channels, tuple):
            raise InstrumentParameterError("Invalid channel type. Must be an integer or a list of integers.")
        
        if isinstance(channels, tuple):
            if len(channels) == 0:
                raise InstrumentParameterError("No channels specified")

        for channel in channels:
            self.config.channels.validate(channel)

        # Prepare the MeasurementResult dictionary
        sampling_rate = float(self.get_sampling_rate())

        # Build common channel list  ───────────────────────────────────────
        channel_commands = ', '.join(f"CHANnel{ch}" for ch in channels)

        # Check if we're in AVERAGE acquisition mode, which requires special handling
        acq_type = self.get_acquisition_type()
        acq_mode = self.get_acquisition_mode()
        
        # Special handling for AVERAGE acquisition type
        if acq_type == "AVERAGE":
            self._log("AVERAGE acquisition type detected - using special sequence")
            
            # Get the current average count
            avg_count = self.get_acquisition_average_count()
            self._log(f"Current average count: {avg_count}")
            
            # Ensure we have proper completion criteria set (100% means all points must be averaged)
            self._send_command(":ACQuire:COMPlete 100")
            
            # Stop any ongoing acquisition
            self._send_command(":STOP")
            self._wait()
            
            # ---- set up a clean single averaged acquisition ---------------------
            # 1. let the scope auto‑trigger so it never waits forever
            sweep_orig = self._query(":TRIGger:SWEep?").strip()
            self._send_command(":TRIGger:SWEep AUTO")

            # 2. fire the averaged capture and immediately force a trigger
            self._send_command(f"DIGitize {channel_commands}", skip_check=True)
            self._send_command(":TRIGger:FORCe", skip_check=True)

            # 3. block until the scope reports *Operation Complete*
            self._send_command("*OPC")          #  ←  **add this line**
            self._log("Waiting for acquisition to complete …")
            self._wait()              # issues *OPC?* internally

            # guarantee the scope does not wait forever in “Ready”
            self._send_command(":TRIGger:FORCe", skip_check=True)
            self._log("Waiting for acquisition to complete …")
            self._wait()              # *OPC?* – now works, finishes at 100 %

            # 4. restore user trigger sweep and clear the error queue
            self._send_command(f":TRIGger:SWEep {sweep_orig}", skip_check=True)
            self.clear_errors()
        else:
            # Standard digitize for other acquisition types
            self._send_command(f"DIGitize {channel_commands}")

        # Configure waveform reading
        self._send_command(f':WAVeform:SOURce CHANnel{channels[0]}')
        self._send_command(':WAVeform:FORMat BYTE')
        self._send_command(':WAVeform:POINts:MODE RAW')
        
        # Read preamble to get scaling factors
        
    
        pream = self._read_preamble()

        # ───── read each channel & derive the correct time base ──────────────
        time_values        = None          # will be filled from 1st channel
        measurement_results = {}

        for idx, channel in enumerate(channels):
            voltages = (
                self._read_wave_data(f"CHANnel{channel}") - pream.yref
            ) * pream.yinc + pream.yorg

            # first channel defines the *actual* record length
            if time_values is None:
                n_pts       = len(voltages)        # 2× in PEAK mode
                time_values = (
                    np.arange(n_pts) - pream.xref
                ) * pream.xinc + pream.xorg

            measurement_results[channel] = voltages

        
        # Make series names string and "Channel 1" etc
        measurement_results = {f"Channel {key} (V)": value for key, value in measurement_results.items()}

        return ChannelReadingResult(
           instrument=self.config.model,
           units="V",
           measurement_type="ChannelVoltageTime",
           sampling_rate=sampling_rate,
           values=pl.DataFrame({
                "Time (s)": time_values,
                **measurement_results
           })
        )

    # def read_fft(source_channel: int, scale: float = None, offset: float = None, window_type: str = 'HANNing', units: str = 'DECibel', display: bool = True):
    #     """
    #     Perform the FFT and read the data from the oscilloscope, returning it as a MeasurementResult.

    #     :return: A MeasurementResult object containing the FFT data.
    #     """
    #     self.configure_fft(source_channel, scale, offset, window_type, units, display)
    #     data = self._read_to_np()
    #     return FRanalysisResult(
    #         instrument=self.config.model,
    #         values=data,
    #         units="dB",
    #         measurement_type="FFT"
    #     )
    
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
        self.config.channels.validate(channel)
        # Set the probe attenuation for the specified channel
        response = self._query(f"CHANnel{channel}:PROBe?")
        response = f"{response}:1"

        return response
        
    def set_probe_attenuation(self, channel, scale):
        """
        Sets the probe scale for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to set the scale for.
            scale (int): The probe scale value (e.g., 10 for 10:1, 1 for 1:1).
        """
        self.config.channels.validate(channel)
        
        self._send_command(f":CHANnel{channel}:PROBe {self.config.channels[channel].probe_attenuation[scale]}")

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
        self.config.channels.validate(channel)
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

        This method sends an SCPI command to change the function (e.g., 'SIN', 'SQUARE') of the waveform generator.
        
        Args:
        state (str): The desired function ('SIN', 'SQUARE', etc.) for the waveform generator.

        Raises:
        InstrumentParameterError: If the oscilloscope model does not have a waveform generator or if the state is not supported.

        Example:
        >>> set_wave_gen_func('SIN')
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

        # print(self.config.function_generator)
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
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}')
        self._send_command(f':WGEN:FREQuency {self.config.function_generator.frequency.in_range(freq)}')
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
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}')
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
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}')
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
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}')
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
            self.config.channels.validate(channel)
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
    def configure_fft(self, source_channel: int, scale: float = None, offset: float = None, span: float = None,  window_type: str = 'HANNing', units: str = 'DECibel', display: bool = True):
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
        if span != None:
            self._send_command(f':FFT:SPAn {span}')
        # Configure the FFT vertical type (units)
        self._send_command(f':FFT:VTYPe {units}')
        # Set the scale if provided
        # if scale is not None:
            # self._send_command(f':FFT:SCALe {scale}dB')
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
        raw_data = self._read_wave_data("FFT")
        preamble = self._read_preamble()
        data = (raw_data - preamble.yref) * preamble.yinc + preamble.yorg

        sampling_rate = self.get_sampling_rate()

        frequency = np.fft.fftfreq(len(data), 1 / sampling_rate)

        # Process the binary data header to determine the size of the block
        # fft_data = self._read_to_np(data)

        units = self._query(":FFT:VTYPe?")

        label = ""

        if units == "DEC":
            label = "Magnitude (dB)"
        elif units == "VRMS":
            label = "Magnitude (V)"   

        # print(data)
        
        # Now, instead of just returning fft_data, we need to encapsulate it into MeasurementValue objects
        # and then add these to a MeasurementResult object.

        # For this example, let's assume 'self.sampling_rate' is set and represents the sampling rate used for FFT
        # if self.sampling_rate is None:
        #     raise InstrumentParameterError("Sampling rate must be set to read FFT data.")
        
        # # Compute the frequency bins for the FFT data
        # freq = np.fft.fftfreq(len(fft_data), 1 / self.sampling_rate)
        
        # units = self._query(":FFT:VTYPe?")
        # # Create a new MeasurementResult for the FFT results
        # fft_measurement_result = MeasurementResult(
        #     instrument=self.instrument,  # Replace with actual attribute, if different
        #     units=units,  
        #     measurement_type="FFT",
        #     sampling_rate=self.sampling_rate,  # Including the sampling rate for reference
        #     values= np.array([freq, fft_data])
        # )
        
        # Populate the MeasurementResult with MeasurementValue objects
        # for f, magnitude in zip(freq, fft_data):
            # fft_measurement_value = MeasurementValue(value=magnitude)
            # # Normally, timestamp would be set to the time the measurement was taken
            # # In this case, we can repurpose it to store the frequency, if that's acceptable for your design
            # fft_measurement_value.timestamp = f


            # fft_measurement_result.add(fft_measurement_value)
        
        # return fft_measurement_result

        return FFTResult(
            instrument=self.config.model,
            units="V",
            measurement_type="FFT",
            values=pl.DataFrame({
                "Frequency (Hz)": frequency,
                label: data
            })
        )

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
    def franalysis_sweep(self, input_channel, output_channel, start_freq, stop_freq, amplitude, points=10, trace="none", load="onemeg", disable_on_complete=True):
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
        self.config.channels.validate(input_channel)
        self.config.channels.validate(output_channel)

        # Enable FRANalysis
        self._send_command(":STOP")
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

        # --- kick off the sweep and wait until it really finishes -----------
        self._send_command("*OPC")              # set OPC bit
        self._send_command(":FRANalysis:RUN")   # start the sweep
        self._wait()                            # *OPC? – returns at 100 %

        # --- read the resulting table (binary block) ------------------------
        raw_block = self._query_raw(":FRANalysis:DATA?")
        # strip the #<digits><len> header and convert to text
        hdr_len   = int(chr(raw_block[1]))
        txt_data  = raw_block[2+hdr_len :].decode()

        data = txt_data
        if disable_on_complete:
            self._send_command(":FRANalysis:ENABle 0")

        df = pl.read_csv(StringIO(data))
        # self.
        # return df.drop_nulls()



        return FRanalysisResult(
            instrument="Oscilloscope",
            units="Hz,Vpp, db, Phase",
            measurement_type="franalysis",
            values=df.drop_nulls()
        )

    @ConfigRequires("franalysis")
    def franalysis_disable(self, state=True):
        """
        Fully disables the frequency response analysis feature of the oscilloscope.
        :param state: The state of the frequency response analysis feature.
        """
        
        self._send_command(f":FRANalysis:ENABle {'0' if state else '1'}")
        self._log(f"Frequency response analysis is {'disabled' if state else 'enabled'}.")

    def set_acquisition_type(self, acq_type: str) -> None:
        """
        Select the oscilloscope acquisition algorithm.

        Parameters
        ----------
        acq_type : str
            One of: ``"NORMAL"``, ``"AVERAGE"``, ``"HIGH_RES"``, ``"PEAK"``.
            (Case-insensitive.)

        Notes
        -----
        • ``AVERAGE`` is *not* allowed while the scope is in segmented mode (SCPI
        will complain - we pre-check and raise locally for clarity).
        • When ``AVERAGE`` is chosen you will probably want
        :py:meth:`set_acquisition_average_count` immediately afterwards.
        """
        acq_type = acq_type.upper()
        if acq_type not in _ACQ_TYPE_MAP:
            raise InstrumentParameterError(f"Unknown acquisition type: {acq_type}")

        if acq_type == "AVERAGE" and self._query(":ACQuire:MODE?").strip() == "SEGM":
            raise InstrumentParameterError("AVERAGE mode is unavailable in SEGMENTED acquisition.")

        self._send_command(f":ACQuire:TYPE {_ACQ_TYPE_MAP[acq_type]}")
        self._wait()
        self._log(f"Acquisition TYPE set → {acq_type}")

    def get_acquisition_type(self) -> str:
        """
        Returns
        -------
        str
            Current acquisition type (``"NORMAL"``, ``"AVERAGE"``, ``"HIGH_RES"``,
            or ``"PEAK"``).
        """
        reverse = {v[:4]: k for k, v in _ACQ_TYPE_MAP.items()}
        resp = self._query(":ACQuire:TYPE?").strip()
        return reverse.get(resp, resp)

    # ─────────────────────────────────────────────────────────────────────────────
    def set_acquisition_average_count(self, count: int) -> None:
        """
        Set the running-average length for AVERAGE mode.

        Parameters
        ----------
        count : int
            2 ≤ *count* ≤ 65 536 (Keysight limit).

        Raises
        ------
        InstrumentParameterError
            If *count* is out of range **or** if the scope is not currently in
            ``AVERAGE`` acquisition type.
        """
        _validate_range(count, 2, 65_536, "Average count")
        if self.get_acquisition_type() != "AVERAGE":
            raise InstrumentParameterError("Average count can only be set when acquisition type is AVERAGE.")
        self._send_command(f":ACQuire:COUNt {count}")
        self._wait()
        self._log(f"AVERAGE count set → {count}")

    def get_acquisition_average_count(self) -> int:
        """Integer average count (valid only when acquisition type == ``AVERAGE``)."""
        return int(self._query(":ACQuire:COUNt?"))

    # ─────────────────────────────────────────────────────────────────────────────
    def set_acquisition_mode(self, mode: str) -> None:
        """
        Select real-time or segmented memory acquisition.

        Parameters
        ----------
        mode : str
            ``"REAL_TIME"`` or ``"SEGMENTED"`` (case-insensitive).

        Notes
        -----
        • Switching *away* from SEGMENTED clears the segment count.
        • The Keysight SGM license must be installed for SEGMENTED mode; if
        ``ConfigRequires("segmented_memory")`` is part of your config object you
        can decorate this method similarly.
        """
        mode = mode.upper()
        if mode not in _ACQ_MODE_MAP:
            raise InstrumentParameterError(f"Unknown acquisition mode: {mode}")

        self._send_command(f":ACQuire:MODE {_ACQ_MODE_MAP[mode]}")
        self._wait()
        self._log(f"Acquisition MODE set → {mode}")

    def get_acquisition_mode(self) -> str:
        """Return ``"REAL_TIME"`` or ``"SEGMENTED"``."""
        reverse = {"RTIM": "REAL_TIME", "SEGM": "SEGMENTED"}
        return reverse.get(self._query(":ACQuire:MODE?").strip(), "UNKNOWN")

    # ─────────────────────────────────────────────────────────────────────────────
    #  Segmented-memory helpers
    # ─────────────────────────────────────────────────────────────────────────────
    def set_segmented_count(self, count: int) -> None:
        """
        Configure number of memory segments for SEGMENTED acquisitions.

        Keysight limit: 2 ≤ *count* ≤ 500

        Raises
        ------
        InstrumentParameterError
            If not in SEGMENTED mode or *count* out of range.
        """
        if self.get_acquisition_mode() != "SEGMENTED":
            raise InstrumentParameterError("Segmented count can only be set while in SEGMENTED acquisition mode.")
        _validate_range(count, 2, 500, "Segmented count")
        self._send_command(f":ACQuire:SEGMented:COUNt {count}")
        self._wait()
        self._log(f"Segmented COUNT set → {count}")

    def get_segmented_count(self) -> int:
        """Number of segments currently configured (SEGMENTED mode only)."""
        return int(self._query(":ACQuire:SEGMented:COUNt?"))

    def set_segment_index(self, index: int) -> None:
        """
        Select which memory segment is active for readback.

        1 ≤ *index* ≤ ``get_segmented_count()``
        """
        total = self.get_segmented_count()
        _validate_range(index, 1, total, "Segment index")
        self._send_command(f":ACQuire:SEGMented:INDex {index}")
        self._wait()

    def get_segment_index(self) -> int:
        """Index (1-based) of the currently selected memory segment."""
        return int(self._query(":ACQuire:SEGMented:INDex?"))

    def analyze_all_segments(self) -> None:
        """
        Execute the scope's *Analyze Segments* soft-key (:ACQuire:SEGMented:ANALyze).

        Requires:
        • Scope is **stopped** and in SEGMENTED mode.
        • Either quick measurements or infinite persistence must be enabled.

        The call is synchronous - it returns after analysis completes.
        """
        if self.get_acquisition_mode() != "SEGMENTED":
            raise InstrumentParameterError("Segment analysis requires SEGMENTED mode.")
        self._send_command(":ACQuire:SEGMented:ANALyze")
        self._wait()

    # ─────────────────────────────────────────────────────────────────────────────
    #  Convenience queries
    # ─────────────────────────────────────────────────────────────────────────────
    def get_acquire_points(self) -> int:
        """
        Hardware points actually *acquired* for the next waveform transfer
        (`:ACQuire:POINts?`).  Use :WAVeform:POINts to set what you subsequently
        *read* back.
        """
        return int(self._query(":ACQuire:POINts?"))

    def get_acquisition_sample_rate(self) -> float:
        """
        Wraps :py:meth:`get_sampling_rate` with the canonical ACQuire query
        (identical content; provided for semantic completeness).
        """
        return float(self._query(":ACQuire:SRATe?"))

    def get_acquire_setup(self) -> dict[str, str]:
        """
        Return a parsed dictionary representation of the scope's full
        ``:ACQuire?`` status string.

        Example
        -------
        >>> scope.get_acquire_setup()
        {'MODE': 'RTIM', 'TYPE': 'NORM', 'COMP': '100', 'COUNT': '8', 'SEGM:COUN': '2'}
        """
        raw = self._query(":ACQuire?").strip()
        parts = [p.strip() for p in raw.split(';')]
        return {kv.split()[0]: kv.split()[1] for kv in parts}

def _validate_range(value: int, lo: int, hi: int, name: str) -> None:
    if not lo <= value <= hi:
        raise InstrumentParameterError(f"{name} out of range ({lo}-{hi}): {value}")
