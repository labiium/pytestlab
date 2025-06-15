from __future__ import annotations

import asyncio # Added import
import time
import numpy as np
import polars as pl
from typing import Any, Dict, List, Optional, Tuple, Type, Union, Self
from dataclasses import dataclass
from PIL import Image
from io import BytesIO, StringIO
from uncertainties import ufloat
from uncertainties.core import UFloat
from ..analysis import fft as analysis_fft
import warnings

from .instrument import Instrument
# from ..config import OscilloscopeConfig, ConfigRequires # OscilloscopeConfig is V2
from ..config.oscilloscope_config import OscilloscopeConfig # Import the V2 config
from ..experiments import MeasurementResult
from ..common.enums import AcquisitionType, SCPIOnOff, TriggerSlope, WaveformType
from ..common.health import HealthReport, HealthStatus
from ..errors import InstrumentConfigurationError, InstrumentParameterError, InstrumentDataError
from pydantic import validate_call

async def _validate_range(val, minval, maxval, name):
    if not (minval <= val <= maxval):
        raise InstrumentParameterError(
            parameter=name,
            value=val,
            valid_range=(minval, maxval),
            message=f"{name} must be between {minval} and {maxval}.",
        )

_ACQ_TYPE_MAP = {
    AcquisitionType.NORMAL: "NORMal",
    AcquisitionType.AVERAGE: "AVERage",
    AcquisitionType.HIGH_RES: "HRESolution",
    AcquisitionType.PEAK: "PEAK"
}

_ACQ_MODE_MAP = {
    "REAL_TIME": "RTIMe",
    "SEGMENTED": "SEGMented"
}

class ChannelReadingResult(MeasurementResult):
    """A result class for oscilloscope channel readings (time, voltage, etc)."""
    pass

class FFTResult(MeasurementResult):
    """A result class for FFT data from the oscilloscope."""
    pass

class FRanalysisResult(MeasurementResult):
    """A result class for frequency response analysis data."""
    pass


# Forward declarations for type hints within facade classes
class Oscilloscope:
    pass

class ScopeChannelFacade:
    """Provides a simplified, chainable interface for a single oscilloscope channel.

    This facade abstracts the underlying SCPI commands for common channel
    operations, allowing for more readable and fluent test scripts. For example:
    `await scope.channel(1).setup(scale=0.5, offset=0).enable()`

    Attributes:
        _scope: The parent `Oscilloscope` instance.
        _channel: The channel number this facade controls.
    """
    def __init__(self, scope: 'Oscilloscope', channel_num: int):
        self._scope = scope
        self._channel = channel_num

    @validate_call
    async def setup(self, scale: Optional[float] = None, position: Optional[float] = None, offset: Optional[float] = None, coupling: Optional[str] = None, probe_attenuation: Optional[int] = None, bandwidth_limit: Optional[Union[str, float]] = None) -> Self:
        """Configures multiple settings for the channel in a single call.

        This method allows setting the vertical scale, position/offset, coupling,
        probe attenuation, and bandwidth limit. Any parameter left as `None` will
        not be changed.

        Args:
            scale: The vertical scale in volts per division.
            position: The vertical position in divisions from the center.
            offset: The vertical offset in volts. 'offset' is often preferred
                    over 'position' as it's independent of the scale.
            coupling: The input coupling ("AC" or "DC").
            probe_attenuation: The attenuation factor of the probe (e.g., 10 for 10:1).
            bandwidth_limit: The bandwidth limit to apply (e.g., "20M" or 20e6).

        Returns:
            The `ScopeChannelFacade` instance for method chaining.
        """
        if scale is not None:
            current_offset_val = (await self._scope.get_channel_axis(self._channel))[1] if offset is None and position is None else (offset or position or 0.0)
            await self._scope.set_channel_axis(self._channel, scale, current_offset_val)
        elif position is not None or offset is not None: # only position/offset is set
            val_to_set = position if position is not None else offset
            current_scale_val = (await self._scope.get_channel_axis(self._channel))[0]
            await self._scope.set_channel_axis(self._channel, current_scale_val, val_to_set)

        if coupling is not None:
            await self._scope._send_command(f":CHANnel{self._channel}:COUPling {coupling.upper()}")
            self._scope._logger.debug(f"Channel {self._channel} coupling set to {coupling.upper()}")

        if probe_attenuation is not None:
            await self._scope.set_probe_attenuation(self._channel, probe_attenuation)
        
        if bandwidth_limit is not None:
            await self._scope.set_bandwidth_limit(self._channel, bandwidth_limit)
            
        return self

    async def enable(self) -> Self:
        """Enables the channel display."""
        await self._scope.display_channel(self._channel, True)
        return self

    async def disable(self) -> Self:
        """Disables the channel display."""
        await self._scope.display_channel(self._channel, False)
        return self

    async def measure_peak_to_peak(self) -> MeasurementResult:
        """Performs a peak-to-peak voltage measurement on this channel."""
        return await self._scope.measure_voltage_peak_to_peak(self._channel)

    async def measure_rms(self) -> MeasurementResult:
        """Performs an RMS voltage measurement on this channel."""
        return await self._scope.measure_rms_voltage(self._channel)


class ScopeTriggerFacade:
    """Provides a simplified, chainable interface for the oscilloscope's trigger system.

    This facade abstracts the underlying SCPI commands for trigger operations,
    focusing on common use cases like setting up an edge trigger.

    Attributes:
        _scope: The parent `Oscilloscope` instance.
    """
    def __init__(self, scope: 'Oscilloscope'):
        self._scope = scope

    @validate_call
    async def setup_edge(self, source: str, level: float, slope: TriggerSlope = TriggerSlope.POSITIVE, coupling: Optional[str] = None, mode: str = "EDGE") -> Self:
        """Configures a standard edge trigger.

        Args:
            source: The trigger source (e.g., "CH1", "CH2", "EXT", "LINE").
            level: The trigger level in volts.
            slope: The trigger slope (`TriggerSlope.POSITIVE`, `NEGATIVE`, or `EITHER`).
            coupling: The trigger coupling (e.g., "AC", "DC"). Can be instrument-specific.
            mode: The trigger mode, defaults to "EDGE".

        Returns:
            The `ScopeTriggerFacade` instance for method chaining.
        """
        # Determine channel number if source is like 'CH1' for the level command
        trigger_channel_for_level = 1 # Default or fallback
        if source.upper().startswith("CHAN"):
            try:
                trigger_channel_for_level = int(source[len("CHAN"):])
            except ValueError:
                raise InstrumentParameterError(
                    parameter="source",
                    value=source,
                    message="Invalid trigger source format for channel.",
                )
        elif source.upper().startswith("CH"):
            try:
                trigger_channel_for_level = int(source[len("CH"):])
            except ValueError:
                raise InstrumentParameterError(
                    parameter="source",
                    value=source,
                    message="Invalid trigger source format for channel.",
                )
        
        # The main configure_trigger method handles source validation and mapping.
        await self._scope.configure_trigger(
            channel=trigger_channel_for_level, # This is for the :TRIGger:LEVel CHANnel<n> part
            level=level,
            source=source, # This is for :TRIGger:SOURce part
            slope=slope,
            mode=mode
        )
        # Coupling for trigger is often separate, e.g., :TRIGger:COUPling
        if coupling is not None:
            await self._scope._send_command(f":TRIGger:{mode.upper()}:COUPling {coupling.upper()}") # Assuming edge trigger coupling
            self._scope._logger.debug(f"Trigger coupling set to {coupling.upper()}")
        return self
    
    # Add other trigger setup methods like setup_pulse, setup_pattern etc.


