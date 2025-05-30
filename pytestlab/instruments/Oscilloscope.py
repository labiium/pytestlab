from __future__ import annotations

import time
import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from dataclasses import dataclass
from PIL import Image
from io import BytesIO, StringIO
import polars as pl
from .instrument import Instrument
from ..config import OscilloscopeConfig, ConfigRequires
from ..errors import InstrumentConfigurationError, InstrumentParameterError
from ..experiments import MeasurementResult
from matplotlib import pyplot as plt
from uncertainties import ufloat
from uncertainties.core import UFloat # For type hinting float | UFloat

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
    def plot(self) -> None:
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

    def __getitem__(self, channel: Union[int, str]) -> VoltageReadingResult:
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
            raise KeyError(f"Channel {channel} not found in data") from e

class FFTResult(MeasurementResult):
    """
    A class to represent the results of an FFT analysis.

    Attributes:
    values (polars.DataFrame): A DataFrame containing the FFT data.
    """
    def plot(self) -> None:
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

    def plot(self, title: str = "Voltage over Time") -> None:
        plt.figure(figsize=(10, 6))
        plt.plot(self.values["Time (s)"], self.values["Voltage (V)"])
        plt.title(title)
        plt.xlabel("Time (s)")
        plt.ylabel("Voltage (V)")
        plt.grid(True)
        plt.show()

    def __getitem__(self, key: str) -> pl.Series:
        return self.values[key]