class ScopeAcquisitionFacade:
    """Provides a simplified interface for the oscilloscope's acquisition system.

    This facade manages settings related to how the oscilloscope digitizes
    signals, including acquisition type (e.g., Normal, Averaging), memory mode
    (Real-time vs. Segmented), and sample rates.

    Attributes:
        _scope: The parent `Oscilloscope` instance.
    """
    def __init__(self, scope: 'Oscilloscope'):
        self._scope = scope

    @validate_call
    async def set_acquisition_type(self, acq_type: AcquisitionType) -> None:
        """
        Select the oscilloscope acquisition algorithm.
        """
        scpi_val = _ACQ_TYPE_MAP.get(acq_type)
        if not scpi_val:
            raise InstrumentParameterError(
                parameter="acq_type",
                value=acq_type,
                message="Unsupported acquisition type enum member.",
            )

        current_mode_query: str = (await self._scope._query(":ACQuire:MODE?")).strip().upper()
        if acq_type == AcquisitionType.AVERAGE and current_mode_query == _ACQ_MODE_MAP["SEGMENTED"].upper()[:4]:
            raise InstrumentParameterError(
                parameter="acq_type",
                value="AVERAGE",
                message="AVERAGE mode is unavailable in SEGMENTED acquisition.",
            )

        await self._scope._send_command(f":ACQuire:TYPE {scpi_val}")
        await self._scope._wait()
        self._scope._logger.debug(f"Acquisition TYPE set → {acq_type.name}")

    @validate_call
    async def get_acquisition_type(self) -> str:
        """
        Returns current acquisition type (e.g., "NORMAL", "AVERAGE").
        """
        # Invert _ACQ_TYPE_MAP for lookup: SCPI response -> Enum member name
        # SCPI responses can be short forms (e.g., "NORM" for "NORMal")
        # We need to match based on how the instrument actually responds.
        # A common way is that instrument responds with the short form.
        # Let's assume the instrument responds with a value that can be mapped back.
        resp_str_raw: str = (await self._scope._query(":ACQuire:TYPE?")).strip()
        
        for enum_member, scpi_command_str in _ACQ_TYPE_MAP.items():
            # Check if the response starts with the typical short SCPI command part
            # e.g. "NORM" from "NORMal"
            # This matching logic might need to be more robust based on actual instrument behavior
            if resp_str_raw.upper().startswith(scpi_command_str.upper()[:4]): # Compare first 4 chars
                return enum_member.name # Return the string name of the enum member
        
        self._scope._logger.warning(f"Could not map SCPI response '{resp_str_raw}' to a known AcquisitionType. Returning raw response.")
        return resp_str_raw # Fallback to raw response if no match

    @validate_call
    async def set_acquisition_average_count(self, count: int) -> None:
        """
        Set the running-average length for AVERAGE mode.
        2 <= count <= 65536 (Keysight limit).
        """
        await _validate_range(count, 2, 65_536, "Average count") # Sync
        
        current_acq_type_str = await self.get_acquisition_type()
        if current_acq_type_str != AcquisitionType.AVERAGE.name:
            raise InstrumentParameterError(
                parameter="count",
                message=f"Average count can only be set when acquisition type is AVERAGE, not {current_acq_type_str}.",
            )
        await self._scope._send_command(f":ACQuire:COUNt {count}")
        await self._scope._wait()
        self._scope._logger.debug(f"AVERAGE count set → {count}")

    @validate_call
    async def get_acquisition_average_count(self) -> int:
        """Integer average count (valid only when acquisition type == AVERAGE)."""
        return int(await self._scope._query(":ACQuire:COUNt?"))

    @validate_call
    async def set_acquisition_mode(self, mode: str) -> None:
        """
        Select real-time or segmented memory acquisition.
        (Case-insensitive for mode).
        """
        mode_upper: str = mode.upper()
        scpi_mode_val = _ACQ_MODE_MAP.get(mode_upper)
        if not scpi_mode_val:
            raise InstrumentParameterError(
                parameter="mode",
                value=mode,
                valid_range=list(_ACQ_MODE_MAP.keys()),
                message="Unknown acquisition mode.",
            )

        await self._scope._send_command(f":ACQuire:MODE {scpi_mode_val}")
        await self._scope._wait()
        self._scope._logger.debug(f"Acquisition MODE set → {mode_upper}")

    @validate_call
    async def get_acquisition_mode(self) -> str:
        """Return "REAL_TIME" or "SEGMENTED"."""
        resp_str_raw: str = (await self._scope._query(":ACQuire:MODE?")).strip()
        for friendly_name, scpi_command_str in _ACQ_MODE_MAP.items():
            if resp_str_raw.upper().startswith(scpi_command_str.upper()[:4]):
                return friendly_name
        self._scope._logger.warning(f"Could not map SCPI response '{resp_str_raw}' to a known AcquisitionMode. Returning raw response.")
        return resp_str_raw

    @validate_call
    async def set_segmented_count(self, count: int) -> None:
        """
        Configure number of memory segments for SEGMENTED acquisitions.
        Default Keysight limit: 2 <= count <= 500 (check instrument specs)
        """
        if await self.get_acquisition_mode() != "SEGMENTED":
            raise InstrumentParameterError(
                parameter="count",
                message="Segmented count can only be set while in SEGMENTED acquisition mode.",
            )
        await _validate_range(count, 2, 500, "Segmented count") # Sync
        await self._scope._send_command(f":ACQuire:SEGMented:COUNt {count}")
        await self._scope._wait()
        self._scope._logger.debug(f"Segmented COUNT set → {count}")

    @validate_call
    async def get_segmented_count(self) -> int:
        """Number of segments currently configured (SEGMENTED mode only)."""
        return int(await self._scope._query(":ACQuire:SEGMented:COUNt?"))

    @validate_call
    async def set_segment_index(self, index: int) -> None:
        """
        Select which memory segment is active for readback.
        1 <= index <= get_segmented_count()
        """
        total_segments: int = await self.get_segmented_count()
        await _validate_range(index, 1, total_segments, "Segment index") # Sync
        await self._scope._send_command(f":ACQuire:SEGMented:INDex {index}")
        await self._scope._wait()

    @validate_call
    async def get_segment_index(self) -> int:
        """Index (1-based) of the currently selected memory segment."""
        return int(await self._scope._query(":ACQuire:SEGMented:INDex?"))

    @validate_call
    async def analyze_all_segments(self) -> None:
        """
        Execute the scope's *Analyze Segments* soft-key.
        Requires scope to be stopped and in SEGMENTED mode.
        """
        if await self.get_acquisition_mode() != "SEGMENTED":
            raise InstrumentParameterError(
                message="Segment analysis requires SEGMENTED mode."
            )
        await self._scope._send_command(":ACQuire:SEGMented:ANALyze")
        await self._scope._wait()

    @validate_call
    async def get_acquire_points(self) -> int:
        """
        Hardware points actually *acquired* for the next waveform transfer.
        """
        return int(await self._scope._query(":ACQuire:POINts?"))

    @validate_call
    async def get_acquisition_sample_rate(self) -> float:
        """
        Current sample rate of acquisition. Equivalent to get_sampling_rate().
        """
        return float(await self._scope._query(":ACQuire:SRATe?"))

    @validate_call
    async def get_acquire_setup(self) -> Dict[str, str]:
        """
        Return a parsed dictionary of the scope's :ACQuire? status string.
        """
        raw_str: str = (await self._scope._query(":ACQuire?")).strip()
        parts: List[str] = [p.strip() for p in raw_str.split(';')]
        setup_dict: Dict[str, str] = {}
        for part in parts:
            kv = part.split(maxsplit=1)
            if len(kv) == 2:
                setup_dict[kv[0]] = kv[1]
        return setup_dict

@dataclass
class Preamble:
    """Holds the waveform preamble data from the oscilloscope.

    The preamble contains all the necessary metadata to convert the raw, digitized
    ADC values from the oscilloscope into meaningful time and voltage arrays. It
    describes the scaling and offset factors for both the X (time) and Y (voltage)
    axes.

    Attributes:
        format: Data format (e.g., 'BYTE', 'WORD').
        type: Acquisition type (e.g., 'NORMal', 'AVERage').
        points: The number of data points in the waveform.
        xinc: The time difference between adjacent data points (sampling interval).
        xorg: The time value of the first data point.
        xref: The reference time point (usually the trigger point).
        yinc: The voltage difference for each ADC level (voltage resolution).
        yorg: The voltage value at the vertical center of the screen.
        yref: The ADC level corresponding to the vertical center.
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


class Oscilloscope(Instrument[OscilloscopeConfig]):
    """Drives a digital oscilloscope for waveform acquisition and measurement.

    This class provides a comprehensive, high-level interface for controlling an
    oscilloscope. It builds upon the base `Instrument` class and adds extensive
    functionality specific to oscilloscopes.

    Key features include:
    - Facade-based interfaces for channels, trigger, and acquisition for cleaner code.
    - Methods for reading waveforms, performing automated measurements (e.g., Vpp, Vrms).
    - Support for advanced features like FFT and Frequency Response Analysis (FRA).
    - Built-in waveform generator control if the hardware supports it.
    - Screenshot capability.

    Attributes:
        config: The Pydantic configuration object (`OscilloscopeConfig`)
                containing settings specific to this oscilloscope.
        trigger: A `ScopeTriggerFacade` for configuring trigger settings.
        acquisition: A `ScopeAcquisitionFacade` for acquisition system settings.
    """
    config: OscilloscopeConfig # Type hint for validated config
    # visa_resource is handled by base Instrument or backend through config.address
    def __init__(self, config: OscilloscopeConfig, debug_mode: bool = False, simulate: bool = False, **kwargs: Any) -> None: # config is now non-optional
        """
        Initialize the Oscilloscope class with the given VISA resource and profile information.
        
        Args:
        config (OscilloscopeConfig): Configuration object for the oscilloscope.
        debug_mode (bool): Enable debug mode. (Handled by base or backend)
        simulate (bool): Enable simulation mode. (Handled by base or backend)
        """
        # The config is already validated by the loader to be OscilloscopeConfig V2
        super().__init__(config=config, debug_mode=debug_mode, simulate=simulate, **kwargs) # Pass kwargs
        # Initialize facades
        self.trigger = ScopeTriggerFacade(self)
        self.acquisition = ScopeAcquisitionFacade(self)

    @validate_call
    def channel(self, ch_num: int) -> ScopeChannelFacade:
        """Returns a facade for interacting with a specific channel.

        This method provides a convenient, chainable interface for controlling a
        single oscilloscope channel.

        Args:
            ch_num: The channel number (1-based).

        Returns:
            A `ScopeChannelFacade` object for the specified channel.

        Raises:
            InstrumentParameterError: If the channel number is invalid.
        """
        if not self.config.channels or not (1 <= ch_num <= len(self.config.channels)):
            num_conf_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(
                parameter="ch_num",
                value=ch_num,
                valid_range=(1, num_conf_ch),
                message="Channel number is out of range.",
            )
        return ScopeChannelFacade(self, ch_num)

    @classmethod
    def from_config(cls: Type['Oscilloscope'], config: OscilloscopeConfig, debug_mode: bool = False, **kwargs: Any) -> 'Oscilloscope':
        # This method aligns with the new __init__ signature.
        return cls(config=config, debug_mode=debug_mode, **kwargs)
    
    async def health_check(self) -> HealthReport:
        """
        Performs a basic health check of the oscilloscope instrument.
        
        Returns:
            HealthReport: A report containing the instrument's health status,
                          errors, warnings, and supported features.
        """
        report = HealthReport()
        
        try:
            # Get instrument identification
            report.instrument_idn = await self.id()
            
            # Check for stored errors
            instrument_errors = await self.get_all_errors()
            if instrument_errors:
                report.warnings.extend([f"Stored Error: {code} - {msg}" for code, msg in instrument_errors])

            # Set initial status based on errors
            if not report.errors and not report.warnings:
                report.status = HealthStatus.OK
            elif report.warnings and not report.errors:
                report.status = HealthStatus.WARNING
            else:
                report.status = HealthStatus.ERROR

        except Exception as e:
            report.status = HealthStatus.ERROR
            report.errors.append(f"Health check failed during IDN/Error Query: {str(e)}")

        try:
            # Test basic oscilloscope functionality
            _ = await self.get_time_axis()
            
            # Check supported features based on configuration
            if hasattr(self.config, 'fft') and self.config.fft:
                report.supported_features["fft"] = True
            else:
                report.supported_features["fft"] = False
                
            if hasattr(self.config, 'franalysis') and self.config.franalysis:
                report.supported_features["franalysis"] = True
            else:
                report.supported_features["franalysis"] = False
                
            if hasattr(self.config, 'function_generator') and self.config.function_generator:
                report.supported_features["function_generator"] = True
            else:
                report.supported_features["function_generator"] = False

        except Exception as e:
            report.errors.append(f"Oscilloscope-specific check failed: {str(e)}")

        # Determine backend status
        if hasattr(self, '_backend') and hasattr(self._backend, '__class__'):
            backend_name = self._backend.__class__.__name__
            if "SimBackend" in backend_name:
                report.backend_status = "Simulated"
            elif "VisaBackend" in backend_name:
                report.backend_status = "VISA Connection"
            elif "LambInstrument" in backend_name or "LambBackend" in backend_name:
                report.backend_status = "Lamb Connection"
            else:
                report.backend_status = f"Unknown backend: {backend_name}"
        else:
            report.backend_status = "Backend information unavailable"

        # Final status evaluation
        if report.errors and report.status != HealthStatus.ERROR:
            report.status = HealthStatus.ERROR
        elif report.warnings and report.status == HealthStatus.OK:
            report.status = HealthStatus.WARNING
        
        # If no errors or warnings after all checks, and status is still UNKNOWN, set to OK
        if report.status == HealthStatus.UNKNOWN and not report.errors and not report.warnings:
            report.status = HealthStatus.OK

        return report
    
    async def _read_preamble(self) -> Preamble:
        """Reads and parses the waveform preamble from the oscilloscope.

        The preamble contains essential metadata for interpreting the waveform data,
        such as scaling factors and offsets.

        Returns:
            A `Preamble` dataclass instance.
        """

        peram_str: str = await self._query(':WAVeform:PREamble?')
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
        
    async def _read_wave_data(self, source: str) -> np.ndarray:
        """Reads the raw waveform data block for a given source.

        This internal method configures the waveform transfer format and reads
        the binary data block from the instrument.

        Args:
            source: The waveform source to read (e.g., "CHANnel1", "FFT").

        Returns:
            A NumPy array of the raw, unprocessed ADC values.
        """
        # Ensure previous operations are complete
        await self._wait()
        await self._send_command(f':WAVeform:SOURce {source}')
        await self._wait()
        self._logger.debug(f"Reading data from {source}")

        # Set the data transfer format to 8-bit bytes
        await self._send_command(':WAVeform:FORMat BYTE')

        # For time-domain channels, ensure we get all raw data points
        if source != "FFT":
            await self._send_command(':WAVeform:POINts:MODE RAW')

        self._logger.debug('Reading points')
        await self._wait()
        self._logger.debug('Reading data')

        # Query for the waveform data, which returns a binary block
        raw_data: bytes = await self._query_raw(':WAVeform:DATA?')
        data: np.ndarray = await self._read_to_np(raw_data)
        return data
    
    @validate_call
    async def lock_panel(self, lock: bool = True) -> None:
        """
        Locks the panel of the instrument

        Args:
            lock (bool): True to lock the panel, False to unlock it
        """
        scpi_state = SCPIOnOff.ON.value if lock else SCPIOnOff.OFF.value
        await self._send_command(f":SYSTem:LOCK {scpi_state}")

    @validate_call
    async def auto_scale(self) -> None:
        """
        Auto scale the oscilloscope display.
        
        This method sends an SCPI command to the oscilloscope to auto scale the display.
        
        Example:
        >>> auto_scale()
        """
        await self._send_command(":AUToscale")

    @validate_call
    async def set_time_axis(self, scale: float, position: float) -> None:
        """
        Sets the time axis of the Oscilloscope. (x-axis)

        :param scale: scale The scale of the axis in seconds
        :param position: The position of the time axis from the trigger in seconds
        """
    
        await self._send_command(f':TIMebase:SCALe {scale}')
        await self._send_command(f':TIMebase:POSition {position}')
        await self._wait()

    @validate_call
    async def get_time_axis(self) -> List[float]:
        """
        Gets the time axis of the oscilloscope. (x-axis)

        :return: A list containing the time axis scale and position
        """
        scale_str: str = await self._query(":TIMebase:SCALe?")
        position_str: str = await self._query(":TIMebase:POSition?")
        return [np.float64(scale_str), np.float64(position_str)]
    
    @validate_call
    async def set_channel_axis(self, channel: int, scale: float, offset: float) -> None:
        """
        Sets the channel axis of the oscilloscope. (y-axis)

        :param channel: The channel to set
        :param scale: The scale of the channel axis in volts
        :param offset: The offset of the channel in volts
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )
        
        await self._send_command(f':CHANnel{channel}:SCALe {scale}')
        await self._send_command(f':CHANnel{channel}:OFFSet {offset}')
        await self._wait()

    @validate_call
    async def get_channel_axis(self, channel: int) -> List[float]:
        """
        Gets the channel axis of the oscilloscope. (y-axis)

        :param channel: The channel to get the axis for
        :return: A list containing the channel axis scale and offset
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )
        
        scale_str: str = await self._query(f":CHANnel{channel}:SCALe?")
        offset_str: str = await self._query(f":CHANnel{channel}:OFFSet?")
        return [np.float64(scale_str), np.float64(offset_str)]
        
    @validate_call
    async def configure_trigger(self, channel: int, level: float, source: Optional[str] = None, trigger_type: str = "HIGH", slope: TriggerSlope = TriggerSlope.POSITIVE, mode: str = "EDGE") -> None:
        """
        Sets the trigger for the oscilloscope.
        
        :param channel: The channel to set the trigger for (used if source is None or a channel itself)
        :param level: The trigger level in volts
        :param source: The source of the trigger. Default behaviour is to use the channel. Valid options CHANnel<n> | EXTernal | LINE | WGEN
        :param trigger_type: The type of trigger. Default is 'HIGH' (Note: this param seems unused in current logic for level setting)
        :param slope: The slope of the trigger. Default is TriggerSlope.POSITIVE
        :param mode: The trigger mode. Default is 'EDGE'
        """
        
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Primary channel number is out of range.",
            )
        
        actual_source: str
        if source is None:
            actual_source = f"CHANnel{channel}"
        else:
            actual_source = source.upper()
            # Check if source is a channel (handle CH1, CHAN1, CHANNEL1 formats)
            if actual_source.startswith("CH"):
                try:
                    num_str = "".join(filter(str.isdigit, actual_source))
                    if not num_str:
                        raise ValueError("No digits found in channel source string")
                    source_channel_to_validate = int(num_str)
                    if not (1 <= source_channel_to_validate <= len(self.config.channels)):
                        raise InstrumentParameterError(
                            parameter="source",
                            value=source,
                            valid_range=(1, len(self.config.channels)),
                            message="Source channel number is out of range.",
                        )
                    # Normalize the channel source to CHANNEL format for SCPI command
                    actual_source = f"CHANnel{source_channel_to_validate}"
                except (ValueError, IndexError) as e:
                    raise InstrumentParameterError(
                        parameter="source",
                        value=source,
                        message="Invalid channel format in source.",
                    ) from e
            elif actual_source not in ["EXTERNAL", "LINE", "WGEN"]:
                raise InstrumentParameterError(
                    parameter="source",
                    value=source,
                    valid_range=["EXTernal", "LINE", "WGEN"],
                    message="Invalid source.",
                )

        await self._send_command(f':TRIG:SOUR {actual_source}')
        await self._send_command(f':TRIGger:LEVel {level}, CHANnel{channel}')
        
        if slope.value not in self.config.trigger.slopes:
            raise InstrumentParameterError(
                parameter="slope",
                value=slope.value,
                valid_range=self.config.trigger.slopes,
                message="Unsupported trigger slope.",
            )
        scpi_slope = slope.value
        
        if mode.upper() not in [m.upper() for m in self.config.trigger.modes]: # Case-insensitive check
             self._logger.warning(f"Trigger mode '{mode}' not in configured supported modes: {self.config.trigger.modes}. Passing directly to instrument.")
        scpi_mode = mode

        await self._send_command(f':TRIGger:SLOPe {scpi_slope}')
        await self._send_command(f':TRIGger:MODE {scpi_mode}')
        await self._wait()
        
        self._logger.debug(f"""Trigger set with the following parameters:
                  Trigger Source: {actual_source}
                  Trigger Level for CHAN{channel}: {level}
                  Trigger Slope: {scpi_slope}
                  Trigger Mode: {scpi_mode}""")
    
    @validate_call
    async def measure_voltage_peak_to_peak(self, channel: int) -> MeasurementResult:
        """
        Measure the peak-to-peak voltage for a specified channel.
        
        Args:
        channel (int): The channel identifier.
        
        Returns:
        MeasurementResult: An object containing the peak-to-peak voltage measurement.
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )

        response_str: str = await self._query(f"MEAS:VPP? CHAN{channel}")
        reading: float = float(response_str)

        value_to_return: float | UFloat = reading

        if self.config.measurement_accuracy:
            mode_key = f"vpp_ch{channel}"
            self._logger.debug(f"Attempting to find accuracy spec for Vpp on channel {channel} with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)
            if spec:
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
            values=value_to_return,
            units="V",
            instrument=self.config.model,
            measurement_type="P2PV"
        )

        self._logger.debug(f"Peak to Peak Voltage (Channel {channel}): {value_to_return}")
        
        return measurement_result

    @validate_call
    async def measure_rms_voltage(self, channel: int) -> MeasurementResult:
        """
        Measure the root-mean-square (RMS) voltage for a specified channel.
        
        Args:
        channel (int): The channel identifier.
        
        Returns:
        MeasurementResult: An object containing the RMS voltage measurement.
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )

        response_str: str = await self._query(f"MEAS:VRMS? CHAN{channel}")
        reading: float = float(response_str)

        value_to_return: float | UFloat = reading

        if self.config.measurement_accuracy:
            mode_key = f"vrms_ch{channel}"
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
            values=value_to_return,
            instrument=self.config.model,
            units="V",
            measurement_type="rms_voltage"
        )
        return measurement_result

    @validate_call
    async def read_channels(self, *channels: Union[int, List[int], Tuple[int, ...]], points: Optional[int] = None, run_after: bool = True, timebase: Optional[float] = None, **kwargs) -> ChannelReadingResult:
        """Reads and processes waveform data from one or more channels.

        This is a primary data acquisition method. It triggers an acquisition,
        reads the raw data for the specified channels, and uses the preamble
        to convert the data into a `ChannelReadingResult` containing properly
        scaled time and voltage values in a Polars DataFrame.

        Args:
            *channels: A variable number of channel numbers (e.g., `read_channels(1, 2)`)
                       or a single list/tuple of channels (e.g., `read_channels([1, 2])`).
            points: Deprecated. The number of points is determined by the timebase
                    and instrument settings.
            run_after: This parameter is currently unused.
            timebase: If provided, sets the time-per-division for this acquisition.

        Returns:
            A `ChannelReadingResult` containing the waveform data.

        Raises:
            InstrumentParameterError: If channel numbers are invalid or not provided.
            InstrumentDataError: If time values cannot be generated.
        """
        if 'runAfter' in kwargs:
            warnings.warn(
                "'runAfter' is deprecated, use 'run_after' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            run_after = kwargs['runAfter']
        
        processed_channels: List[int]
        if not channels:
            raise InstrumentParameterError(message="No channels specified.")
        
        first_arg = channels[0]
        if isinstance(first_arg, (list, tuple)) and len(channels) == 1:
            if not all(isinstance(ch_num, int) for ch_num in first_arg):
                raise InstrumentParameterError(
                    message="All elements in channel list/tuple must be integers."
                )
            processed_channels = list(first_arg)
        elif all(isinstance(ch_num, int) for ch_num in channels): # type: ignore [arg-type]
            processed_channels = list(channels) # type: ignore [assignment]
        else:
            raise InstrumentParameterError(
                message="Invalid channel arguments. Must be integers or a single list/tuple of integers."
            )

        if not processed_channels:
            raise InstrumentParameterError(
                message="No channels specified in the list/tuple."
            )

        if timebase is not None:
            current_time_axis = await self.get_time_axis()
            await self.set_time_axis(scale=timebase, position=current_time_axis[1])

        if points is not None:
            self._logger.debug(f"Points argument is deprecated (value: {points}). Use set_time_axis instead.")


        self._logger.debug("starting channel read")

        for ch_num_val in processed_channels:
            if not (1 <= ch_num_val <= len(self.config.channels)):
                raise InstrumentParameterError(
                    parameter="channels",
                    value=ch_num_val,
                    valid_range=(1, len(self.config.channels)),
                    message="Channel number is out of range.",
                )


        sampling_rate_float: float = float(await self.get_sampling_rate())
        channel_commands_str: str = ', '.join(f"CHANnel{ch}" for ch in processed_channels)

        acq_type_enum_or_str = await self.acquisition.get_acquisition_type()
        
        is_average_mode = False
        if isinstance(acq_type_enum_or_str, AcquisitionType):
            is_average_mode = acq_type_enum_or_str == AcquisitionType.AVERAGE
        elif isinstance(acq_type_enum_or_str, str):
            is_average_mode = acq_type_enum_or_str.upper() == "AVERAGE"

        # Handle different acquisition modes. Averaging mode often requires a
        # special command sequence to ensure the requested number of averages
        # are acquired before the data is read.
        if is_average_mode:
            self._logger.debug("AVERAGE acquisition type detected - using special sequence")
            avg_count_int: int = await self.acquisition.get_acquisition_average_count()
            self._logger.debug(f"Current average count: {avg_count_int}")
            await self._send_command(":ACQuire:COMPlete 100") # Ensure all averages are processed
            await self._send_command(":STOP")
            await self._wait()

            # Force a new acquisition sequence for averaging
            sweep_orig_str: str = (await self._query(":TRIGger:SWEep?")).strip()
            await self._send_command(":TRIGger:SWEep AUTO")
            await self._send_command(f"DIGitize {channel_commands_str}", skip_check=True)
            await self._send_command(":TRIGger:FORCe", skip_check=True)
            await self._send_command("*OPC")
            self._logger.debug("Waiting for acquisition to complete …")
            await self._wait()
            await self._send_command(":TRIGger:FORCe", skip_check=True)
            self._logger.debug("Waiting for acquisition to complete …")
            await self._wait()
            await self._send_command(f":TRIGger:SWEep {sweep_orig_str}", skip_check=True)
            await self.clear_status()
        else:
            # For other modes, a simple DIGitize command is sufficient.
            await self._send_command(f"DIGitize {channel_commands_str}")

        await self._send_command(f':WAVeform:SOURce CHANnel{processed_channels[0]}')
        await self._send_command(':WAVeform:FORMat BYTE')
        await self._send_command(':WAVeform:POINts:MODE RAW')
        
        pream: Preamble = await self._read_preamble()

        time_values_np: Optional[np.ndarray] = None
        measurement_results_dict: Dict[str, np.ndarray] = {}

        # Loop through each requested channel to read its data
        for ch_num_loop in processed_channels:
            raw_wave_data = await self._read_wave_data(f"CHANnel{ch_num_loop}")
            # Convert raw ADC values to volts using the preamble data
            voltages_np: np.ndarray = (raw_wave_data - pream.yref) * pream.yinc + pream.yorg

            # Generate the corresponding time axis array, but only once.
            if time_values_np is None:
                n_pts_int: int = len(voltages_np)
                time_values_np = (np.arange(n_pts_int) - pream.xref) * pream.xinc + pream.xorg

            measurement_results_dict[f"Channel {ch_num_loop} (V)"] = voltages_np
        
        if time_values_np is None:
            raise InstrumentDataError(
                self.config.model, "Time values were not generated during channel read."
            )

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
    
    @validate_call
    async def get_sampling_rate(self) -> float:
        """
        Get the current sampling rate of the oscilloscope.
        Returns:
            float: The sampling rate in Hz.
        """
        response_str: str = await self._query(":ACQuire:SRATe?")
        sampling_rate_float: float = np.float64(response_str)
        return sampling_rate_float
    
    @validate_call
    async def get_probe_attenuation(self, channel: int) -> str: # Returns string like "10:1"
        """
        Gets the probe attenuation for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to get the probe attenuation for.

        Returns:
            str: The probe attenuation value (e.g., '10:1', '1:1').
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )
        response_str: str = (await self._query(f"CHANnel{channel}:PROBe?")).strip()
        # Assuming response is the numeric factor (e.g., "10", "1")
        try:
            # Ensure it's a number before formatting
            num_factor = float(response_str)
            if num_factor.is_integer():
                return f"{int(num_factor)}:1"
            return f"{num_factor}:1"
        except ValueError:
            self._logger.warning(f"Could not parse probe attenuation factor '{response_str}' as number. Returning raw.")
            return response_str # Or raise error
        
    @validate_call
    async def set_probe_attenuation(self, channel: int, scale: int) -> None:
        """
        Sets the probe scale for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to set the scale for.
            scale (int): The probe scale value (e.g., 10 for 10:1, 1 for 1:1).
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )
        
        channel_model_config = self.config.channels[channel - 1]
        if scale not in channel_model_config.probe_attenuation: # probe_attenuation is List[int]
            raise InstrumentParameterError(
                parameter="scale",
                value=scale,
                valid_range=channel_model_config.probe_attenuation,
                message=f"Scale not in supported probe_attenuation list for channel {channel}.",
            )
        
        # SCPI command usually takes the numeric factor directly
        await self._send_command(f":CHANnel{channel}:PROBe {scale}")
        self._logger.debug(f"Set probe scale to {scale}:1 for channel {channel}.")

    @validate_call
    async def set_acquisition_time(self, time: float) -> None:
        """
        Set the total acquisition time for the oscilloscope.

        Args:
            time (float): The total acquisition time in seconds.
        """
        await self._send_command(f":TIMebase:MAIN:RANGe {time}")

    @validate_call
    async def set_sample_rate(self, rate: str) -> None:
        """
        Sets the sample rate for the oscilloscope.

        Args:
        rate (str): The desired sample rate. Valid values are 'MAX' and 'AUTO'. Case-insensitive.
        """
        rate_upper: str = rate.upper()
        valid_values: List[str] = ["MAX", "AUTO"] # These are common SCPI values
        if rate_upper not in valid_values:
            raise InstrumentParameterError(
                parameter="rate",
                value=rate,
                valid_range=valid_values,
                message="Invalid rate.",
            )
        await self._send_command(f"ACQuire:SRATe {rate_upper}")

    @validate_call
    async def set_bandwidth_limit(self, channel: int, bandwidth: Union[str, float]) -> None:
        """
        Sets the bandwidth limit for a specified channel.
        Args:
            channel (int): The channel number.
            bandwidth (Union[str, float]): The bandwidth limit (e.g., "20M", 20e6, or "FULL").
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )
        await self._send_command(f"CHANnel{channel}:BANDwidth {bandwidth}")

    @validate_call
    #@ConfigRequires("function_generator")
    async def wave_gen(self, state: bool) -> None:
        """
        Enable or disable the waveform generator of the oscilloscope.
        
        Args:
        state (bool): True to enable ('ON'), False to disable ('OFF').
        """
        scpi_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        await self._send_command(f"WGEN:OUTP {scpi_state}")

    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wave_gen_func(self, func_type: WaveformType) -> None:
        """
        Set the waveform function for the oscilloscope's waveform generator.
        
        Args:
        func_type (WaveformType): The desired function enum member.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        
        # Check if the SCPI value of the enum is in the list of supported waveform types from config
        if func_type.value not in self.config.function_generator.waveform_types:
            raise InstrumentParameterError(
                parameter="func_type",
                value=func_type.value,
                valid_range=self.config.function_generator.waveform_types,
                message="Unsupported waveform type.",
            )
        
        await self._send_command(f"WGEN:FUNC {func_type.value}")

    @validate_call
    ##@ConfigRequires("function_generator")
    async def set_wave_gen_freq(self, freq: float) -> None:
        """
        Set the frequency for the waveform generator.
        
        Args:
        freq (float): The desired frequency for the waveform generator in Hz.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        # Assuming RangeMixin's assert_in_range is preferred for validation
        self.config.function_generator.frequency.assert_in_range(freq, name="Waveform generator frequency")
        await self._send_command(f"WGEN:FREQ {freq}")

    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wave_gen_amp(self, amp: float) -> None:
        """
        Set the amplitude for the waveform generator.
        
        Args:
        amp (float): The desired amplitude for the waveform generator in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.config.function_generator.amplitude.assert_in_range(amp, name="Waveform generator amplitude")
        await self._send_command(f"WGEN:VOLT {amp}")

    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wave_gen_offset(self, offset: float) -> None:
        """
        Set the voltage offset for the waveform generator.
        
        Args:
        offset (float): The desired voltage offset for the waveform generator in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.config.function_generator.offset.assert_in_range(offset, name="Waveform generator offset")
        await self._send_command(f"WGEN:VOLT:OFFSet {offset}")

    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wgen_sin(self, amp: float, offset: float, freq: float) -> None:
        """Sets the waveform generator to a sine wave.

        :param amp: The amplitude of the sine wave in volts
        :param offset: The offset of the sine wave in volts
        :param freq: The frequency of the sine wave in Hz.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        await self.set_wave_gen_func(WaveformType.SINE)
        await self.set_wave_gen_amp(amp)
        await self.set_wave_gen_offset(offset)
        await self.set_wave_gen_freq(freq)


    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wgen_square(self, v0: float, v1: float, freq: float, duty_cycle: Optional[int] = None, **kwargs) -> None:
        """Sets the waveform generator to a square wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the square wave in Hz.
        :param duty_cycle: The duty cycle (1% to 99%).
        """
        if 'dutyCycle' in kwargs:
            warnings.warn(
                "'dutyCycle' is deprecated, use 'duty_cycle' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            duty_cycle = kwargs['dutyCycle']

        if duty_cycle is None:
            duty_cycle = 50

        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        
        await self.set_wave_gen_func(WaveformType.SQUARE)
        
        def clamp_duty(number: int) -> int:
            return max(1, min(number, 99))

        await self._send_command(f':WGEN:VOLTage:LOW {v0}')
        await self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        await self._send_command(f':WGEN:FREQuency {freq}')
        await self._send_command(f':WGEN:FUNCtion:SQUare:DCYCle {clamp_duty(duty_cycle)}')


    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wgen_ramp(self, v0: float, v1: float, freq: float, symmetry: int) -> None:
        """Sets the waveform generator to a ramp wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the ramp wave in Hz.
        :param symmetry: Symmetry (0% to 100%).
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        await self.set_wave_gen_func(WaveformType.RAMP)
        def clamp_symmetry(number: int) -> int:
            return max(0, min(number, 100))

        await self._send_command(f':WGEN:VOLTage:LOW {v0}')
        await self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        await self._send_command(f':WGEN:FREQuency {freq}')
        await self._send_command(f':WGEN:FUNCtion:RAMP:SYMMetry {clamp_symmetry(symmetry)}')


    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wgen_pulse(self, v0: float, v1: float, period: float, pulse_width: Optional[float] = None, **kwargs) -> None:
        """Sets the waveform generator to a pulse wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param period: The period of the pulse wave in seconds.
        :param pulse_width: The pulse width in seconds.
        """
        if 'pulseWidth' in kwargs:
            warnings.warn(
                "'pulseWidth' is deprecated, use 'pulse_width' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            pulse_width = kwargs['pulseWidth']

        if pulse_width is None:
            raise InstrumentParameterError(message="pulse_width is required.")

        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        await self.set_wave_gen_func(WaveformType.PULSE)
        
        await self._send_command(f':WGEN:VOLTage:LOW {v0}')
        await self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        await self._send_command(f':WGEN:PERiod {period}')
        await self._send_command(f':WGEN:FUNCtion:PULSe:WIDTh {pulse_width}')


    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wgen_dc(self, offset: float) -> None:
        """Sets the waveform generator to a DC wave.

        :param offset: The offset of the DC wave in volts
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        await self.set_wave_gen_func(WaveformType.DC)
        await self.set_wave_gen_offset(offset)


    @validate_call
    #@ConfigRequires("function_generator")
    async def set_wgen_noise(self, v0: float, v1: float, offset: float) -> None:
        """Sets the waveform generator to a noise wave.

        :param v0: The 'low' amplitude component or similar parameter for noise.
        :param v1: The 'high' amplitude component or similar parameter for noise.
        :param offset: The offset of the noise wave in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        await self.set_wave_gen_func(WaveformType.NOISE)
        await self._send_command(f':WGEN:VOLTage:LOW {v0}')
        await self._send_command(f':WGEN:VOLTage:HIGH {v1}')
        await self.set_wave_gen_offset(offset)

    @validate_call
    async def display_channel(self, channels: Union[int, List[int]], state: bool = True) -> None:
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
            # validate_call should catch this if type hints are precise enough
            raise InstrumentParameterError(
                message="channels must be an int or a list of ints"
            )
        
        scpi_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        for ch_num in ch_list:
            if not (1 <= ch_num <= len(self.config.channels)):
                raise InstrumentParameterError(
                    parameter="channels",
                    value=ch_num,
                    valid_range=(1, len(self.config.channels)),
                    message="Channel number is out of range.",
                )
            await self._send_command(f"CHANnel{ch_num}:DISPlay {scpi_state}")

    @validate_call
    #@ConfigRequires("fft")
    async def fft_display(self, state: bool = True) -> None:
        """
        Switches on or off the FFT display.

        :param state: True to enable FFT display, False to disable.
        """
        scpi_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        await self._send_command(f":FFT:DISPlay {scpi_state}")
        self._logger.debug(f"FFT display {'enabled' if state else 'disabled'}.")
        
    @validate_call
    #@ConfigRequires("function_generator")
    async def function_display(self, state: bool = True) -> None:
        """
        Switches on or off the function display (e.g. Math or WGEN waveform).

        :param state: True to enable display, False to disable.
        """
        scpi_state = SCPIOnOff.ON.value if state else SCPIOnOff.OFF.value
        await self._send_command(f":FUNCtion:DISPlay {scpi_state}")
        self._logger.debug(f"Function display {'enabled' if state else 'disabled'}.")

    @validate_call
    #@ConfigRequires("fft")
    async def configure_fft(self, source_channel: int, scale: Optional[float] = None, offset: Optional[float] = None, span: Optional[float] = None,  window_type: str = 'HANNing', units: str = 'DECibel', display: bool = True) -> None:
        """
        Configure the oscilloscope to perform an FFT on the specified channel.

        :param source_channel: The channel number to perform FFT on.
        :param scale: The vertical scale of the FFT display. Instrument specific.
        :param offset: The vertical offset of the FFT display. Instrument specific.
        :param span: The frequency span for the FFT. Instrument specific.
        :param window_type: The windowing function. Case-insensitive. From config.fft.window_types.
        :param units: The unit for FFT magnitude. Case-insensitive. From config.fft.units.
        :param display: True to turn FFT display ON, False for OFF.
        """
        if self.config.fft is None:
            raise InstrumentConfigurationError(
                self.config.model, "FFT not configured for this instrument."
            )
        if not (1 <= source_channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="source_channel",
                value=source_channel,
                valid_range=(1, len(self.config.channels)),
                message="Source channel number is out of range.",
            )
        
        # Validate window_type against config.fft.window_types (List[str])
        # Assuming window_type parameter is the SCPI string itself
        if window_type.upper() not in [wt.upper() for wt in self.config.fft.window_types]:
            raise InstrumentParameterError(
                parameter="window_type",
                value=window_type,
                valid_range=self.config.fft.window_types,
                message="Unsupported FFT window type.",
            )
        scpi_window = window_type
        
        # Validate units against config.fft.units (List[str])
        if units.upper() not in [u.upper() for u in self.config.fft.units]:
            raise InstrumentParameterError(
                parameter="units",
                value=units,
                valid_range=self.config.fft.units,
                message="Unsupported FFT units.",
            )
        scpi_units = units

        await self._send_command(f':FFT:SOURce1 CHANnel{source_channel}')
        await self._send_command(f':FFT:WINDow {scpi_window}')
        
        if span is not None:
            await self._send_command(f':FFT:SPAn {span}')
        
        await self._send_command(f':FFT:VTYPe {scpi_units}')
        
        if scale is not None:
            await self._send_command(f':FFT:SCALe {scale}')
        
        if offset is not None:
            await self._send_command(f':FFT:OFFSet {offset}')
            
        scpi_display_state = SCPIOnOff.ON.value if display else SCPIOnOff.OFF.value
        await self._send_command(f':FFT:DISPlay {scpi_display_state}')

        self._logger.debug(f"FFT configured for channel {source_channel}.")

    async def _convert_binary_block_to_data(self, binary_block: bytes) -> np.ndarray: # No internal await calls, can remain sync if preferred, but making async for consistency if it's part of an async chain
        """
        Converts a SCPI binary block to a NumPy array.
        Assumes format like #<N><LengthBytes><DataBytes>
        This method's original implementation was problematic.
        This is a more standard interpretation of SCPI binary blocks.
        The actual data type (e.g., int8, int16) depends on :WAVeform:FORMat.
        """
        if not binary_block.startswith(b'#'):
            raise InstrumentDataError(
                self.config.model, "Invalid binary block format: does not start with #"
            )
        
        len_digits = int(binary_block[1:2].decode('ascii'))
        data_len = int(binary_block[2 : 2 + len_digits].decode('ascii'))
        
        actual_data_start_index = 2 + len_digits
        raw_data_bytes = binary_block[actual_data_start_index : actual_data_start_index + data_len]
        
        dt = np.dtype(np.int8)
        data_array = np.frombuffer(raw_data_bytes, dtype=dt)
        
        if len(data_array) != data_len:
             self._logger.debug(f"Warning: Binary block data length mismatch. Expected {data_len}, got {len(data_array)}")

        return data_array

    @validate_call
    async def read_fft_data(self, channel: int, window: Optional[str] = 'hann') -> FFTResult:
        """
        Acquires time-domain data for the specified channel and computes the FFT using
        the analysis submodule.

        Args:
            channel (int): The channel number to perform FFT on.
            window (Optional[str]): The windowing function to apply before FFT
                                     (e.g., 'hann', 'hamming', None).

        Returns:
            FFTResult: An object containing the computed FFT data (frequency and linear magnitude).
        """
        self._logger.debug(f"Initiating FFT computation for channel {channel} using analysis module.")

        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )

        # 1. Acquire raw time-domain waveform data
        waveform_data: ChannelReadingResult = await self.read_channels(channel)
        
        if waveform_data.values is None or waveform_data.values.is_empty():
            self._logger.warning(f"No waveform data acquired for channel {channel}. Cannot compute FFT.")
            # Return an empty FFTResult or raise an error
            return FFTResult(
                instrument=self.config.model,
                units="Linear",
                measurement_type="FFT_computed_python",
                values=pl.DataFrame({
                    "Frequency (Hz)": np.array([]),
                    "Magnitude (Linear)": np.array([])
                })
            )

        time_array = waveform_data.values["Time (s)"].to_numpy()
        voltage_column_name = f"Channel {channel} (V)"
        if voltage_column_name not in waveform_data.values.columns:
            raise InstrumentDataError(
                self.config.model,
                f"Could not find voltage data for channel {channel} in waveform results.",
            )
        voltage_array = waveform_data.values[voltage_column_name].to_numpy()

        # 2. Call the appropriate function from pytestlab.analysis.fft
        frequency_array, magnitude_array = analysis_fft.compute_fft(
            time_array=time_array,
            voltage_array=voltage_array,
            window=window
        )

        # 3. Return or further process the results
        return FFTResult(
            instrument=self.config.model,
            units="Linear", # compute_fft returns linear magnitude
            measurement_type="FFT_computed_python",
            values=pl.DataFrame({
                "Frequency (Hz)": frequency_array,
                "Magnitude (Linear)": magnitude_array
            })
        )

    @validate_call
    async def screenshot(self) -> Image.Image:
        """
        Capture a screenshot of the oscilloscope display.

        :return Image: A PIL Image object containing the screenshot.
        """
        binary_data_response: bytes = await self._query_raw(":DISPlay:DATA? PNG, COLor")
        
        if not binary_data_response.startswith(b'#'):
            raise InstrumentDataError(
                self.config.model, "Invalid screenshot data format: does not start with #"
            )

        length_of_length_field: int = int(chr(binary_data_response[1]))
        png_data_length_str: str = binary_data_response[2 : 2 + length_of_length_field].decode('ascii')
        png_data_length: int = int(png_data_length_str)
        png_data_start_index: int = 2 + length_of_length_field
        image_data_bytes: bytes = binary_data_response[png_data_start_index : png_data_start_index + png_data_length]
        
        return Image.open(BytesIO(image_data_bytes))

    @validate_call
    #@ConfigRequires("franalysis")
    #@ConfigRequires("function_generator")
    async def franalysis_sweep(self, input_channel: int, output_channel: int, start_freq: float, stop_freq: float, amplitude: float, points: int = 10, trace: str = "none", load: str = "onemeg", disable_on_complete: bool = True) -> FRanalysisResult:
        """
        Perform a frequency response analysis sweep.

        Returns:
            FRanalysisResult: Containing the frequency response analysis data.
        """
        if self.config.function_generator is None or self.config.franalysis is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator or FRANalysis not configured."
            )

        if not (1 <= input_channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="input_channel",
                value=input_channel,
                valid_range=(1, len(self.config.channels)),
                message="Input channel is out of range.",
            )
        if not (1 <= output_channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="output_channel",
                value=output_channel,
                valid_range=(1, len(self.config.channels)),
                message="Output channel is out of range.",
            )

        # Ensure points is at least 2 for a valid sweep
        if points < 2:
            raise InstrumentParameterError(
                parameter="points",
                value=points,
                valid_range=(2, "inf"),
                message="Points for sweep must be at least 2.",
            )

        # SCPI commands for frequency response analysis sweep
        await self._send_command(f":FUNCtion:FRANalysis")
        await self._send_command(f":FREQuency:START {start_freq}")
        await self._send_command(f":FREQuency:STOP {stop_freq}")
        await self._send_command(f":AMPLitude {amplitude}")
        await self._send_command(f":POINTS {points}")
        await self._send_command(f":TRACe:FEED {trace}")
        await self._send_command(f":LOAD {load}")
        
        if disable_on_complete:
            await self._send_command(":DISABLE")

        # Optionally wait for completion or check status
        await self._wait()  # Ensure to wait for the command to complete

        # Assuming the result can be fetched with a common query, adjust as necessary
        result_data = await self._query(":FETCH:FRANalysis?")
        
        # Parse the result data into a structured format if needed
        # For now, let's assume it's a simple comma-separated value string
        parsed_results = [float(val) for val in result_data.split(',')]

        # Create a DataFrame or structured result object
        # Assuming two columns: Frequency and Magnitude
        freq_values = parsed_results[0::2]  # Extracting frequency values
        mag_values = parsed_results[1::2]   # Extracting magnitude values

        return FRanalysisResult(
            instrument=self.config.model,
            units="",
            measurement_type="FrequencyResponse",
            values=pl.DataFrame({
                "Frequency (Hz)": freq_values,
                "Magnitude": mag_values
            })
        )