class FRanalysisResult(MeasurementResult):

    """
    A class to represent the results of a frequency response analysis from an oscilloscope.

    Attributes:
    values (polars.DataFrame): A DataFrame containing the frequency response data.
    """
    def plot(self, title: str = "Gain and Phase vs. Frequency") -> None:
        plt.figure(figsize=(12, 6))

        frequency: np.ndarray = self.values[:,1].to_numpy()
        gain: np.ndarray = self.values[:,3].to_numpy()
        phase: np.ndarray = self.values[:,4].to_numpy()

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

    def __getitem__(self, key: str) -> pl.Series:
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
    def __init__(self, visa_resource: Optional[str] = None, config: Optional[OscilloscopeConfig] = None, debug_mode: bool = False, simulate: bool = False) -> None:
        """
        Initialize the Oscilloscope class with the given VISA resource and profile information.
        
        Args:
        visa_resource (str): The VISA resource string used for identifying the connected oscilloscope. Optional if a profile is provided.
        config (OscilloscopeConfig): Configuration object for the oscilloscope.
        debug_mode (bool): Enable debug mode.
        simulate (bool): Enable simulation mode.
        """
        if not isinstance(config, OscilloscopeConfig):
            raise InstrumentConfigurationError("Invalid configuration provided.")
        super().__init__(config=config, debug_mode=debug_mode, simulate=simulate)

    @classmethod
    def from_config(cls: Type[Oscilloscope], config: OscilloscopeConfig, debug_mode: bool = False) -> Oscilloscope:
        # Assuming OscilloscopeConfig can be instantiated from a dict-like config
        # If config is a dict that needs to be passed to OscilloscopeConfig constructor:
        # return cls(config=OscilloscopeConfig(**config), debug_mode=debug_mode)
        # If config is already an OscilloscopeConfig instance:
        return cls(config=config, debug_mode=debug_mode)
    
    def _read_preamble(self) -> Preamble:
        """Reads the preamble from the oscilloscope.

        :return: A Preamble object
        """

        peram_str: str = self._query(':WAVeform:PREamble?')
        peram_list: list[str] = peram_str.split(',')
        self._logger.debug(peram_list)

        # Format of preamble:
        # format, type, points, count, xincrement, xorigin, xreference, yincrement, yorigin, yreference
        pre = Preamble(
            format=peram_list[0],
            type=peram_list[1],
            points=int(peram_list[2]),
            # peram_list[3] is count, not used directly in Preamble dataclass here
            xinc=float(peram_list[4]),
            xorg=float(peram_list[5]),
            xref=float(peram_list[6]),
            yinc=float(peram_list[7]),
            yorg=float(peram_list[8]),
            yref=float(peram_list[9])
        )
        return pre
        
    def _read_wave_data(self, source: str) -> np.ndarray:

        self._wait()
        self._send_command(f':WAVeform:SOURce {source}')
        
        self._wait()
        
        self._logger.debug(f"Reading data from {source}")

        self._send_command(':WAVeform:FORMat BYTE')

        if source != "FFT":
            self._send_command(':WAVeform:POINts:MODE RAW')

        self._logger.debug('Reading points')

        self._wait()

        self._logger.debug('Reading data')

        raw_data: bytes = self._query_raw(':WAVeform:DATA?')
        # Assuming _read_to_np handles the conversion from raw bytes (including header) to np.ndarray of numbers
        data: np.ndarray = self._read_to_np(raw_data) 
        return data
    
    def lock_panel(self, lock: bool = True) -> None:
        """
        Locks the panel of the instrument

        Args:
            lock (bool): True to lock the panel, False to unlock it
        """
        if lock:
            self._send_command(":SYSTem:LOCK ON")
        else:
            self._send_command(":SYSTem:LOCK OFF")

    def auto_scale(self) -> None:
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
        scale_str: str = self._query(":TIMebase:SCALe?")
        position_str: str = self._query(":TIMebase:POSition?")
        return [np.float64(scale_str), np.float64(position_str)]
    
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
        
        scale_str: str = self._query(f":CHANnel{channel}:SCALe?")
        offset_str: str = self._query(f":CHANnel{channel}:OFFSet?")
        return [np.float64(scale_str), np.float64(offset_str)]
        
        
    def configure_trigger(self, channel: int, level: float, source: Optional[str] = None, trigger_type: str = "HIGH", slope: str = "POS", mode: str = "EDGE") -> None:
        """
        Sets the trigger for the oscilloscope.
        
        :param channel: The channel to set the trigger for (used if source is None or a channel itself)
        :param level: The trigger level in volts
        :param source: The source of the trigger. Default behaviour is to use the channel. Valid options CHANnel<n> | EXTernal | LINE | WGEN
        :param trigger_type: The type of trigger. Default is 'HIGH' (Note: this param seems unused in current logic for level setting)
        :param slope: The slope of the trigger. Default is 'POS'
        :param mode: The trigger mode. Default is 'EDGE'
        """
        
        # Validate the primary channel argument first
        self.config.channels.validate(channel) 
        
        actual_source: str
        source_channel_to_validate = channel # Default to the primary channel for validation if source is complex
        if source is None:
            actual_source = f"CHANnel{channel}"
        else:
            actual_source = source.upper()
            # validate sources
            if actual_source.startswith("CHAN"):
                try:
                    # Extract channel number from source like "CHANNEL1" or "CHAN1"
                    num_str = ""
                    for char_in_source in reversed(actual_source):
                        if char_in_source.isdigit():
                            num_str = char_in_source + num_str
                        elif num_str: # break if we found digits and now a non-digit
                            break
                    if not num_str:
                        raise ValueError("No digits found in channel source string")
                    source_channel_to_validate = int(num_str)
                    self.config.channels.validate(source_channel_to_validate) 
                except (ValueError, IndexError) as e:
                    raise InstrumentParameterError(f"Invalid channel format in source: {source}") from e
            elif actual_source not in ["EXTERNAL", "LINE", "WGEN"]: 
                raise InstrumentParameterError(f"Invalid source {source}. Valid non-channel sources: EXTernal, LINE, WGEN.")

        self._send_command(f':TRIG:SOUR {actual_source}')
        self._send_command(f':TRIGger:LEVel {level}, CHANnel{channel}') 
        
        # Use .get() for slopes and modes to allow passing raw SCPI values if not in map
        scpi_slope = self.config.trigger.slopes.get(slope.upper(), slope)
        scpi_mode = self.config.trigger.modes.get(mode.upper(), mode)

        self._send_command(f':TRIGger:SLOPe {scpi_slope}')
        self._send_command(f':TRIGger:MODE {scpi_mode}')
        self._wait()
        
        self._logger.debug(f"""Trigger set with the following parameters:
                  Trigger Source: {actual_source}
                  Trigger Level for CHAN{channel}: {level} 
                  Trigger Slope: {scpi_slope}
                  Trigger Mode: {scpi_mode}""")
    

    
    def measure_voltage_peak_to_peak(self, channel: int) -> MeasurementResult:
        """
        Measure the peak-to-peak voltage for a specified channel.
        
        Args:
        channel (int): The channel identifier.
        
        Returns:
        MeasurementResult: An object containing the peak-to-peak voltage measurement.
        """
        self.config.channels.validate(channel)

        response_str: str = self._query(f"MEAS:VPP? CHAN{channel}")
        reading: float = float(response_str)

        value_to_return: float | UFloat = reading

        if self.config.measurement_accuracy:
            mode_key = f"vpp_ch{channel}" # Example key: "vpp_ch1"
            self._logger.debug(f"Attempting to find accuracy spec for Vpp on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)
            if spec:
                # Assuming the spec does not require range_value for Vpp, or it's implicit in the spec definition
                sigma = spec.calculate_std_dev(reading, range_value=None)
                if sigma > 0:
                    value_to_return = ufloat(reading, sigma)
                    self._logger.debug(f"Applied accuracy spec '{mode_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{mode_key}' resulted in sigma=0. Returning float.")
            else:
                self._logger.debug(f"No accuracy spec found for Vpp on channel {channel} with key '{mode_key}'. Returning float.")
        else:
            self._logger.debug(f"No measurement_accuracy configuration in instrument for Vpp on channel {channel}. Returning float.")

        measurement_result = MeasurementResult(
            values=value_to_return, # Can be float or UFloat
            units="V",
            instrument=self.config.model,
            measurement_type="P2PV" # Peak-to-Peak Voltage
        )

        self._logger.debug(f"Peak to Peak Voltage (Channel {channel}): {value_to_return}")
        
        return measurement_result

    def measure_rms_voltage(self, channel: int) -> MeasurementResult:
        """
        Measure the root-mean-square (RMS) voltage for a specified channel.
        
        Args:
        channel (int): The channel identifier.
        
        Returns:
        MeasurementResult: An object containing the RMS voltage measurement.
        """
        self.config.channels.validate(channel)

        response_str: str = self._query(f"MEAS:VRMS? CHAN{channel}")
        reading: float = float(response_str)

        value_to_return: float | UFloat = reading

        if self.config.measurement_accuracy:
            mode_key = f"vrms_ch{channel}" # Example key: "vrms_ch1"
            self._logger.debug(f"Attempting to find accuracy spec for Vrms on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)
            if spec:
                sigma = spec.calculate_std_dev(reading, range_value=None)
                if sigma > 0:
                    value_to_return = ufloat(reading, sigma)
                    self._logger.debug(f"Applied accuracy spec '{mode_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{mode_key}' resulted in sigma=0. Returning float.")
            else:
                self._logger.debug(f"No accuracy spec found for Vrms on channel {channel} with key '{mode_key}'. Returning float.")
        else:
            self._logger.debug(f"No measurement_accuracy configuration in instrument for Vrms on channel {channel}. Returning float.")
        
        self._logger.debug(f"RMS Voltage (Channel {channel}): {value_to_return}")
        
        measurement_result = MeasurementResult(
            values=value_to_return, # Can be float or UFloat
            instrument=self.config.model,
            units="V",
            measurement_type="rms_voltage" # Consistent naming
        )
        return measurement_result

    def read_channels(self, *channels: Union[int, List[int], Tuple[int, ...]], points: Optional[int] = None, runAfter: bool = True, timebase: Optional[float] = None) -> ChannelReadingResult:
        """
        Reads the specified channels from the oscilloscope.
        
        Args:
        *channels (Union[int, List[int], Tuple[int,...]]): A variable number of channel numbers or a single list/tuple of channel numbers.
        points (Optional[int]): Deprecated. Use set_time_axis instead.
        runAfter (bool): Parameter seems unused in current implementation.
        timebase (Optional[float]): The timebase scale to use for the measurement.
        
        Returns:
        ChannelReadingResult: A ChannelReadingResult object containing the measurement results.
        """
        
        processed_channels: List[int]
        if not channels:
            raise InstrumentParameterError("No channels specified.")
        
        # Type check and process channels argument
        first_arg = channels[0]
        if isinstance(first_arg, (list, tuple)) and len(channels) == 1:
            if not all(isinstance(ch_num, int) for ch_num in first_arg):
                raise InstrumentParameterError("All elements in channel list/tuple must be integers.")
            processed_channels = list(first_arg)
        elif all(isinstance(ch_num, int) for ch_num in channels):
            processed_channels = list(channels) # type: ignore [assignment]
        else:
            raise InstrumentParameterError("Invalid channel arguments. Must be integers or a single list/tuple of integers.")

        if not processed_channels:
             raise InstrumentParameterError("No channels specified in the list/tuple.")

        if timebase is not None:
            # Assuming get_time_axis returns [scale, position]
            current_time_axis = self.get_time_axis()
            self.set_time_axis(scale=timebase, position=current_time_axis[1]) 

        if points is not None:
            self._logger.debug(f"Points argument is deprecated (value: {points}). Use set_time_axis instead.")


        self._logger.debug("starting channel read")

        for ch_num_val in processed_channels:
            self.config.channels.validate(ch_num_val)

        sampling_rate_float: float = float(self.get_sampling_rate())
        channel_commands_str: str = ', '.join(f"CHANnel{ch}" for ch in processed_channels)

        acq_type_str: str = self.get_acquisition_type()
        
        if acq_type_str == "AVERAGE":
            self._logger.debug("AVERAGE acquisition type detected - using special sequence")
            avg_count_int: int = self.get_acquisition_average_count()
            self._logger.debug(f"Current average count: {avg_count_int}")
            self._send_command(":ACQuire:COMPlete 100")
            self._send_command(":STOP")
            self._wait()
            
            sweep_orig_str: str = self._query(":TRIGger:SWEep?").strip()
            self._send_command(":TRIGger:SWEep AUTO")
            self._send_command(f"DIGitize {channel_commands_str}", skip_check=True)
            self._send_command(":TRIGger:FORCe", skip_check=True)
            self._send_command("*OPC")
            self._logger.debug("Waiting for acquisition to complete …")
            self._wait()
            self._send_command(":TRIGger:FORCe", skip_check=True)
            self._logger.debug("Waiting for acquisition to complete …")
            self._wait()
            self._send_command(f":TRIGger:SWEep {sweep_orig_str}", skip_check=True)
            self.clear_status()
        else:
            self._send_command(f"DIGitize {channel_commands_str}")

        self._send_command(f':WAVeform:SOURce CHANnel{processed_channels[0]}')
        self._send_command(':WAVeform:FORMat BYTE')
        self._send_command(':WAVeform:POINts:MODE RAW')
        
        pream: Preamble = self._read_preamble()

        time_values_np: Optional[np.ndarray] = None
        measurement_results_dict: Dict[str, np.ndarray] = {}

        for ch_num_loop in processed_channels:
            # Reread preamble for each channel if y-scaling can differ
            # self._send_command(f':WAVeform:SOURce CHANnel{ch_num_loop}') # Set source for preamble
            # current_pream = self._read_preamble() # Potentially different yinc, yorg, yref per channel
            # voltages_np: np.ndarray = (
            #     self._read_wave_data(f"CHANnel{ch_num_loop}") - current_pream.yref 
            # ) * current_pream.yinc + current_pream.yorg
            # Using common preamble for now as per original logic
            voltages_np: np.ndarray = (
                self._read_wave_data(f"CHANnel{ch_num_loop}") - pream.yref
            ) * pream.yinc + pream.yorg


            if time_values_np is None:
                n_pts_int: int = len(voltages_np)
                time_values_np = (
                    np.arange(n_pts_int) - pream.xref # xref from first channel's preamble
                ) * pream.xinc + pream.xorg # xinc, xorg from first channel's preamble
            
            measurement_results_dict[f"Channel {ch_num_loop} (V)"] = voltages_np
        
        if time_values_np is None: 
            raise RuntimeError("Time values were not generated during channel read.")

        return ChannelReadingResult(
           instrument=self.config.model,
           units="V",
           measurement_type="ChannelVoltageTime",
           sampling_rate=sampling_rate_float,
           values=pl.DataFrame({
                "Time (s)": time_values_np,
                **measurement_results_dict
           })
        )
    
    def get_sampling_rate(self) -> float:
        """
        Get the current sampling rate of the oscilloscope.
        Returns:
            float: The sampling rate in Hz.
        """
        response_str: str = self._query(":ACQuire:SRATe?")
        sampling_rate_float: float = np.float64(response_str)
        return sampling_rate_float
    
    def get_probe_attenuation(self, channel: int) -> str:
        """
        Gets the probe attenuation for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to get the probe attenuation for.

        Returns:
            str: The probe attenuation value (e.g., '10:1', '1:1').
        """
        self.config.channels.validate(channel)
        response_str: str = self._query(f"CHANnel{channel}:PROBe?").strip()
        return f"{response_str}:1" 
        
    def set_probe_attenuation(self, channel: int, scale: int) -> None:
        """
        Sets the probe scale for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to set the scale for.
            scale (int): The probe scale value (e.g., 10 for 10:1, 1 for 1:1).
                         This 'scale' is used as a key in config.
        """
        self.config.channels.validate(channel)
        
        # Assuming self.config.channels is a list of ChannelConfig objects, 0-indexed
        # And ChannelConfig has a probe_attenuation dict like {10: "10.0", 1: "1.0"}
        channel_config = self.config.channels.get_channel(channel) # Assuming a getter method
        if channel_config is None or scale not in channel_config.probe_attenuation:
             raise InstrumentParameterError(f"Scale {scale} not defined in probe_attenuation for channel {channel}")
        
        scpi_scale_value = channel_config.probe_attenuation[scale]
        self._send_command(f":CHANnel{channel}:PROBe {scpi_scale_value}")

        self._logger.debug(f"Set probe scale to {scale}:1 for channel {channel}.")

    def set_acquisition_time(self, time: float) -> None:
        """
        Set the total acquisition time for the oscilloscope.

        Args:
            time (float): The total acquisition time in seconds.
        """
        self._send_command(f":TIMebase:MAIN:RANGe {time}")

    def set_sample_rate(self, rate: str) -> None:
        """
        Sets the sample rate for the oscilloscope.

        Args:
        rate (str): The desired sample rate. Valid values are 'MAX' and 'AUTO'. Case-insensitive.
        """
        rate_upper: str = rate.upper()
        valid_values: List[str] = ["MAX", "AUTO"]
        if rate_upper not in valid_values:
            raise InstrumentParameterError(f"Invalid rate: {rate}. Supported values are: {valid_values}")
        self._send_command(f"ACQuire:SRATe {rate_upper}")

    def set_bandwidth_limit(self, channel: int, bandwidth: Union[str, float]) -> None:
        """
        Sets the bandwidth limit for a specified channel.
        Args:
            channel (int): The channel number.
            bandwidth (Union[str, float]): The bandwidth limit (e.g., "20M", 20e6, or "FULL").
        """
        self.config.channels.validate(channel)
        self._send_command(f"CHANnel{channel}:BANDwidth {bandwidth}")

    @ConfigRequires("function_generator")
    def wave_gen(self, state: bool) -> None:
        """
        Enable or disable the waveform generator of the oscilloscope.
        
        Args:
        state (bool): True to enable ('ON'), False to disable ('OFF').
        """
        self._send_command(f"WGEN:OUTP {'ON' if state else 'OFF'}")

    @ConfigRequires("function_generator")
    def set_wave_gen_func(self, func_type: str) -> None:
        """
        Set the waveform function for the oscilloscope's waveform generator.
        
        Args:
        func_type (str): The desired function (e.g., 'SIN', 'SQUARE'). Case-insensitive.
        """
        func_type_upper = func_type.upper()
        if self.config.function_generator is None: # Should be caught by ConfigRequires but good for type checker
            raise InstrumentConfigurationError("Function generator not configured.")
        if func_type_upper not in self.config.function_generator.waveform_types:
            raise InstrumentParameterError(f"Unsupported waveform type: {func_type}. Supported: {list(self.config.function_generator.waveform_types.keys())}")
        
        self._send_command(f"WGEN:FUNC {self.config.function_generator.waveform_types[func_type_upper]}")

    @ConfigRequires("function_generator")
    def set_wave_gen_freq(self, freq: float) -> None:
        """
        Set the frequency for the waveform generator.
        
        Args:
        freq (float): The desired frequency for the waveform generator in Hz.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        validated_freq = self.config.function_generator.frequency.in_range(freq)
        self._send_command(f"WGEN:FREQ {validated_freq}")

    @ConfigRequires("function_generator")
    def set_wave_gen_amp(self, amp: float) -> None:
        """
        Set the amplitude for the waveform generator.
        
        Args:
        amp (float): The desired amplitude for the waveform generator in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        validated_amp = self.config.function_generator.amplitude.in_range(amp)
        self._send_command(f"WGEN:VOLT {validated_amp}")

    @ConfigRequires("function_generator")
    def set_wave_gen_offset(self, offset: float) -> None:
        """
        Set the voltage offset for the waveform generator.
        
        Args:
        offset (float): The desired voltage offset for the waveform generator in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        validated_offset = self.config.function_generator.offset.in_range(offset)
        self._send_command(f"WGEN:VOLT:OFFSet {validated_offset}")

    @ConfigRequires("function_generator")
    def set_wgen_sin(self, amp: float, offset: float, freq: float) -> None:
        """Sets the waveform generator to a sine wave.

        :param amp: The amplitude of the sine wave in volts
        :param offset: The offset of the sine wave in volts
        :param freq: The frequency of the sine wave in Hz.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        self._send_command('WGEN:FUNCtion SINusoid')
        self._send_command(f':WGEN:VOLTage {self.config.function_generator.amplitude.in_range(amp)}')
        self._send_command(f':WGEN:VOLTage:OFFSet {self.config.function_generator.offset.in_range(offset)}')
        self._send_command(f':WGEN:FREQuency {self.config.function_generator.frequency.in_range(freq)}')


    @ConfigRequires("function_generator")
    def set_wgen_square(self, v0: float, v1: float, freq: float, dutyCycle: int) -> None:
        """Sets the waveform generator to a square wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the square wave in Hz.
        :param dutyCycle: The duty cycle (1% to 99%).
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        def clamp_duty(number: int) -> int:
            return max(1, min(number, 99))

        self._send_command('WGEN:FUNCtion SQUare')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}') 
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}')
        self._send_command(f':WGEN:FREQuency {self.config.function_generator.frequency.in_range(freq)}')
        self._send_command(f':WGEN:FUNCtion:SQUare:DCYCle {clamp_duty(dutyCycle)}')


    @ConfigRequires("function_generator")
    def set_wgen_ramp(self, v0: float, v1: float, freq: float, symmetry: int) -> None:
        """Sets the waveform generator to a ramp wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the ramp wave in Hz.
        :param symmetry: Symmetry (0% to 100%).
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        def clamp_symmetry(number: int) -> int:
            return max(0, min(number, 100))

        self._send_command('WGEN:FUNCtion RAMP')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}')
        self._send_command(f':WGEN:FREQuency {self.config.function_generator.frequency.in_range(freq)}')
        self._send_command(f':WGEN:FUNCtion:RAMP:SYMMetry {clamp_symmetry(symmetry)}')


    @ConfigRequires("function_generator")
    def set_wgen_pulse(self, v0: float, v1: float, period: float, pulseWidth: float) -> None:
        """Sets the waveform generator to a pulse wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param period: The period of the pulse wave in seconds.
        :param pulseWidth: The pulse width in seconds.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        # Add proper clamping for period and pulseWidth based on instrument specs if available
        # For example:
        # validated_period = self.config.function_generator.pulse_period.in_range(period)
        # validated_pulse_width = self.config.function_generator.pulse_width.in_range(pulseWidth, period=validated_period)


        self._send_command('WGEN:FUNCtion PULSe')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}')
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}')
        self._send_command(f':WGEN:PERiod {period}') 
        self._send_command(f':WGEN:FUNCtion:PULSe:WIDTh {pulseWidth}')


    @ConfigRequires("function_generator")
    def set_wgen_dc(self, offset: float) -> None:
        """Sets the waveform generator to a DC wave.

        :param offset: The offset of the DC wave in volts
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        self._send_command('WGEN:FUNCtion DC')
        self._send_command(f':WGEN:VOLTage:OFFSet {self.config.function_generator.offset.in_range(offset)}')


    @ConfigRequires("function_generator")
    def set_wgen_noise(self, v0: float, v1: float, offset: float) -> None: 
        """Sets the waveform generator to a noise wave.

        :param v0: The 'low' amplitude component or similar parameter for noise.
        :param v1: The 'high' amplitude component or similar parameter for noise.
        :param offset: The offset of the noise wave in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError("Function generator not configured.")
        self._send_command('WGEN:FUNCtion NOISe')
        self._send_command(f':WGEN:VOLTage:LOW {self.config.function_generator.amplitude.in_range(v0)}') 
        self._send_command(f':WGEN:VOLTage:HIGH {self.config.function_generator.amplitude.in_range(v1)}') 
        self._send_command(f':WGEN:VOLTage:OFFSet {self.config.function_generator.offset.in_range(offset)}')

    def display_channel(self, channels: Union[int, List[int]], state: bool = True) -> None:
        """
        Display or hide the specified channel(s) on the oscilloscope.
        
        Args:
        channels (Union[int, List[int]]): A single channel number or a list of channel numbers.
        state (bool): True to display (ON), False to hide (OFF). Default is True.
        """
        ch_list: List[int]
        if isinstance(channels, int):
            ch_list = [channels]
        elif isinstance(channels, list) and all(isinstance(ch, int) for ch in channels):
            ch_list = channels
        else:
            raise InstrumentParameterError("channels must be an int or a list of ints")
        
        for ch_num in ch_list:
            self.config.channels.validate(ch_num)
            self._send_command(f"CHANnel{ch_num}:DISPlay {'ON' if state else 'OFF'}")

    @ConfigRequires("fft")
    def fft_display(self, state: bool = True) -> None:
        """
        Switches on or off the FFT display.

        :param state: True to enable FFT display, False to disable.
        """
        self._send_command(f":FFT:DISPlay {'ON' if state else 'OFF'}")
        self._logger.debug(f"FFT display {'enabled' if state else 'disabled'}.")
        
    @ConfigRequires("function_generator")
    def function_display(self, state: bool = True) -> None: 
        """
        Switches on or off the function display (e.g. Math or WGEN waveform).

        :param state: True to enable display, False to disable.
        """
        self._send_command(f":FUNCtion:DISPlay {'ON' if state else 'OFF'}") 
        self._logger.debug(f"Function display {'enabled' if state else 'disabled'}.")

    @ConfigRequires("fft")
    def configure_fft(self, source_channel: int, scale: Optional[float] = None, offset: Optional[float] = None, span: Optional[float] = None,  window_type: str = 'HANNing', units: str = 'DECibel', display: bool = True) -> None:
        """
        Configure the oscilloscope to perform an FFT on the specified channel.

        :param source_channel: The channel number to perform FFT on.
        :param scale: The vertical scale of the FFT display. Instrument specific.
        :param offset: The vertical offset of the FFT display. Instrument specific.
        :param span: The frequency span for the FFT. Instrument specific.
        :param window_type: The windowing function. Case-insensitive.
        :param units: The unit for FFT magnitude. Case-insensitive.
        :param display: True to turn FFT display ON, False for OFF.
        """
        if self.config.fft is None: # Should be caught by ConfigRequires
            raise InstrumentConfigurationError("FFT not configured for this instrument.")
        self.config.channels.validate(source_channel)
        
        scpi_window = self.config.fft.window_types.get(window_type.upper(), window_type.upper())
        scpi_units = self.config.fft.units.get(units.upper(), units.upper())

        self._send_command(f':FFT:SOURce1 CHANnel{source_channel}')
        self._send_command(f':FFT:WINDow {scpi_window}')
        
        if span is not None:
            # Add validation for span if available in config.fft.span_range
            self._send_command(f':FFT:SPAn {span}')
        
        self._send_command(f':FFT:VTYPe {scpi_units}')
        
        if scale is not None:
            # Add validation for scale if available in config.fft.scale_range
            self._send_command(f':FFT:SCALe {scale}') 
        
        if offset is not None:
            # Add validation for offset if available in config.fft.offset_range
            self._send_command(f':FFT:OFFSet {offset}')
            
        self._send_command(f':FFT:DISPlay {"ON" if display else "OFF"}')

        self._logger.debug(f"FFT configured for channel {source_channel}.")

    def _convert_binary_block_to_data(self, binary_block: bytes) -> np.ndarray: 
        """
        Converts a SCPI binary block to a NumPy array.
        Assumes format like #<N><LengthBytes><DataBytes>
        This method's original implementation was problematic.
        This is a more standard interpretation of SCPI binary blocks.
        The actual data type (e.g., int8, int16) depends on :WAVeform:FORMat.
        """
        if not binary_block.startswith(b'#'):
            raise ValueError("Invalid binary block format: does not start with #")
        
        len_digits = int(binary_block[1:2].decode('ascii')) 
        data_len = int(binary_block[2 : 2 + len_digits].decode('ascii'))
        
        actual_data_start_index = 2 + len_digits
        raw_data_bytes = binary_block[actual_data_start_index : actual_data_start_index + data_len]
        
        # This part is highly dependent on :WAVeform:FORMat (BYTE, WORD, ASCii)
        # Assuming BYTE format -> 8-bit signed int as per _read_wave_data
        # If _read_to_np in _read_wave_data already handles this, this method might be simplified
        # or its usage re-evaluated.
        dt = np.dtype(np.int8) 
        data_array = np.frombuffer(raw_data_bytes, dtype=dt)
        
        if len(data_array) != data_len: # For BYTE format, len(data_array) should be data_len
             self._logger.debug(f"Warning: Binary block data length mismatch. Expected {data_len}, got {len(data_array)}")

        return data_array


    @ConfigRequires("fft")
    def read_fft_data(self) -> FFTResult: 
        """
        Reads FFT data from the oscilloscope. Assumes FFT is already configured.

        :return: An FFTResult object containing the FFT data.
        """
        self._logger.debug('Initiating FFT data read.')
        
        # _read_wave_data("FFT") should return numeric data after _read_to_np processing
        # which includes stripping the SCPI binary header and converting to numbers.
        raw_numeric_data_fft: np.ndarray = self._read_wave_data("FFT") 
        preamble_fft: Preamble = self._read_preamble() # Preamble for FFT source

        scaled_data_fft: np.ndarray = (raw_numeric_data_fft - preamble_fft.yref) * preamble_fft.yinc + preamble_fft.yorg

        num_points_fft: int = preamble_fft.points 
        frequency_axis_fft: np.ndarray = (np.arange(num_points_fft) - preamble_fft.xref) * preamble_fft.xinc + preamble_fft.xorg
        
        units_str: str = self._query(":FFT:VTYPe?").strip().upper() 
        y_label_str: str
        if units_str == "DEC": # DECibel
            y_label_str = "Magnitude (dB)"
        elif units_str == "VRMS":
            y_label_str = "Magnitude (Vrms)"
        elif units_str == "DBM":
             y_label_str = "Magnitude (dBm)"
        else:
            y_label_str = f"Magnitude ({units_str})"


        return FFTResult(
            instrument=self.config.model,
            units=units_str, 
            measurement_type="FFT",
            values=pl.DataFrame({
                "Frequency (Hz)": frequency_axis_fft,
                y_label_str: scaled_data_fft
            })
        )

    def screenshot(self) -> Image.Image: 
        """
        Capture a screenshot of the oscilloscope display.

        :return Image: A PIL Image object containing the screenshot.
        """
        binary_data_response: bytes = self._query_raw(":DISPlay:DATA? PNG, COLor")
        
        if not binary_data_response.startswith(b'#'):
            raise ValueError("Invalid screenshot data format: does not start with #")

        length_of_length_field: int = int(chr(binary_data_response[1]))
        png_data_length_str: str = binary_data_response[2 : 2 + length_of_length_field].decode('ascii')
        png_data_length: int = int(png_data_length_str)
        png_data_start_index: int = 2 + length_of_length_field
        image_data_bytes: bytes = binary_data_response[png_data_start_index : png_data_start_index + png_data_length]
        
        return Image.open(BytesIO(image_data_bytes))


    @ConfigRequires("franalysis")
    @ConfigRequires("function_generator")
    def franalysis_sweep(self, input_channel: int, output_channel: int, start_freq: float, stop_freq: float, amplitude: float, points: int = 10, trace: str = "none", load: str = "onemeg", disable_on_complete: bool = True) -> FRanalysisResult:
        """
        Perform a frequency response analysis sweep.

        Returns:
            FRanalysisResult: Containing the frequency response analysis data.
        """
        if self.config.function_generator is None or self.config.franalysis is None:
            raise InstrumentConfigurationError("Function generator or FRANalysis not configured.")

        self.config.channels.validate(input_channel)
        self.config.channels.validate(output_channel)

        self._send_command(":STOP")
        self._send_command(":FRANalysis:ENABle ON")

        self._send_command(f":FRANalysis:SOURce:INPut CHANnel{input_channel}")
        self._send_command(f":FRANalysis:SOURce:OUTPut CHANnel{output_channel}")

        self._send_command(f":FRANalysis:FREQuency:MODE SWEep")
        self._send_command(f":FRANalysis:SWEep:POINts {points}") 
        
        validated_start_freq = self.config.function_generator.frequency.in_range(start_freq)
        validated_stop_freq = self.config.function_generator.frequency.in_range(stop_freq)
        validated_amplitude = self.config.function_generator.amplitude.in_range(amplitude)

        self._send_command(f":FRANalysis:FREQuency:STARt {validated_start_freq}Hz")
        self._send_command(f":FRANalysis:FREQuency:STOP {validated_stop_freq}Hz")
    
        scpi_load = self.config.franalysis.load.get(load.lower(), load) 
        scpi_trace = self.config.franalysis.trace.get(trace.lower(), trace)

        self._send_command(f":FRANalysis:WGEN:LOAD {scpi_load}")
        self._send_command(f":FRANalysis:TRACE {scpi_trace}")

        self._send_command(f":WGEN:VOLTage {validated_amplitude}") 

        self._send_command("*OPC")
        self._send_command(":FRANalysis:RUN")
        self._wait()

        raw_block_bytes: bytes = self._query_raw(":FRANalysis:DATA?")
        
        if not raw_block_bytes.startswith(b'#'):
             raise ValueError("Invalid FRANalysis data format: does not start with #")

        hdr_len_digits: int = int(chr(raw_block_bytes[1]))
        data_actual_len_str: str = raw_block_bytes[2 : 2 + hdr_len_digits].decode('ascii')
        data_actual_len: int = int(data_actual_len_str)
        text_data_start: int = 2 + hdr_len_digits
        text_data_str: str = raw_block_bytes[text_data_start : text_data_start + data_actual_len].decode('utf-8')

        if disable_on_complete:
            self._send_command(":FRANalysis:ENABle OFF")

        df_results: pl.DataFrame = pl.read_csv(StringIO(text_data_str))

        return FRanalysisResult(
            instrument=self.config.model, 
            units="Mixed", 
            measurement_type="franalysis",
            values=df_results.drop_nulls() 
        )

    @ConfigRequires("franalysis")
    def franalysis_disable(self, state: bool = True) -> None: 
        """
        Disables (if state=True) or enables (if state=False) the frequency response analysis feature.
        :param state: True to disable FRANalysis, False to enable.
        """
        self._send_command(f":FRANalysis:ENABle {'OFF' if state else 'ON'}") 
        self._logger.debug(f"Frequency response analysis is {'disabled' if state else 'enabled'}.")

    def set_acquisition_type(self, acq_type: str) -> None:
        """
        Select the oscilloscope acquisition algorithm.
        (Case-insensitive for acq_type).
        """
        acq_type_upper: str = acq_type.upper()
        if acq_type_upper not in _ACQ_TYPE_MAP:
            raise InstrumentParameterError(f"Unknown acquisition type: {acq_type}. Supported: {list(_ACQ_TYPE_MAP.keys())}")

        current_mode_query: str = self._query(":ACQuire:MODE?").strip().upper() # Ensure SCPI response is upper for comparison
        # Compare with the SCPI command part, not the friendly name
        if acq_type_upper == "AVERAGE" and current_mode_query == _ACQ_MODE_MAP["SEGMENTED"].upper()[:4]: 
            raise InstrumentParameterError("AVERAGE mode is unavailable in SEGMENTED acquisition.")

        self._send_command(f":ACQuire:TYPE {_ACQ_TYPE_MAP[acq_type_upper]}")
        self._wait()
        self._logger.debug(f"Acquisition TYPE set → {acq_type_upper}")

    def get_acquisition_type(self) -> str:
        """
        Returns current acquisition type (e.g., "NORMAL", "AVERAGE").
        """
        reverse_map: Dict[str, str] = {v.upper()[:4]: k for k, v in _ACQ_TYPE_MAP.items()}
        resp_str: str = self._query(":ACQuire:TYPE?").strip().upper() 
        
        # Match based on the typical SCPI response prefix (e.g., "NORM" for "NORMal")
        for scpi_prefix, friendly_name in reverse_map.items():
            if resp_str.startswith(scpi_prefix):
                return friendly_name
        return resp_str 

    def set_acquisition_average_count(self, count: int) -> None:
        """
        Set the running-average length for AVERAGE mode.
        2 <= count <= 65536 (Keysight limit).
        """
        _validate_range(count, 2, 65_536, "Average count")
        if self.get_acquisition_type() != "AVERAGE":
            raise InstrumentParameterError("Average count can only be set when acquisition type is AVERAGE.")
        self._send_command(f":ACQuire:COUNt {count}")
        self._wait()
        self._logger.debug(f"AVERAGE count set → {count}")

    def get_acquisition_average_count(self) -> int:
        """Integer average count (valid only when acquisition type == AVERAGE)."""
        return int(self._query(":ACQuire:COUNt?"))

    def set_acquisition_mode(self, mode: str) -> None:
        """
        Select real-time or segmented memory acquisition.
        (Case-insensitive for mode).
        """
        mode_upper: str = mode.upper()
        if mode_upper not in _ACQ_MODE_MAP:
            raise InstrumentParameterError(f"Unknown acquisition mode: {mode}. Supported: {list(_ACQ_MODE_MAP.keys())}")

        self._send_command(f":ACQuire:MODE {_ACQ_MODE_MAP[mode_upper]}")
        self._wait()
        self._logger.debug(f"Acquisition MODE set → {mode_upper}")

    def get_acquisition_mode(self) -> str:
        """Return "REAL_TIME" or "SEGMENTED"."""
        reverse_map: Dict[str, str] = {v.upper()[:4]: k for k, v in _ACQ_MODE_MAP.items()} 
        resp_str: str = self._query(":ACQuire:MODE?").strip().upper()
        
        for scpi_prefix, friendly_name in reverse_map.items():
            if resp_str.startswith(scpi_prefix):
                return friendly_name
        return resp_str 

    def set_segmented_count(self, count: int) -> None:
        """
        Configure number of memory segments for SEGMENTED acquisitions.
        Default Keysight limit: 2 <= count <= 500 (check instrument specs)
        """
        if self.get_acquisition_mode() != "SEGMENTED":
            raise InstrumentParameterError("Segmented count can only be set while in SEGMENTED acquisition mode.")
        # Use actual instrument limits from config if available
        # min_seg = self.config.segmented_memory.min_count if self.config.segmented_memory else 2
        # max_seg = self.config.segmented_memory.max_count if self.config.segmented_memory else 500
        _validate_range(count, 2, 500, "Segmented count") # Using example limits
        self._send_command(f":ACQuire:SEGMented:COUNt {count}")
        self._wait()
        self._logger.debug(f"Segmented COUNT set → {count}")

    def get_segmented_count(self) -> int:
        """Number of segments currently configured (SEGMENTED mode only)."""
        return int(self._query(":ACQuire:SEGMented:COUNt?"))

    def set_segment_index(self, index: int) -> None:
        """
        Select which memory segment is active for readback.
        1 <= index <= get_segmented_count()
        """
        total_segments: int = self.get_segmented_count()
        _validate_range(index, 1, total_segments, "Segment index")
        self._send_command(f":ACQuire:SEGMented:INDex {index}")
        self._wait()

    def get_segment_index(self) -> int:
        """Index (1-based) of the currently selected memory segment."""
        return int(self._query(":ACQuire:SEGMented:INDex?"))

    def analyze_all_segments(self) -> None:
        """
        Execute the scope's *Analyze Segments* soft-key.
        Requires scope to be stopped and in SEGMENTED mode.
        """
        if self.get_acquisition_mode() != "SEGMENTED":
            raise InstrumentParameterError("Segment analysis requires SEGMENTED mode.")
        self._send_command(":ACQuire:SEGMented:ANALyze")
        self._wait() 

    def get_acquire_points(self) -> int:
        """
        Hardware points actually *acquired* for the next waveform transfer.
        """
        return int(self._query(":ACQuire:POINts?"))

    def get_acquisition_sample_rate(self) -> float:
        """
        Current sample rate of acquisition. Equivalent to get_sampling_rate().
        """
        return float(self._query(":ACQuire:SRATe?"))

    def get_acquire_setup(self) -> Dict[str, str]:
        """
        Return a parsed dictionary of the scope's :ACQuire? status string.
        """
        raw_str: str = self._query(":ACQuire?").strip()
        parts: List[str] = [p.strip() for p in raw_str.split(';')]
        setup_dict: Dict[str, str] = {}
        for part in parts:
            kv = part.split(maxsplit=1) 
            if len(kv) == 2:
                setup_dict[kv[0]] = kv[1]
        return setup_dict

def _validate_range(value: int, lo: int, hi: int, name: str) -> None:
    if not lo <= value <= hi:
        raise InstrumentParameterError(f"{name} out of range ({lo}-{hi}): {value}")
