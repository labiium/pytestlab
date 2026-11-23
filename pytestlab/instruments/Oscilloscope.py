from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from typing import TYPE_CHECKING
from typing import Any
from typing import Self

import numpy as np
import polars as pl
from PIL import Image
from pydantic import StrictInt
from pydantic import validate_call

from ..analysis import fft as analysis_fft
from ..common.health import HealthReport
from ..common.health import HealthStatus
from ..config.instrument_config import InstrumentConfig  # Import base config

# from ..config import OscilloscopeConfig, ConfigRequires # OscilloscopeConfig is V2
from ..config.oscilloscope_config import OscilloscopeConfig  # Import the V2 config
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ..errors import InstrumentParameterError
from ..errors import OperationDiscoveryError
from ..experiments import MeasurementResult
from ..uncertainty import Quantity as MeasurementQuantity
from ..uncertainty import QuantityArray
from ..uncertainty.waveform import WaveformUncertaintyModel
from .instrument import Instrument
from .operation_contract import OperationDescriptor
from .scpi_binary import BinaryBlockParseError
from .scpi_binary import definite_length_block_to_array
from .scpi_binary import strip_definite_length_block
from .uncertainty_adapters import nominal_measurement_quantity
from .uncertainty_adapters import nonzero_uncertainty_quantity
from .uncertainty_adapters import oscilloscope_measurement_context
from .waveform_result import AcquisitionTrace
from .waveform_result import ScopeStateSnapshot
from .waveform_result import WaveformResult
from .waveform_set import SharedClockModel
from .waveform_set import WaveformSetResult

if TYPE_CHECKING:  # for type checkers only; avoids runtime import cycles
    from ..plotting.simple import PlotSpec


def _validate_range(val, minval, maxval, name):
    if not (minval <= val <= maxval):
        raise InstrumentParameterError(
            parameter=name,
            value=val,
            valid_range=(minval, maxval),
            message=f"{name} must be between {minval} and {maxval}.",
        )


def _profile_semantic_response(
    scope: Oscilloscope, operation: str, parameter: str, response: str
) -> str | None:
    """Return the semantic value matching a profile-owned transport token."""
    spec = scope.config.operation_options.parameter(operation, parameter)
    if spec is None:
        return None
    for option in spec.options:
        transport = option.transport
        token = getattr(transport, "value", None) if transport is not None else None
        if not token:
            continue
        token = str(token)
        response_upper = response.strip().upper()
        token_upper = token.upper()
        short_token = "".join(character for character in token if not character.islower())
        abbreviated = bool(short_token) and response_upper == short_token.upper()
        if response_upper == token_upper or abbreviated:
            return str(option.value)
    return None


class ChannelReadingResult(MeasurementResult):
    """A result class for oscilloscope channel readings (time, voltage, etc).

    Convenience features:
    - results[1] → returns a new ChannelReadingResult containing only CH1 and time
    - results.for_channel(2) → same as above for channel 2
    - results.channels → list of available channel numbers
    - results.time → numpy array of the time axis
    - results.to_dataframe() → underlying DataFrame
    """

    def _ensure_dataframe(self) -> pl.DataFrame:
        if not isinstance(self.values, pl.DataFrame):
            raise TypeError("ChannelReadingResult expects 'values' to be a Polars DataFrame.")
        return self.values

    @property
    def channels(self) -> list[int]:
        """List which channel numbers this reading contains."""
        df = self._ensure_dataframe()
        chans: list[int] = []
        for name in df.columns:
            if name.startswith("Channel ") and name.endswith(" (V)"):
                try:
                    num = int(name.split(" ")[1])
                    chans.append(num)
                except Exception:
                    continue
        return sorted(chans)

    @property
    def time(self) -> np.ndarray:
        """Return the shared time axis of the captured trace, in seconds."""
        df = self._ensure_dataframe()
        if "Time (s)" not in df.columns:
            raise KeyError("Time (s) column not found in ChannelReadingResult.")
        return df["Time (s)"].to_numpy()

    def to_dataframe(self) -> pl.DataFrame:
        """Return the captured samples as a Polars DataFrame.


        The frame has one time column and one voltage column per captured channel.
        """
        return self._ensure_dataframe()

    def _column_for_channel(self, channel: int) -> str:
        return f"Channel {channel} (V)"

    def for_channel(self, channel: int) -> ChannelReadingResult:
        """Narrow this reading to a single channel.


        Args:
            channel: Channel number to keep.

        Returns:
            A reading containing only that channel's samples.
        """
        df = self._ensure_dataframe()
        col = self._column_for_channel(channel)
        if col not in df.columns:
            raise KeyError(f"Channel column not present: {col}")
        sub_df = pl.DataFrame(
            {
                "Time (s)": df["Time (s)"],
                col: df[col],
            }
        )
        envelope = dict(getattr(self, "envelope", {}) or {})
        waveform_meta = envelope.get("waveform_uncertainty")
        if isinstance(waveform_meta, dict):
            envelope["waveform_uncertainty"] = {
                str(channel): waveform_meta.get(str(channel), waveform_meta.get(channel))
            }
        return ChannelReadingResult(
            values=sub_df,
            instrument=self.instrument,
            units=self.units,
            measurement_type=self.measurement_type,
            timestamp=self.timestamp,
            sampling_rate=getattr(self, "sampling_rate", None),
            envelope=envelope,
        )

    def waveform(self, channel: int) -> WaveformResult:
        """Return a first-class covariance-aware waveform result for one channel.

        This is intentionally lazy so normal `read_channels()` callers keep the
        same DataFrame behavior and cost.  If no waveform uncertainty metadata
        is available, the returned result carries nominal samples with explicit
        incomplete provenance.
        """

        df = self._ensure_dataframe()
        col = self._column_for_channel(channel)
        if col not in df.columns:
            raise KeyError(f"Channel column not present: {col}")
        values = df[col].to_numpy().astype(float)
        time = df["Time (s)"].to_numpy().astype(float) if "Time (s)" in df.columns else None
        meta_by_channel = (getattr(self, "envelope", {}) or {}).get("waveform_uncertainty", {})
        meta = meta_by_channel.get(str(channel)) or meta_by_channel.get(channel) or {}
        unit = str(meta.get("unit", self.units or "V"))
        model = WaveformUncertaintyModel.from_metadata(
            meta,
            samples=values,
            unit=unit,
            channel=channel,
        )
        return WaveformResult(
            values,
            time=time,
            unit=unit,
            channel=channel,
            instrument=self.instrument,
            model=model,
            metadata=meta,
        )

    def quantity(self, channel: int) -> QuantityArray:
        """Return a covariance-aware waveform `QuantityArray` for one channel."""

        return self.waveform(channel).quantity_array()

    def channel(self, channel: int) -> WaveformResult:
        """Return one channel as a waveform result with automatic uncertainty propagation."""

        return self.waveform(channel)

    def ch(self, channel: int) -> WaveformResult:
        """Short alias for :meth:`channel` for interactive notebook use."""

        return self.waveform(channel)

    def mean(
        self, channel: int, *, dof_method: str = "validated_independent"
    ) -> MeasurementQuantity:
        """Return the channel mean as a unit- and uncertainty-carrying quantity."""

        return self.quantity(channel).mean(dof_method=dof_method)

    def rms(self, channel: int, *, dof_method: str = "lag1_autocorrelation") -> MeasurementQuantity:
        """Return channel RMS as a unit- and uncertainty-carrying quantity."""

        return self.quantity(channel).rms(dof_method=dof_method)

    def peak_to_peak(self, channel: int) -> MeasurementQuantity:
        """Return first-order channel peak-to-peak voltage.

        This helper preserves the underlying ``QuantityArray`` warning model:
        first-order Vpp is marked non-report-grade unless Monte Carlo propagation
        is used.
        """

        return self.quantity(channel).peak_to_peak()

    def peak_to_peak_monte_carlo(
        self,
        channel: int,
        *,
        samples: int = 100_000,
        seed: int | None = None,
    ) -> MeasurementQuantity:
        """Return Monte Carlo propagated channel peak-to-peak voltage."""

        return self.quantity(channel).peak_to_peak_monte_carlo(samples=samples, seed=seed)

    def __getitem__(self, key):
        # Integer channel indexing: results[1] → CH1 + time
        if isinstance(key, int):
            return self.for_channel(key)
        # Named access for time
        if key in ("time", "t"):
            return self.time
        # Fall back to default behavior (may raise)
        return super().__getitem__(key)


class FFTResult(MeasurementResult):
    """A result class for FFT data from the oscilloscope."""

    pass


class FRanalysisResult(MeasurementResult):
    """A result class for frequency response analysis data."""

    pass


# (Removed forward declaration to avoid shadowing real Oscilloscope class)


class ScopeChannelFacade:
    """Provides a simplified, chainable interface for a single oscilloscope channel.

    This facade abstracts the underlying SCPI commands for common channel
    operations, allowing for more readable and fluent test scripts. For example:
    `scope.channel(1).setup(scale=0.5, offset=0).enable()`

    Attributes:
        _scope: The parent `Oscilloscope` instance.
        _channel: The channel number this facade controls.
    """

    def __init__(self, scope: Oscilloscope, channel_num: int):
        self._scope = scope
        self._channel = channel_num

    @validate_call
    def setup(
        self,
        scale: float | None = None,
        position: float | None = None,
        offset: float | None = None,
        coupling: str | None = None,
        probe_attenuation: float | None = None,
        bandwidth_limit: str | float | None = None,
    ) -> Self:
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
        self._scope._setup_channel(
            self._channel,
            scale=scale,
            position=position,
            offset=offset,
            coupling=coupling,
            probe_attenuation=probe_attenuation,
            bandwidth_limit=bandwidth_limit,
        )
        return self

    def enable(self) -> Self:
        """Enables the channel display."""
        self._scope.display_channel(self._channel, True)
        return self

    def disable(self) -> Self:
        """Disables the channel display."""
        self._scope.display_channel(self._channel, False)
        return self

    def measure_peak_to_peak(self, *, uncertainty: bool = True) -> MeasurementResult:
        """Performs a peak-to-peak voltage measurement on this channel."""
        return self._scope.measure_voltage_peak_to_peak(self._channel, uncertainty=uncertainty)

    def measure_rms(self, *, uncertainty: bool = True) -> MeasurementResult:
        """Performs an RMS voltage measurement on this channel."""
        return self._scope.measure_rms_voltage(self._channel, uncertainty=uncertainty)


class ScopeTriggerFacade:
    """Provides a simplified, chainable interface for the oscilloscope's trigger system.

    This facade abstracts the underlying SCPI commands for trigger operations,
    focusing on common use cases like setting up an edge trigger.

    Attributes:
        _scope: The parent `Oscilloscope` instance.
    """

    def __init__(self, scope: Oscilloscope):
        self._scope = scope

    @validate_call
    def setup_edge(
        self,
        source: str,
        level: float,
        slope: str = "positive",
        coupling: str | None = None,
        mode: str = "EDGE",
    ) -> Self:
        """Configures a standard edge trigger.

        Args:
            source: The trigger source (e.g., "CH1", "CH2", "EXT", "LINE").
            level: The trigger level in volts.
            slope: The semantic trigger slope (for example `positive`, `negative`, or `either`).
            coupling: The trigger coupling (e.g., "AC", "DC"). Can be instrument-specific.
            mode: The trigger mode, defaults to "EDGE".

        Returns:
            The `ScopeTriggerFacade` instance for method chaining.
        """
        resolved_source = self._scope._resolve_operation_parameter(
            "configure_trigger", "source", source
        )
        semantic_source = str(resolved_source.value)
        trigger_channel_for_level = 1
        if semantic_source.startswith("channel_"):
            trigger_channel_for_level = int(semantic_source.rsplit("_", 1)[1])

        self._scope.configure_trigger(
            channel=trigger_channel_for_level,
            level=level,
            source=semantic_source,
            slope=slope,
            mode=mode,
        )
        if coupling is not None:
            for cmd in self._scope._scpi_engine.build(
                "set_trigger_coupling", mode=mode.upper(), coupling=coupling.upper()
            ):
                self._scope._send_command(cmd)
        return self


class ScopeAcquisitionFacade:
    """Provides a simplified interface for the oscilloscope's acquisition system.

    This facade manages settings related to how the oscilloscope digitizes
    signals, including acquisition type (e.g., Normal, Averaging), memory mode
    (Real-time vs. Segmented), and sample rates.

    Attributes:
        _scope: The parent `Oscilloscope` instance.
    """

    def __init__(self, scope: Oscilloscope):
        self._scope = scope

    @validate_call
    def set_acquisition_type(self, acq_type: str) -> Self:
        """Set the acquisition type: normal, averaging, peak detect or high resolution."""
        self._scope.set_acquisition_type(acq_type)
        return self

    @validate_call
    def get_acquisition_type(self) -> str:
        """Read back the current acquisition type."""
        query = self._scope._scpi_engine.build("acq_get_type")[0]
        resp_str_raw: str = self._scope._query(query).strip()
        semantic = _profile_semantic_response(
            self._scope, "set_acquisition_type", "acq_type", resp_str_raw
        )
        if semantic:
            return semantic
        numeric_map = (self._scope._scpi_engine.describe("acq_get_type").get("response") or {}).get(
            "numeric_map"
        ) or {}
        numeric_key = resp_str_raw.upper().removeprefix("+")
        mapped_name = numeric_map.get(numeric_key)
        if mapped_name:
            resolved = self._scope._resolve_operation_parameter(
                "set_acquisition_type", "acq_type", str(mapped_name).lower()
            )
            return str(resolved.value).upper()
        raise InstrumentDataError(
            self._scope.config.model,
            "Profile could not map the acquisition-type response to a semantic value.",
        )

    @validate_call
    def get_acquisition_mode(self) -> str:
        """Read back the current acquisition mode, such as real-time or segmented."""
        resp_str_raw: str = self._scope._query(
            self._scope._scpi_engine.build("acq_get_mode")[0]
        ).strip()
        semantic = _profile_semantic_response(
            self._scope, "set_acquisition_mode", "mode", resp_str_raw
        )
        if semantic:
            return semantic
        raise InstrumentDataError(
            self._scope.config.model,
            "Profile could not map the acquisition-mode response to a semantic value.",
        )

    @validate_call
    def set_acquisition_average_count(self, count: int) -> Self:
        """Set how many acquisitions are averaged together when averaging is enabled."""
        _validate_range(count, 2, 65_536, "Average count")
        current_acq_type_str = self.get_acquisition_type()
        current_type = self._scope._resolve_operation_parameter(
            "set_acquisition_type", "acq_type", current_acq_type_str.lower()
        ).value
        average_type = self._scope._resolve_operation_parameter(
            "set_acquisition_type", "acq_type", "average"
        ).value
        if current_type != average_type:
            raise InstrumentParameterError(
                parameter="count",
                message=f"Average count can only be set when acquisition type is AVERAGE, not {current_acq_type_str}.",
            )
        for cmd in self._scope._scpi_engine.build("acq_set_count", count=count):
            self._scope._send_command(cmd)
        self._scope._wait()
        self._scope._logger.debug(f"AVERAGE count set → {count}")
        return self

    @validate_call
    def get_acquisition_average_count(self) -> int:
        """Read back how many acquisitions are averaged together."""
        return int(self._scope._query(self._scope._scpi_engine.build("acq_get_count")[0]))

    @validate_call
    def set_acquisition_mode(self, mode: str) -> Self:
        """Set the acquisition mode, such as real-time or segmented."""
        self._scope.set_acquisition_mode(mode)
        return self

    @validate_call
    def set_segmented_count(self, count: int) -> Self:
        """Set how many segments are captured in segmented acquisition mode."""
        current_mode = self.get_acquisition_mode()
        current_transport = self._scope._resolve_operation_parameter(
            "set_acquisition_mode", "mode", current_mode.lower()
        ).transport_value
        if not str(current_transport).upper().startswith("SEGM"):
            raise InstrumentParameterError(
                parameter="count",
                message="Segmented count can only be set while in SEGMENTED acquisition mode.",
            )
        _validate_range(count, 2, 500, "Segmented count")
        for cmd in self._scope._scpi_engine.build("seg_set_count", count=count):
            self._scope._send_command(cmd)
        self._scope._wait()
        self._scope._logger.debug(f"Segmented COUNT set → {count}")
        return self

    @validate_call
    def get_segmented_count(self) -> int:
        """Read back how many segments segmented acquisition captures."""
        return int(self._scope._query(self._scope._scpi_engine.build("seg_get_count")[0]))

    @validate_call
    def set_segment_index(self, index: int) -> Self:
        """Select which captured segment subsequent reads return."""
        total_segments: int = self.get_segmented_count()
        _validate_range(index, 1, total_segments, "Segment index")
        for cmd in self._scope._scpi_engine.build("seg_set_index", index=index):
            self._scope._send_command(cmd)
        self._scope._wait()
        self._scope._logger.debug(f"Segment INDEX set → {index}")
        return self

    @validate_call
    def get_segment_index(self) -> int:
        """Read back which captured segment is currently selected."""
        return int(self._scope._query(self._scope._scpi_engine.build("seg_get_index")[0]))

    @validate_call
    def analyze_all_segments(self) -> Self:
        """Run measurements across every captured segment rather than just the selected one."""
        if self.get_acquisition_mode().casefold() != "segmented":
            raise InstrumentParameterError(
                parameter="count", message="Segment analysis requires SEGMENTED mode."
            )
        for cmd in self._scope._scpi_engine.build("seg_analyze"):
            self._scope._send_command(cmd)
        self._scope._wait()
        return self

    @validate_call
    def get_acquire_points(self) -> int:
        """Read back how many sample points one acquisition records."""
        return int(self._scope._query(self._scope._scpi_engine.build("acquire_points")[0]))

    @validate_call
    def get_acquisition_sample_rate(self) -> float:
        """Read back the acquisition sample rate, in samples per second."""
        return float(self._scope._query(self._scope._scpi_engine.build("acquire_sample_rate")[0]))

    @validate_call
    def get_acquire_setup(self) -> dict[str, str]:
        """Read back the full acquisition setup as a dictionary of instrument settings."""
        try:
            setup_query = self._scope._scpi_engine.build("acquire_setup")[0]
        except KeyError:
            # Infiniium MXR exposes the individual acquisition queries but not
            # the legacy aggregate ``:ACQuire?`` query used by some scopes.
            # Keep this method useful without inventing an unsupported command.
            fallback_aliases = (
                ("type", "acq_get_type"),
                ("mode", "acq_get_mode"),
                ("count", "acq_get_count"),
                ("points", "acquire_points"),
                ("sample_rate", "acquire_sample_rate"),
            )
            return {
                key: self._scope._query(self._scope._scpi_engine.build(alias)[0]).strip()
                for key, alias in fallback_aliases
            }

        raw_str: str = self._scope._query(setup_query).strip()
        parts: list[str] = [p.strip() for p in raw_str.split(";")]
        setup_dict: dict[str, str] = {}
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

    config: OscilloscopeConfig  # Type hint for validated config

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "run_self_test",
            public_method="run_self_test",
            required=False,
            group="diagnostics",
            scope="model",
            direct_python_only=True,
            direct_transport_queries=("self_test",),
        ),
        OperationDescriptor(
            "time_axis", public_method="set_time_axis", safety_class="state-changing", required=True
        ),
        OperationDescriptor(
            "channel_axis",
            public_method="set_channel_axis",
            safety_class="state-changing",
            required=True,
        ),
        OperationDescriptor(
            "channel_setup",
            public_method="setup_channel",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "configure_trigger",
            public_method="configure_trigger",
            safety_class="state-changing",
            required=True,
        ),
        OperationDescriptor(
            "set_acquisition_type",
            public_method="set_acquisition_type",
            safety_class="state-changing",
            required=True,
        ),
        OperationDescriptor(
            "set_acquisition_mode",
            public_method="set_acquisition_mode",
            safety_class="state-changing",
            required=True,
        ),
        OperationDescriptor(
            "acquisition",
            public_method="get_sampling_rate",
            safety_class="state-changing",
            required=True,
        ),
        OperationDescriptor(
            "segmented_acquisition",
            public_method="analyze_segments",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "waveform_readout", public_method="acquire_waveform", safety_class="read", required=True
        ),
        OperationDescriptor(
            "digitize", public_method="read_channels", safety_class="read", required=True
        ),
        OperationDescriptor(
            "measure_vpp",
            public_method="measure_voltage_peak_to_peak",
            safety_class="read",
            required=False,
        ),
        OperationDescriptor(
            "measure_vrms", public_method="measure_rms_voltage", safety_class="read", required=False
        ),
        OperationDescriptor(
            "measure_phase", public_method="measure_phase", safety_class="read", required=False
        ),
        OperationDescriptor(
            "measure_frequency",
            public_method="measure_frequency",
            safety_class="read",
            required=False,
        ),
        OperationDescriptor(
            "screenshot", public_method="screenshot", safety_class="read", required=False
        ),
        OperationDescriptor(
            "auto_scale", public_method="auto_scale", safety_class="state-changing", required=False
        ),
        OperationDescriptor(
            "run", public_method="run", safety_class="state-changing", required=False
        ),
        OperationDescriptor(
            "stop", public_method="stop", safety_class="state-changing", required=False
        ),
        OperationDescriptor(
            "system_lock", public_method="lock_panel", safety_class="state-changing", required=False
        ),
        OperationDescriptor(
            "display_channel",
            public_method="display_channel",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "set_wave_gen_func",
            capability="function_generator",
            public_method="set_wave_gen_func",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_basic",
            capability="function_generator",
            public_method="wave_gen",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_shapes",
            capability="function_generator",
            public_method="set_wgen_square",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "fft",
            capability="fft",
            public_method="configure_fft",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "fft_display",
            capability="fft",
            public_method="fft_display",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "function_display",
            capability="fft",
            public_method="function_display",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "frequency_response_analysis",
            capability="franalysis",
            public_method="franalysis_sweep",
            safety_class="state-changing",
            required=False,
        ),
        # Auxiliary public methods remain discoverable even on profiles that
        # do not implement the corresponding optional capability.
        OperationDescriptor(
            "time_axis_read", public_method="get_time_axis", safety_class="read", required=False
        ),
        OperationDescriptor(
            "channel_axis_read",
            public_method="get_channel_axis",
            safety_class="read",
            required=False,
        ),
        OperationDescriptor(
            "waveform_acquisition",
            public_method="acquire_waveforms",
            safety_class="read",
            required=False,
        ),
        OperationDescriptor(
            "probe_read", public_method="get_probe_attenuation", safety_class="read", required=False
        ),
        OperationDescriptor(
            "probe_write",
            public_method="set_probe_attenuation",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "acquisition_time",
            public_method="set_acquisition_time",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "sample_rate",
            public_method="set_sample_rate",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "bandwidth_limit",
            public_method="set_bandwidth_limit",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_frequency",
            public_method="set_wave_gen_freq",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_amplitude",
            public_method="set_wave_gen_amp",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_offset",
            public_method="set_wave_gen_offset",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_sine",
            public_method="set_wgen_sin",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_ramp",
            public_method="set_wgen_ramp",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_pulse",
            public_method="set_wgen_pulse",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_dc",
            public_method="set_wgen_dc",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "wave_generator_noise",
            public_method="set_wgen_noise",
            capability="function_generator",
            safety_class="state-changing",
            required=False,
        ),
        OperationDescriptor(
            "fft_read",
            public_method="read_fft_data",
            capability="fft",
            safety_class="read",
            required=False,
        ),
    )

    # visa_resource is handled by base Instrument or backend through config.address
    def __init__(
        self,
        config: OscilloscopeConfig,
        debug_mode: bool = False,
        simulate: bool = False,
        **kwargs: Any,
    ) -> None:  # config is now non-optional
        """
        Initialize the Oscilloscope class with the given VISA resource and profile information.

        Args:
        config (OscilloscopeConfig): Configuration object for the oscilloscope.
        debug_mode (bool): Enable debug mode. (Handled by base or backend)
        simulate (bool): Enable simulation mode. (Handled by base or backend)
        """
        # The config is already validated by the loader to be OscilloscopeConfig V2
        super().__init__(
            config=config, debug_mode=debug_mode, simulate=simulate, **kwargs
        )  # Pass kwargs
        # Initialize facades
        self.trigger = ScopeTriggerFacade(self)
        self.acquisition = ScopeAcquisitionFacade(self)

    @property
    def twin(self) -> Any:
        """Low-burden digital-twin validation helpers for this oscilloscope."""

        from pytestlab.twin import OscilloscopeTwinTools

        return OscilloscopeTwinTools(model=self.config.model)

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

    @validate_call
    def run(self) -> None:
        """Start continuous acquisition using the profile-defined operation."""
        for cmd in self._scpi_engine.build("run"):
            self._send_command(cmd)

    @validate_call
    def stop(self) -> None:
        """Stop acquisition using the profile-defined operation."""
        for cmd in self._scpi_engine.build("stop"):
            self._send_command(cmd)

    @classmethod
    def from_config(
        cls: type[Oscilloscope], config: InstrumentConfig, debug_mode: bool = False
    ) -> Oscilloscope:
        # This method aligns with the new __init__ signature.
        """Build an oscilloscope driver from an instrument configuration."""
        if not isinstance(config, OscilloscopeConfig):
            raise InstrumentConfigurationError(
                cls.__name__, "from_config expects an OscilloscopeConfig object."
            )
        return cls(config=config, debug_mode=debug_mode)

    def health_check(self) -> HealthReport:
        """
        Performs a basic health check of the oscilloscope instrument.

        Returns:
            HealthReport: A report containing the instrument's health status,
                          errors, warnings, and supported features.
        """
        report = HealthReport()

        try:
            # Get instrument identification
            report.instrument_idn = self.id()

            # Check for stored errors
            instrument_errors = self.get_all_errors()
            if instrument_errors:
                report.warnings.extend(
                    [f"Stored Error: {code} - {msg}" for code, msg in instrument_errors]
                )

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
            _ = self.get_time_axis()

            # Check supported features based on configuration
            if hasattr(self.config, "fft") and self.config.fft:
                report.supported_features["fft"] = True
            else:
                report.supported_features["fft"] = False

            if hasattr(self.config, "franalysis") and self.config.franalysis:
                report.supported_features["franalysis"] = True
            else:
                report.supported_features["franalysis"] = False

            if hasattr(self.config, "function_generator") and self.config.function_generator:
                report.supported_features["function_generator"] = True
            else:
                report.supported_features["function_generator"] = False

        except Exception as e:
            report.errors.append(f"Oscilloscope-specific check failed: {str(e)}")

        # Determine backend status
        if hasattr(self, "_backend") and hasattr(self._backend, "__class__"):
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

    def _read_preamble(self) -> Preamble:
        """Reads and parses the waveform preamble from the oscilloscope.

        The preamble contains essential metadata for interpreting the waveform data,
        such as scaling factors and offsets.

        Returns:
            A `Preamble` dataclass instance.
        """
        q = self._scpi_engine.build("wave_preamble")[0]
        parts = self._scpi_engine.parse("wave_preamble", self._query(q))
        self._logger.debug(parts)

        # Format of preamble:
        # format, type, points, count, xincrement, xorigin, xreference, yincrement, yorigin, yreference
        pre = Preamble(
            format=str(parts[0]),
            type=str(parts[1]),
            points=int(parts[2]),
            # parts[3] is count, not used directly in Preamble dataclass here
            xinc=float(parts[4]),
            xorg=float(parts[5]),
            xref=float(parts[6]),
            yinc=float(parts[7]),
            yorg=float(parts[8]),
            yref=float(parts[9]),
        )
        return pre

    def _validate_waveform_points(self, points: int | None, *, run_after: bool) -> None:
        if points is None:
            return
        if points <= 0:
            raise InstrumentParameterError(
                parameter="points", value=points, message="points must be a positive integer."
            )
        if not run_after:
            raise InstrumentParameterError(
                parameter="points",
                value=points,
                message="Read-only acquisition cannot change the waveform point count.",
            )
        operation = self.config.operation_options.operation("waveform_readout")
        if operation is None or not (
            operation.transport.get("points") or operation.transport.get("acquisition_points")
        ):
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not declare numeric waveform point control."
            )
        spec = operation.parameters.get("points")
        values = spec.constraints.get("values") if spec is not None else None
        if values is not None and points not in values:
            raise InstrumentParameterError(
                parameter="points",
                value=points,
                valid_range=tuple(values),
                message="Requested point count is not supported by the instrument profile.",
            )

    def _configure_acquisition_points(self, points: int) -> None:
        """Set profile-declared acquisition depth before digitizing."""
        operation = self.config.operation_options.operation("waveform_readout")
        transport = operation.transport if operation is not None else {}
        alias = transport.get("acquisition_points")
        if alias is None:
            return
        limits_query = transport.get("acquisition_points_limits_query")
        if limits_query is not None:
            response = self._query_profile_alias(limits_query)
            try:
                parameter_count, tagged_range = response.strip().split(",", 1)
                if parameter_count.strip() != "1" or not tagged_range.startswith("<numeric>"):
                    raise ValueError("expected one numeric point range")
                minimum, maximum = (
                    float(value) for value in tagged_range.removeprefix("<numeric>").split(":")
                )
                if not (
                    math.isfinite(minimum) and math.isfinite(maximum) and 0 < minimum <= maximum
                ):
                    raise ValueError("invalid point limits")
            except (TypeError, ValueError) as exc:
                raise InstrumentDataError(
                    self.config.model, f"Invalid acquisition point limits: {response!r}."
                ) from exc
            _validate_range(points, minimum, maximum, "points")
        self._send_profile_alias(alias, points=points)

    def _configure_waveform_transfer(
        self, source: str, waveform_format: str, *, points: int | None = None
    ) -> str | None:
        """Configure waveform transport before obtaining its scaling preamble."""

        normalized = self._resolve_waveform_format(waveform_format)
        operation = self.config.operation_options.operation("waveform_readout")
        if operation is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not declare waveform readout."
            )
        transport = operation.transport
        self._wait()
        self._send_profile_alias(transport["source"], source=source)
        self._wait()
        if points is None:
            self._send_profile_alias(transport["points_max"])
        format_alias = transport.get(f"format_{normalized}")
        if format_alias is None:
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not support waveform format '{normalized}'."
            )
        self._send_profile_alias(format_alias)
        if normalized == "word" and "byteorder_lsb" in transport:
            self._send_profile_alias(transport["byteorder_lsb"])
        mode_alias = None
        if source != "FFT":
            mode_key = "points_normal" if normalized == "word" else "points_raw"
            acquisition_mode_aliases = {
                key.removeprefix("points_mode_for_"): value
                for key, value in transport.items()
                if key.startswith("points_mode_for_")
            }
            if normalized == "byte" and acquisition_mode_aliases:
                acquisition_type = self.acquisition.get_acquisition_type().lower()
                mode_alias = acquisition_mode_aliases.get(acquisition_type) or (
                    transport.get(mode_key) or transport.get("points_raw")
                )
            else:
                mode_alias = transport.get(mode_key) or transport.get("points_raw")
            timebase_query = transport.get("timebase_mode_query")
            if mode_alias == transport.get("points_raw") and timebase_query:
                timebase_mode = self._query_profile_alias(timebase_query).strip().upper()
                if timebase_mode != "MAIN":
                    mode_alias = transport.get("points_normal")
                    if mode_alias is None:
                        raise InstrumentConfigurationError(
                            self.config.model,
                            "Profile has no measurement-record transfer for the current timebase.",
                        )
            if mode_alias is not None:
                self._send_profile_alias(mode_alias)
        if points is not None and "points" in transport:
            spec = operation.parameters.get("points")
            record = "normal" if mode_alias == transport.get("points_normal") else "raw"
            values_by_record = spec.constraints.get("values_by_record", {}) if spec else {}
            values = values_by_record.get(record)
            if values is not None and points not in values:
                raise InstrumentParameterError(
                    parameter="points",
                    value=points,
                    valid_range=tuple(values),
                    message=f"The selected {record} waveform record does not support this count.",
                )
            self._send_profile_alias(transport["points"], points=points)
        self._wait()
        return mode_alias

    @contextmanager
    def _preserve_channel_display(self, channels: list[int]):
        """Restore display state for instruments whose digitize operation changes it."""

        operation = self.config.operation_options.operation("waveform_readout")
        transport = operation.transport if operation is not None else {}
        query_alias = transport.get("channel_display_query")
        display_alias = transport.get("channel_display")
        if query_alias is None or display_alias is None:
            yield
            return

        states: dict[int, bool] = {}
        for channel in channels:
            response = self._query_profile_alias(query_alias, channel=channel).strip().upper()
            if response in {"1", "ON", "TRUE"}:
                states[channel] = True
            elif response in {"0", "OFF", "FALSE"}:
                states[channel] = False
            else:
                raise InstrumentDataError(
                    self.config.model,
                    f"Could not interpret channel {channel} display state: {response!r}.",
                )

        try:
            yield
        except BaseException:
            for channel, state in states.items():
                try:
                    self._send_profile_alias(display_alias, channel=channel, state=state)
                except Exception:
                    self._logger.exception(
                        "Could not restore channel %s display after waveform failure.", channel
                    )
            raise
        else:
            restore_error: Exception | None = None
            for channel, state in states.items():
                try:
                    self._send_profile_alias(display_alias, channel=channel, state=state)
                except Exception as exc:
                    if restore_error is None:
                        restore_error = exc
            if restore_error is not None:
                raise restore_error

    def _resolve_waveform_format(self, waveform_format: str) -> str:
        normalized = waveform_format.strip().lower()
        operation = self.config.operation_options.operation("waveform_readout")
        transport = operation.transport if operation is not None else {}
        if normalized == "auto":
            return "word" if "format_word" in transport else "byte"
        if normalized not in {"byte", "word"}:
            raise InstrumentParameterError(
                parameter="waveform_format",
                value=waveform_format,
                valid_range=("auto", "byte", "word"),
                message="waveform format must be 'auto', 'byte', or 'word'.",
            )
        if f"format_{normalized}" not in transport:
            raise InstrumentParameterError(
                parameter="waveform_format",
                value=waveform_format,
                valid_range=tuple(
                    candidate
                    for candidate in ("byte", "word")
                    if f"format_{candidate}" in transport
                ),
                message=f"{self.config.model} does not define {normalized.upper()} transfer.",
            )
        return normalized

    def _read_current_waveform_source(self) -> int:
        """Return the currently selected analog waveform channel without changing it."""

        response = self._query_profile_alias("wave_source").strip()
        try:
            semantic = self._resolve_transport_response("waveform_readout", "channel", response)
        except OperationDiscoveryError as exc:
            raise InstrumentDataError(
                self.config.model,
                "Profile could not map the current waveform source to a channel.",
            ) from exc
        if not isinstance(semantic, str) or not semantic.startswith("channel_"):
            raise InstrumentDataError(
                self.config.model,
                "Profile waveform source mapping did not resolve to a channel.",
            )
        try:
            return int(semantic.rsplit("_", 1)[1])
        except (ValueError, IndexError) as exc:
            raise InstrumentDataError(
                self.config.model,
                "Profile waveform source mapping contains an invalid channel.",
            ) from exc

    def _waveform_source_for_channel(self, channel: int) -> str:
        """Resolve a semantic channel to the profile's private waveform source."""

        resolved = self._resolve_operation_parameter(
            "waveform_readout", "channel", f"channel_{channel}"
        )
        return str(resolved.transport_value)

    def _read_current_waveform_format(self) -> str:
        """Return the current binary transfer width without changing instrument state."""

        response = self._query_profile_alias("wave_format").strip().upper()
        if response.startswith("BYTE"):
            return "byte"
        if response.startswith("WORD"):
            return "word"
        raise InstrumentDataError(
            self.config.model,
            f"Current waveform format {response!r} is not a supported binary transfer.",
        )

    def _read_current_waveform_byteorder(self) -> str:
        response = self._query_profile_alias("wave_byteorder").strip().upper()
        if response.startswith("LSB"):
            return "little"
        if response.startswith("MSB"):
            return "big"
        raise InstrumentDataError(
            self.config.model,
            "Profile could not map the waveform byte-order response.",
        )

    def _read_wave_data(
        self,
        source: str,
        *,
        preamble: Preamble | None = None,
        waveform_format: str = "byte",
        byteorder: str | None = None,
    ) -> np.ndarray:
        """Reads the raw waveform data block for a given source.

        The caller configures the transfer before reading the preamble. This
        method only reads and decodes the resulting binary block.

        Args:
            source: The waveform source to read (e.g., "CHANnel1", "FFT").
            preamble: Scaling metadata captured after configuring the transfer.
            waveform_format: Resolved binary transport format (BYTE or WORD).

        Returns:
            A NumPy array of the raw, unprocessed ADC values.
        """
        self._logger.debug(f"Reading data from {source}")
        # Query and parse binblock via SCPIEngine
        q = self._scpi_engine.build("wave_data")[0]
        bin_bytes: bytes = self._scpi_engine.parse("wave_data", self._query_raw(q))
        normalized = waveform_format.strip().lower()
        y_reference = preamble.yref if preamble is not None else None
        if y_reference is None:
            raise InstrumentDataError(
                self.config.model,
                "Waveform preamble must provide y-reference for binary decoding.",
            )
        if normalized == "word":
            if byteorder is None:
                raise InstrumentDataError(
                    self.config.model,
                    "WORD waveform decoding requires the current byte order.",
                )
            dtype = self._waveform_word_dtype(y_reference=y_reference, byteorder=byteorder)
        else:
            dtype = self._waveform_byte_dtype(y_reference=y_reference)
        return np.frombuffer(bin_bytes, dtype=dtype)

    @staticmethod
    def _waveform_byte_dtype(*, y_reference: float) -> np.dtype:
        """Return BYTE signedness declared by the waveform preamble."""
        return np.dtype(np.uint8 if 0.5 <= float(y_reference) <= 255.0 else np.int8)

    @staticmethod
    def _waveform_word_dtype(*, y_reference: float, byteorder: str) -> np.dtype:
        """Return WORD signedness and byte order declared by transfer metadata."""
        if byteorder not in {"little", "big"}:
            raise InstrumentDataError(
                "oscilloscope", f"Unsupported waveform byte order {byteorder!r}."
            )
        prefix = "<" if byteorder == "little" else ">"
        code = "u2" if float(y_reference) >= 0.5 else "i2"
        return np.dtype(prefix + code)

    @validate_call
    def lock_panel(self, lock: bool = True) -> None:
        """
        Locks the panel of the instrument

        Args:
            lock (bool): True to lock the panel, False to unlock it
        """
        arguments = self._resolve_operation_arguments("system_lock", {"lock": lock})
        for alias, params in arguments.items():
            self._send_profile_alias(alias, **params)

    @validate_call
    def auto_scale(self) -> None:
        """
        Auto scale the oscilloscope display.

        This method sends an SCPI command to the oscilloscope to auto scale the display.

        Example:
        >>> auto_scale()
        """
        operation = self.config.operation_options.operation("auto_scale")
        transport = operation.transport if operation is not None else {}
        selection_query = transport.get("channel_selection_query")
        display_query = transport.get("channel_display_query")
        if selection_query and display_query:
            selection = self._query_profile_alias(selection_query).strip().upper()
            if selection.startswith("DISP"):
                any_displayed = False
                for channel in range(1, len(self.config.channels) + 1):
                    state = (
                        self._query_profile_alias(display_query, channel=channel).strip().upper()
                    )
                    if state in {"1", "ON", "TRUE"}:
                        any_displayed = True
                        break
                    if state not in {"0", "OFF", "FALSE"}:
                        raise InstrumentDataError(
                            self.config.model,
                            f"Could not interpret channel {channel} display state: {state!r}.",
                        )
                if not any_displayed:
                    raise InstrumentParameterError(
                        parameter="channels",
                        value=[],
                        message=(
                            "Autoscale is configured for displayed channels, but no channel is "
                            "displayed. Explicitly enable the task's measurement channel first."
                        ),
                    )
            elif selection != "ALL":
                raise InstrumentDataError(
                    self.config.model,
                    f"Could not interpret autoscale channel selection: {selection!r}.",
                )
        for cmd in self._scpi_engine.build("auto_scale"):
            self._send_command(cmd)

    @validate_call
    def set_time_axis(self, scale: float, position: float) -> None:
        """
        Sets the time axis of the Oscilloscope. (x-axis)

        :param scale: scale The scale of the axis in seconds
        :param position: The position of the time axis from the trigger in seconds
        """
        timebase_range = None
        # Prefer explicit timebase settings, fall back to first channel metadata.
        timebase_settings = getattr(self.config, "timebase_settings", None)
        if timebase_settings is not None:
            tb_range = getattr(timebase_settings, "range", None)
            if tb_range is not None:
                timebase_range = tb_range
        elif self.config.channels:
            first_channel = self.config.channels[0]
            channel_tb = getattr(first_channel, "timebase", None)
            timebase_range = getattr(channel_tb, "range", None)

        scale = float(self._resolve_operation_parameter("time_axis", "scale", scale).value)
        if not math.isfinite(scale):
            valid_range = None
            if timebase_range is not None:
                valid_range = (timebase_range.min_val, timebase_range.max_val)
            raise InstrumentParameterError(
                parameter="scale",
                value=scale,
                valid_range=valid_range,
                message="Scale must be a finite value.",
            )
        if timebase_range is not None:
            timebase_range.assert_in_range(scale, "scale")
        elif scale <= 0:
            raise InstrumentParameterError(
                parameter="scale",
                value=scale,
                valid_range=(0.0, math.inf),
                message="Scale must be greater than zero.",
            )

        position = float(self._resolve_operation_parameter("time_axis", "position", position).value)
        if not math.isfinite(position):
            raise InstrumentParameterError(
                parameter="position", value=position, message="Position must be finite."
            )
        operation = self.config.operation_options.operation("time_axis")
        mode = self._time_axis_mode(operation)
        self._validate_time_position(operation, scale, position, mode, conditional=False)
        self._apply_time_axis(operation, scale, position, mode)
        self._wait()

    def _apply_time_axis(self, operation, scale, position, mode, *, range_commands=None):
        if operation is not None and operation.transport.get("scale_only"):
            scale_alias = operation.transport["scale_only"]
            position_alias = operation.transport["position_only"]
            scale_commands = (
                range_commands
                if range_commands is not None
                else self._build_profile_alias(scale_alias, scale=scale)
            )

            def read_setting(name):
                response = self._query_profile_alias(operation.context_queries[name]).strip()
                try:
                    value = float(response)
                except ValueError as exc:
                    raise InstrumentDataError(
                        self.config.model, f"Invalid timebase {name}: {response!r}."
                    ) from exc
                if not math.isfinite(value) or (name == "current_scale" and value <= 0):
                    raise InstrumentDataError(
                        self.config.model, f"Invalid timebase {name}: {response!r}."
                    )
                return value

            current_position = read_setting("current_position")
            retain_position = position is None
            if retain_position:
                position = current_position
            current_scale = (
                read_setting("current_scale") if current_position != 0 or position != 0 else None
            )
            try:
                self._validate_time_position(
                    operation, scale, position, mode, conditional=current_scale == scale
                )
            except InstrumentParameterError:
                if retain_position:
                    position = 0.0
                else:
                    raise
            self._build_profile_alias(position_alias, position=position)
            neutralized = False
            if current_position != 0 and current_scale != scale:
                self._send_profile_alias(position_alias, position=0.0)
                neutralized = True
            for command in scale_commands:
                self._send_command(command)
            if position != 0:
                effective_scale = read_setting("current_scale")
                try:
                    self._validate_time_position(operation, effective_scale, position, mode)
                except InstrumentParameterError as exc:
                    if retain_position:
                        position = 0.0
                    else:
                        raise InstrumentParameterError(
                            parameter="position",
                            value=position,
                            message=f"Position is invalid at effective timebase scale {effective_scale} s/div: {exc}",
                        ) from exc
            if position != 0 or not (neutralized or (retain_position and current_position == 0)):
                self._send_profile_alias(position_alias, position=position)
        else:
            commands = (
                range_commands
                if range_commands is not None
                else self._scpi_engine.build("set_time_axis", scale=scale, position=position)
            )
            for cmd in commands:
                self._send_command(cmd)

    def _time_axis_mode(self, operation):
        if operation is None or not operation.context_queries.get("mode"):
            return None
        return self._query_profile_alias(operation.context_queries["mode"]).strip().upper()

    def _validate_time_position(self, operation, scale, position, mode, *, conditional=True):
        spec = operation.parameters.get("position") if operation is not None else None
        if spec is None:
            return
        if mode in spec.constraints.get("unavailable_modes", ()):
            raise InstrumentParameterError(
                parameter="mode",
                value=mode,
                message=f"Timebase range and position are unavailable in {mode} mode.",
            )
        bounds = spec.constraints.get("native_position_bounds")
        if not bounds or (bounds.get("modes") and mode not in bounds["modes"]):
            return

        def limit(bound):
            if not isinstance(bound, dict):
                return Decimal(str(bound))
            if not conditional:
                cap = bound.get("at_most")
                if "ceil_sequence" in bound:
                    cap = bound["ceil_sequence"][-1]
                value = Decimal(str(cap)) if cap is not None else Decimal("Infinity")
                return -value if bound.get("negative") else value
            value = Decimal(str(scale)) * Decimal(str(bound["scale_multiplier"]))
            if "ceil_sequence" in bound:
                value = next(
                    (
                        Decimal(str(entry))
                        for entry in bound["ceil_sequence"]
                        if Decimal(str(entry)) >= value
                    ),
                    Decimal(str(bound["ceil_sequence"][-1])),
                )
            if "at_least" in bound:
                value = max(value, Decimal(str(bound["at_least"])))
            if "at_most" in bound:
                value = min(value, Decimal(str(bound["at_most"])))
            return -value if bound.get("negative") else value

        minimum, maximum = limit(bounds["minimum"]), limit(bounds["maximum"])
        if not minimum <= Decimal(str(position)) <= maximum:
            raise InstrumentParameterError(
                parameter="position",
                value=position,
                valid_range=(float(minimum), float(maximum)),
                message="Position is outside the qualified native range for this timebase scale.",
            )

    @validate_call
    def get_time_axis(self) -> list[float]:
        """
        Gets the time axis of the oscilloscope. (x-axis)

        :return: A list containing the time axis scale and position
        """
        s = self._scpi_engine.parse(
            "get_timebase_scale", self._query(self._scpi_engine.build("get_timebase_scale")[0])
        )
        p = self._scpi_engine.parse(
            "get_timebase_position",
            self._query(self._scpi_engine.build("get_timebase_position")[0]),
        )
        return [np.float64(s), np.float64(p)]

    def _channel_axis_context(self, channel: int, profile_operation) -> dict[str, float]:
        scale_spec = profile_operation.parameters.get("scale") if profile_operation else None
        context = {}
        if scale_spec is not None and scale_spec.dependencies:
            context_queries = profile_operation.context_queries
            probe_alias = context_queries.get("probe_attenuation")
            if not probe_alias:
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Contextual channel-scale limits require a profile probe query.",
                )
            probe_response = self._query_profile_alias(probe_alias, channel=channel).strip()
            try:
                probe_attenuation = float(probe_response.split(",", 1)[0].strip())
            except ValueError as exc:
                raise InstrumentDataError(
                    self.config.model,
                    f"Profile probe response is not numeric: {probe_response!r}",
                ) from exc
            if not math.isfinite(probe_attenuation) or probe_attenuation <= 0:
                raise InstrumentDataError(
                    self.config.model,
                    f"Profile probe response is not a positive finite attenuation: {probe_response!r}",
                )

            impedance_alias = context_queries.get("input_impedance")
            if impedance_alias:
                impedance_response = (
                    self._query_profile_alias(impedance_alias, channel=channel)
                    .strip()
                    .strip('"')
                    .upper()
                )
                if impedance_response in {"DC50", "DCFIFTY", "50", "FIFTY"}:
                    input_impedance = 50
                elif impedance_response in {"DC", "AC", "ONEMEG", "1M", "1000000"}:
                    input_impedance = 1000000
                else:
                    raise InstrumentDataError(
                        self.config.model,
                        "Profile input impedance response is not recognized: "
                        f"{impedance_response!r}",
                    )
            else:
                try:
                    input_impedance = float(self.config.channels[channel - 1].input_impedance)
                except (AttributeError, IndexError, TypeError, ValueError) as exc:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Contextual channel-scale limits require a profile input-impedance query "
                        "or a fixed channel input_impedance value.",
                    ) from exc
            context.update(
                probe_attenuation=probe_attenuation,
                input_impedance=input_impedance,
            )
        return context

    def _prepare_channel_axis(self, channel, scale, offset, *, context=None):
        channel = int(self._resolve_operation_parameter("channel_axis", "channel", channel).value)
        profile_operation = self.config.operation_options.operation("channel_axis")
        arguments = {"channel": channel, "scale": scale, "offset": offset}
        arguments.update(
            self._channel_axis_context(channel, profile_operation) if context is None else context
        )

        write_alias = (
            profile_operation.transport.get("write", "set_channel_axis")
            if profile_operation is not None
            else "set_channel_axis"
        )
        resolved = self._resolve_operation_arguments("channel_axis", arguments).get(write_alias, {})
        channel = int(resolved.get("channel", channel))
        scale = resolved.get("scale", scale)
        offset = resolved.get("offset", offset)
        scale = float(scale)
        offset = float(offset)
        if not math.isfinite(scale) or scale <= 0:
            raise InstrumentParameterError(
                parameter="scale", value=scale, message="Scale must be finite and positive."
            )
        if not math.isfinite(offset):
            raise InstrumentParameterError(
                parameter="offset", value=offset, message="Offset must be finite."
            )
        return channel, scale, offset, arguments, profile_operation

    @validate_call
    def set_channel_axis(self, channel: int, scale: float, offset: float) -> None:
        """Set volts/div and offset after validating their complete native context.

        Quantized scale is read back before applying nonzero offset. A rejected
        offset can therefore leave a valid scale change applied.
        """
        channel, scale, offset, arguments, profile_operation = self._prepare_channel_axis(
            channel, scale, offset
        )

        commands = self._scpi_engine.build(
            "set_channel_axis", channel=channel, scale=scale, offset=offset
        )
        offset_spec = (
            profile_operation.parameters.get("offset") if profile_operation is not None else None
        )
        if (
            profile_operation is not None
            and offset_spec is not None
            and offset_spec.contextual_ranges
        ):
            offset_query = profile_operation.context_queries.get("current_offset")
            scale_query = profile_operation.context_queries.get("current_scale")
            offset_alias = profile_operation.transport.get("offset_only")
            scale_alias = profile_operation.transport.get("scale_only")
            if not offset_query or not scale_query or not offset_alias or not scale_alias:
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Contextual offset limits require profile scale/offset queries and setters.",
                )
            scale_commands = self._build_profile_alias(scale_alias, channel=channel, scale=scale)
            offset_commands = self._build_profile_alias(
                offset_alias, channel=channel, offset=offset
            )

            def read_axis_setting(alias: str, name: str) -> float:
                response = self._query_profile_alias(alias, channel=channel).strip()
                try:
                    value = float(response)
                except ValueError as exc:
                    raise InstrumentDataError(
                        self.config.model, f"Current channel {name} is not numeric: {response!r}."
                    ) from exc
                if not math.isfinite(value) or (name == "scale" and value <= 0):
                    raise InstrumentDataError(
                        self.config.model, f"Current channel {name} is invalid: {response!r}."
                    )
                return value

            current_offset = read_axis_setting(offset_query, "offset")
            neutralized = False
            if current_offset != 0 and offset_spec.constraints.get(
                "neutralize_offset_on_scale_change"
            ):
                current_scale = read_axis_setting(scale_query, "scale")
                if current_scale != scale:
                    self._resolve_operation_parameter(
                        "channel_axis", "offset", 0.0, context={**arguments, "scale": scale}
                    )
                    self._send_profile_alias(offset_alias, channel=channel, offset=0.0)
                    neutralized = True
            for command in scale_commands:
                self._send_command(command)
            if offset != 0:
                effective_scale = read_axis_setting(scale_query, "scale")
                try:
                    self._resolve_operation_parameter(
                        "channel_axis",
                        "offset",
                        offset,
                        context={**arguments, "scale": effective_scale},
                    )
                except InstrumentParameterError as exc:
                    raise InstrumentParameterError(
                        parameter="offset",
                        value=offset,
                        message=f"Offset is invalid at effective scale {effective_scale} V/div: {exc}",
                    ) from exc
            if offset != 0 or not neutralized:
                for command in offset_commands:
                    self._send_command(command)
        else:
            for cmd in commands:
                self._send_command(cmd)
        self._wait()

    def _setup_channel(
        self,
        channel,
        *,
        scale=None,
        position=None,
        offset=None,
        coupling=None,
        probe_attenuation=None,
        bandwidth_limit=None,
    ) -> None:
        if all(
            value is None
            for value in (scale, position, offset, coupling, probe_attenuation, bandwidth_limit)
        ):
            return
        arguments = {
            name: value
            for name, value in {
                "channel": channel,
                "coupling": coupling,
                "probe_attenuation": probe_attenuation,
                "bandwidth_limit": bandwidth_limit,
            }.items()
            if value is not None
        }
        resolved = self._resolve_operation_arguments("channel_setup", arguments)
        channel_result = self._resolve_operation_parameter("channel_setup", "channel", channel)
        channel = int(channel_result.value)
        operation = self.config.operation_options.operation("channel_setup")
        transport = (
            operation.transport
            if operation is not None
            else {
                "coupling": "set_channel_coupling",
                "probe": "probe_set",
                "bandwidth": "channel_bandwidth",
            }
        )
        commands = {}
        for name, requested in (
            ("coupling", coupling),
            ("probe", probe_attenuation),
            ("bandwidth", bandwidth_limit),
        ):
            if requested is not None:
                if name == "bandwidth":
                    commands[name] = self._bandwidth_commands(channel, requested)
                    continue
                alias = transport[name]
                commands[name] = self._build_profile_alias(
                    alias, **{"channel": channel, **resolved[alias]}
                )

        prospective_impedance = None
        if coupling is not None:
            choice = self._resolve_operation_parameter("channel_setup", "coupling", coupling)
            if choice.option is not None:
                prospective_impedance = choice.option.constraints.get("input_impedance")
        explicit_axis = any(value is not None for value in (scale, position, offset))
        for name, value in (("scale", scale), ("position", position), ("offset", offset)):
            if value is not None and (not math.isfinite(value) or (name == "scale" and value <= 0)):
                raise InstrumentParameterError(
                    parameter=name,
                    value=value,
                    message="Axis values must be finite and scale positive.",
                )

        axis_operation = self.config.operation_options.operation("channel_axis")
        bridge = False
        current_context = None
        prospective_context = None
        final_scale = None
        current_scale = None
        ratio = 1.0
        if explicit_axis or prospective_impedance is not None:
            current_context = self._channel_axis_context(channel, axis_operation)
            prospective_context = dict(current_context)
            ratio = 1.0
            if probe_attenuation is not None and "probe_attenuation" in current_context:
                requested_probe = self._resolve_operation_parameter(
                    "channel_setup", "probe_attenuation", probe_attenuation
                ).value
                ratio = requested_probe / current_context["probe_attenuation"]
                prospective_context["probe_attenuation"] = requested_probe
            if prospective_impedance is not None:
                prospective_context["input_impedance"] = prospective_impedance
            current_scale, current_offset = self.get_channel_axis(channel)
            final_scale = scale if scale is not None else float(current_scale) * ratio
            final_offset = position if position is not None else offset
            if final_offset is None:
                final_offset = float(current_offset) * ratio
            _, final_scale, final_offset, _, _ = self._prepare_channel_axis(
                channel, final_scale, final_offset, context=prospective_context
            )
            if prospective_context.get("input_impedance") != current_context.get("input_impedance"):
                try:
                    self._prepare_channel_axis(
                        channel,
                        float(current_scale) * ratio,
                        float(current_offset) * ratio,
                        context=prospective_context,
                    )
                except InstrumentParameterError:
                    bridge = True
                    bridge_context = {
                        **current_context,
                        "probe_attenuation": prospective_context.get("probe_attenuation", 1),
                    }
                    self._prepare_channel_axis(channel, final_scale, 0.0, context=bridge_context)

        if bandwidth_limit is not None:
            choice = self._resolve_operation_parameter(
                "channel_setup", "bandwidth_limit", bandwidth_limit
            )
            sensitivity = self._bandwidth_sensitivity_constraint("channel_setup", "bandwidth_limit")
            if str(choice.value).casefold() == "full" and sensitivity:
                if current_context is None:
                    current_context = self._channel_axis_context(channel, axis_operation)
                if current_scale is None:
                    current_scale, _current_offset = self.get_channel_axis(channel)
                bandwidth_context = dict(current_context)
                if prospective_impedance is not None:
                    bandwidth_context["input_impedance"] = prospective_impedance
                if probe_attenuation is not None:
                    requested_probe = self._resolve_operation_parameter(
                        "channel_setup", "probe_attenuation", probe_attenuation
                    ).value
                    bandwidth_context["probe_attenuation"] = requested_probe
                    final_scale = (
                        scale
                        if scale is not None
                        else float(current_scale)
                        * (requested_probe / current_context["probe_attenuation"])
                    )
                elif final_scale is None:
                    final_scale = scale if scale is not None else float(current_scale)
                self._validate_bandwidth_sensitivity(
                    "bandwidth_limit",
                    bandwidth_limit,
                    final_scale,
                    bandwidth_context,
                    sensitivity,
                )

        for command in commands.get("probe", ()):
            self._send_command(command)
        if bridge:
            assert final_scale is not None
            self.set_channel_axis(channel, final_scale, 0.0)
        for command in commands.get("coupling", ()):
            self._send_command(command)
        if explicit_axis or prospective_impedance is not None:
            assert final_scale is not None and final_offset is not None
            actual_context = self._channel_axis_context(channel, axis_operation)
            self._prepare_channel_axis(channel, final_scale, final_offset, context=actual_context)
            if explicit_axis or bridge:
                self.set_channel_axis(channel, final_scale, final_offset)
        for command in commands.get("bandwidth", ()):
            self._send_command(command)

    @validate_call
    def setup_channel(
        self,
        channel: int,
        coupling: str | None = None,
        probe_attenuation: float | None = None,
        bandwidth_limit: str | float | None = None,
    ) -> None:
        """Validate the complete request before applying channel input settings."""
        self._setup_channel(
            channel,
            coupling=coupling,
            probe_attenuation=probe_attenuation,
            bandwidth_limit=bandwidth_limit,
        )

    @validate_call
    def get_channel_axis(self, channel: int) -> list[float]:
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

        s = self._scpi_engine.parse(
            "get_channel_scale",
            self._query(self._scpi_engine.build("get_channel_scale", channel=channel)[0]),
        )
        o = self._scpi_engine.parse(
            "get_channel_offset",
            self._query(self._scpi_engine.build("get_channel_offset", channel=channel)[0]),
        )
        return [np.float64(s), np.float64(o)]

    @validate_call
    def configure_trigger(
        self,
        channel: int,
        level: float,
        source: str | None = None,
        slope: str = "positive",
        mode: str = "EDGE",
    ) -> None:
        """
        Sets the trigger for the oscilloscope.

        :param channel: The channel to set the trigger for (used if source is None or a channel itself)
        :param level: The trigger level in volts
        :param source: The source of the trigger. Default behaviour is to use the channel. Valid options CHANnel<n> | EXTernal | LINE | WGEN
        :param slope: Semantic trigger slope; defaults to ``positive``.
        :param mode: The trigger mode. Default is 'EDGE'
        """

        source_context = source if source is not None else f"channel_{channel}"
        resolved = self._resolve_operation_arguments(
            "configure_trigger",
            {
                "channel": channel,
                "level": level,
                "source": source_context,
                "slope": slope,
                "mode": mode,
            },
        )
        trigger_arguments = resolved.get("configure_trigger", {})
        actual_source = trigger_arguments.get("source", source_context)
        scpi_slope = trigger_arguments.get("slope", slope)
        scpi_mode = trigger_arguments.get("mode", mode)

        for cmd in self._scpi_engine.build(
            "configure_trigger",
            source=actual_source,
            level=trigger_arguments.get("level", level),
            channel=trigger_arguments.get("channel", channel),
            slope=scpi_slope,
            mode=scpi_mode,
        ):
            self._send_command(cmd)
        self._wait()
        self._logger.debug(
            f"Trigger set → source={actual_source}, level={level}, slope={scpi_slope}, mode={scpi_mode}"
        )
        return

    @validate_call
    def measure_voltage_peak_to_peak(
        self, channel: int, *, uncertainty: bool = True
    ) -> MeasurementResult:
        """
        Measure the peak-to-peak voltage for a specified channel.

        Args:
        channel (int): The channel identifier.

        Returns:
        MeasurementResult: An object containing the peak-to-peak voltage measurement.
        """
        channel = int(self._resolve_operation_parameter("measure_vpp", "channel", channel).value)
        q = self._scpi_engine.build("measure_vpp", channel=channel)[0]
        raw_response = self._query(q)
        reading = float(self._scpi_engine.parse("measure_vpp", raw_response))
        if reading in {9.9e37, -9.9e37, 9.99999e37, -9.99999e37}:
            raise InstrumentDataError(
                self.config.model,
                f"Vpp measurement is unavailable on channel {channel}; instrument returned "
                f"the documented sentinel {raw_response!r}.",
            )

        value_to_return: float | MeasurementQuantity = reading
        if uncertainty:
            value_to_return = nominal_measurement_quantity(
                reading,
                "V",
                function="measure_vpp",
                output_name=f"vpp_ch{channel}",
                reason=(
                    f"{self.config.model} Vpp channel {channel}: no applied uncertainty metadata "
                    "yet; result is nominal-only and non-report-grade."
                ),
            )

        if uncertainty and self.config.measurement_accuracy:
            mode_key = f"vpp_ch{channel}"
            self._logger.debug(
                f"Attempting to find accuracy spec for Vpp on channel {channel} with key: '{mode_key}'"
            )
            spec = self.config.measurement_accuracy.get(mode_key)
            spec_key = mode_key
            if spec is None:
                spec_key = f"waveform_ch{channel}"
                spec = self.config.measurement_accuracy.get(spec_key)
            if spec:
                context = oscilloscope_measurement_context(
                    self.config,
                    channel=channel,
                    reading=reading,
                    unit="V",
                    function="measure_vpp",
                    instrument_key=self._uncertainty_source_key(),
                )
                quantity = nonzero_uncertainty_quantity(
                    spec,
                    context,
                    logger=self._logger,
                    label=f"accuracy spec '{spec_key}'",
                    strict=self.config.uncertainty_strict,
                )
                if quantity is not None:
                    value_to_return = quantity
            else:
                value_to_return = nominal_measurement_quantity(
                    reading,
                    "V",
                    function="measure_vpp",
                    output_name=f"vpp_ch{channel}",
                    reason=(
                        f"{self.config.model} Vpp channel {channel}: missing "
                        f"measurement_accuracy keys {mode_key!r} or {spec_key!r}; "
                        "add an accuracy spec."
                    ),
                )
                self._logger.debug(
                    "No accuracy spec found for Vpp on channel %s with keys %r or %r; returning "
                    "nominal-only non-report-grade Quantity.",
                    channel,
                    mode_key,
                    spec_key,
                )
        elif uncertainty:
            self._logger.debug(
                "No measurement_accuracy configuration in instrument for Vpp on channel %s; "
                "returning nominal-only non-report-grade Quantity.",
                channel,
            )

        measurement_result = MeasurementResult(
            values=value_to_return, units="V", instrument=self.config.model, measurement_type="P2PV"
        )

        self._logger.debug(f"Peak to Peak Voltage (Channel {channel}): {value_to_return}")

        return measurement_result

    @validate_call
    def measure_frequency(self, channel: int, *, uncertainty: bool = True) -> MeasurementResult:
        """Query the scope's channel-frequency measurement in Hz.

        With ``uncertainty=False``, ``values`` is the scalar instrument reading.
        Otherwise the result is explicitly nominal-only and non-report-grade:
        no calibrated scalar-frequency uncertainty model is applied.
        """
        channel = int(
            self._resolve_operation_parameter("measure_frequency", "channel", channel).value
        )
        query = self._scpi_engine.build("measure_frequency", channel=channel)[0]
        raw_response = self._query(query)
        reading = float(self._scpi_engine.parse("measure_frequency", raw_response))
        if not math.isfinite(reading) or reading <= 0 or reading in {9.9e37, 9.99999e37}:
            raise InstrumentDataError(
                self.config.model,
                f"Frequency measurement is unavailable on channel {channel}; "
                f"instrument returned {raw_response!r}.",
            )
        value: float | MeasurementQuantity = reading
        if uncertainty:
            value = nominal_measurement_quantity(
                reading,
                "Hz",
                function="measure_frequency",
                output_name=f"frequency_ch{channel}",
                reason=(
                    f"{self.config.model} frequency channel {channel}: no applied scalar-frequency "
                    "uncertainty metadata; result is nominal-only and non-report-grade."
                ),
            )
        return MeasurementResult(
            values=value,
            units="Hz",
            instrument=self.config.model,
            measurement_type="FREQUENCY",
        )

    @validate_call
    def measure_phase(self, channel: int, *, uncertainty: bool = True) -> MeasurementResult:
        """Measure channel phase in degrees through the profile abstraction."""
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )
        query = self._scpi_engine.build("measure_phase", channel=channel)[0]
        reading = float(self._scpi_engine.parse("measure_phase", self._query(query)))
        value: float | MeasurementQuantity = reading
        if uncertainty:
            value = nominal_measurement_quantity(
                reading,
                "degree",
                function="measure_phase",
                output_name=f"phase_ch{channel}",
                reason=(
                    f"{self.config.model} phase channel {channel}: no applied uncertainty "
                    "metadata yet; result is nominal-only and non-report-grade."
                ),
            )
        return MeasurementResult(
            values=value,
            units="degree",
            instrument=self.config.model,
            measurement_type="PHASE",
        )

    @validate_call
    def measure_rms_voltage(self, channel: int, *, uncertainty: bool = True) -> MeasurementResult:
        """
        Measure the root-mean-square (RMS) voltage for a specified channel.

        Args:
        channel (int): The channel identifier.

        Returns:
        MeasurementResult: An object containing the RMS voltage measurement.
        """
        channel = int(self._resolve_operation_parameter("measure_vrms", "channel", channel).value)
        q = self._scpi_engine.build("measure_vrms", channel=channel)[0]
        reading = float(self._scpi_engine.parse("measure_vrms", self._query(q)))

        value_to_return: float | MeasurementQuantity = reading
        if uncertainty:
            value_to_return = nominal_measurement_quantity(
                reading,
                "V",
                function="measure_vrms",
                output_name=f"vrms_ch{channel}",
                reason=(
                    f"{self.config.model} Vrms channel {channel}: no applied uncertainty metadata "
                    "yet; result is nominal-only and non-report-grade."
                ),
            )

        if uncertainty and self.config.measurement_accuracy:
            mode_key = f"vrms_ch{channel}"
            self._logger.debug(
                f"Attempting to find accuracy spec for Vrms on channel {channel} with key: '{mode_key}'"
            )
            spec = self.config.measurement_accuracy.get(mode_key)
            spec_key = mode_key
            if spec is None:
                spec_key = f"waveform_ch{channel}"
                spec = self.config.measurement_accuracy.get(spec_key)
            if spec:
                context = oscilloscope_measurement_context(
                    self.config,
                    channel=channel,
                    reading=reading,
                    unit="V",
                    function="measure_vrms",
                    instrument_key=self._uncertainty_source_key(),
                )
                quantity = nonzero_uncertainty_quantity(
                    spec,
                    context,
                    logger=self._logger,
                    label=f"accuracy spec '{spec_key}'",
                    strict=self.config.uncertainty_strict,
                )
                if quantity is not None:
                    value_to_return = quantity
            else:
                value_to_return = nominal_measurement_quantity(
                    reading,
                    "V",
                    function="measure_vrms",
                    output_name=f"vrms_ch{channel}",
                    reason=(
                        f"{self.config.model} Vrms channel {channel}: missing "
                        f"measurement_accuracy keys {mode_key!r} or {spec_key!r}; "
                        "add an accuracy spec."
                    ),
                )
                self._logger.debug(
                    "No accuracy spec found for Vrms on channel %s with keys %r or %r; returning "
                    "nominal-only non-report-grade Quantity.",
                    channel,
                    mode_key,
                    spec_key,
                )
        elif uncertainty:
            self._logger.debug(
                "No measurement_accuracy configuration in instrument for Vrms on channel %s; "
                "returning nominal-only non-report-grade Quantity.",
                channel,
            )

        self._logger.debug(f"RMS Voltage (Channel {channel}): {value_to_return}")

        measurement_result = MeasurementResult(
            values=value_to_return,
            instrument=self.config.model,
            units="V",
            measurement_type="rms_voltage",
        )
        return measurement_result

    @validate_call
    def read_channels(
        self,
        *channels: int | list[int] | tuple[int, ...],
        run_after: bool = True,
        timebase: float | None = None,
        timeout_ms: int | None = None,
        waveform_format: str = "byte",
        points: StrictInt | None = None,
        **kwargs,
    ) -> ChannelReadingResult:
        """
        Capture waveform data from one or more scope channels.

        Acquires the channels and returns a ChannelReadingResult with correct
        per-channel Y scaling.

        This implementation queries a fresh waveform preamble **for every channel**
        so that Y-axis scaling (yinc/yorg/yref) is applied correctly even when the
        channels have different vertical settings.

        Args:
            timeout_ms: Optional one-shot communication budget for this acquisition.
                Keep the backend default low for normal commands and pass a larger
                value only for expected long acquisitions or large waveform transfers.
            waveform_format: ``"byte"``, ``"word"``, or ``"auto"``. Auto prefers
                WORD when the selected instrument profile defines it.
            points: Optional device-side point-count request for controlled
                acquisition. The result records the effective count per channel.
        """
        if timeout_ms is not None:
            with self.temporary_communication_timeout(timeout_ms):
                return self.read_channels(
                    *channels,
                    run_after=run_after,
                    timebase=timebase,
                    timeout_ms=None,
                    waveform_format=waveform_format,
                    points=points,
                    **kwargs,
                )

        # ---------------------- argument normalisation (unchanged) ----------------------
        if "runAfter" in kwargs:
            run_after = bool(kwargs["runAfter"])
        self._validate_waveform_points(points, run_after=run_after)

        if not channels:
            raise InstrumentParameterError(message="No channels specified.")

        processed_channels: list[int] = []
        if len(channels) == 1 and isinstance(channels[0], list | tuple):
            for c in channels[0]:
                if not isinstance(c, int):
                    raise InstrumentParameterError(message="Channel numbers must be integers.")
                processed_channels.append(c)
        else:
            for item in channels:
                if isinstance(item, list | tuple):
                    for x in item:
                        if not isinstance(x, int):
                            raise InstrumentParameterError(
                                message="Channel numbers must be integers."
                            )
                        processed_channels.append(x)
                else:
                    if not isinstance(item, int):
                        raise InstrumentParameterError(message="Channel numbers must be integers.")
                    processed_channels.append(item)

        for ch in processed_channels:
            if not (1 <= ch <= len(self.config.channels)):
                raise InstrumentParameterError(
                    parameter="channels",
                    value=ch,
                    valid_range=(1, len(self.config.channels)),
                    message="Channel number is out of range.",
                )

        with self._preserve_channel_display(processed_channels) if run_after else nullcontext():
            if not run_after:
                if timebase is not None:
                    raise InstrumentParameterError(
                        parameter="timebase",
                        value=timebase,
                        message="Read-only acquisition cannot change the timebase.",
                    )
                if len(processed_channels) != 1:
                    raise InstrumentParameterError(
                        parameter="channels",
                        value=processed_channels,
                        message="Read-only acquisition can read only the currently selected channel.",
                    )
                selected_channel = self._read_current_waveform_source()
                if selected_channel != processed_channels[0]:
                    raise InstrumentParameterError(
                        parameter="channels",
                        value=processed_channels[0],
                        message=(
                            f"Read-only acquisition requested channel {processed_channels[0]}, "
                            f"but the instrument waveform source is channel {selected_channel}."
                        ),
                    )
                current_format = self._read_current_waveform_format()
                requested_format = waveform_format.strip().lower()
                if requested_format != "auto" and requested_format != current_format:
                    raise InstrumentParameterError(
                        parameter="waveform_format",
                        value=waveform_format,
                        valid_range=("auto", current_format),
                        message=(
                            f"Read-only acquisition cannot change the current {current_format} "
                            "waveform transfer format."
                        ),
                    )
                resolved_waveform_format = current_format
                resolved_byteorder = (
                    self._read_current_waveform_byteorder()
                    if resolved_waveform_format == "word"
                    else None
                )
            else:
                if timebase is not None:
                    cur_scale, cur_pos = self.get_time_axis()
                    self.set_time_axis(scale=timebase, position=cur_pos)
                if points is not None:
                    self._configure_acquisition_points(points)
                sources = [self._waveform_source_for_channel(ch) for ch in processed_channels]
                chan_list_str = self.config.waveform_source_separator.join(sources)
                for cmd in self._scpi_engine.build("digitize", sources=chan_list_str):
                    self._send_command(cmd)
                resolved_waveform_format = self._resolve_waveform_format(waveform_format)
                resolved_byteorder = (
                    self._read_current_waveform_byteorder()
                    if resolved_waveform_format == "word"
                    else None
                )

            sampling_rate = float(self.get_sampling_rate())

            time_array: np.ndarray | None = None
            columns: dict[str, np.ndarray] = {}
            waveform_uncertainty: dict[str, dict[str, Any]] = {}
            points_mode_aliases: list[str] = []
            effective_points: dict[str, int] = {}

            for _idx, ch in enumerate(processed_channels, start=1):
                source = self._waveform_source_for_channel(ch)
                # Transfer settings affect the preamble scaling. Configure them
                # before querying the channel-specific preamble.
                if run_after:
                    if points is None:
                        points_mode_alias = self._configure_waveform_transfer(
                            source, resolved_waveform_format
                        )
                    else:
                        points_mode_alias = self._configure_waveform_transfer(
                            source, resolved_waveform_format, points=points
                        )
                    if points_mode_alias is not None:
                        points_mode_aliases.append(points_mode_alias)
                pre = self._read_preamble()

                raw = self._read_wave_data(
                    source,
                    preamble=pre,
                    waveform_format=resolved_waveform_format,
                    byteorder=resolved_byteorder,
                )
                effective_points[str(ch)] = len(raw)
                if points is not None and len(raw) != points:
                    self._logger.warning(
                        "Requested %s waveform points on channel %s; instrument returned %s.",
                        points,
                        ch,
                        len(raw),
                    )

                # Convert Y-axis using **this channel's** preamble
                volts = (raw - pre.yref) * pre.yinc + pre.yorg
                columns[f"Channel {ch} (V)"] = volts
                channel_range = self.config.channels[ch - 1].channel_range
                range_value = getattr(channel_range, "max", None)
                if range_value is None:
                    range_value = getattr(channel_range, "max_val", None)
                context = oscilloscope_measurement_context(
                    self.config,
                    channel=ch,
                    reading=float(np.mean(volts)) if len(volts) else 0.0,
                    unit="V",
                    function="read_channels",
                    instrument_key=self._uncertainty_source_key(),
                )
                spec = None
                if self.config.measurement_accuracy:
                    spec = self.config.measurement_accuracy.get(f"waveform_ch{ch}")
                    if spec is None:
                        spec = self.config.measurement_accuracy.get(f"vpp_ch{ch}")
                waveform_uncertainty[str(ch)] = {
                    "unit": "V",
                    "range_value": range_value,
                    "resolution": getattr(channel_range, "resolution", None),
                    "bandwidth": self.config.bandwidth,
                    "sample_count": len(volts),
                    "sampling_rate": sampling_rate,
                    "source_key": context.source_key,
                    "data_origin": "measured",
                    "evidence_purpose": "measurement_result",
                    "origin_detail": f"oscilloscope read_channels {self.config.model} channel {ch}",
                    "traceability": context.traceability,
                    "accuracy_spec": spec,
                    "preamble": {
                        "xinc": pre.xinc,
                        "xorg": pre.xorg,
                        "xref": pre.xref,
                        "yinc": pre.yinc,
                        "yorg": pre.yorg,
                        "yref": pre.yref,
                    },
                }

                # Only need to compute the common time axis once
                if time_array is None:
                    n_pts = len(volts)
                    operation = self.config.operation_options.operation("waveform_readout")
                    transport = operation.transport if operation is not None else {}
                    peak_mode = transport.get("points_mode_for_peak")
                    peak_pairs = (
                        peak_mode is not None
                        and (
                            not run_after
                            or (bool(points_mode_aliases) and points_mode_aliases[-1] == peak_mode)
                        )
                        and self.acquisition.get_acquisition_type().lower() == "peak"
                    )
                    if peak_pairs:
                        pair_indices = np.arange(n_pts) // 2
                        time_array = (pair_indices - pre.xref) * pre.xinc * 2 + pre.xorg
                    else:
                        time_array = (np.arange(n_pts) - pre.xref) * pre.xinc + pre.xorg

            if time_array is None:
                raise InstrumentDataError(self.config.model, "Time axis generation failed.")

            operation = self.config.operation_options.operation("waveform_readout")
            transport = operation.transport if operation is not None else {}
            points_commands = (
                [transport["points_max"]]
                if points is None and run_after and "points_max" in transport
                else [
                    transport[key]
                    for key in ("acquisition_points", "points")
                    if key in transport and run_after
                ]
            )
            return ChannelReadingResult(
                instrument=self.config.model,
                units="V",
                measurement_type="ChannelVoltageTime",
                sampling_rate=sampling_rate,
                values=pl.DataFrame({"Time (s)": time_array, **columns}),
                envelope={
                    "waveform_uncertainty": waveform_uncertainty,
                    "waveform_transfer": {
                        "points_mode_aliases": list(dict.fromkeys(points_mode_aliases)),
                        "requested_points": points,
                        "effective_points": effective_points,
                        "points_commands": points_commands,
                    },
                },
            )

    @validate_call
    def acquire_waveform(
        self,
        channel: int,
        *,
        mode: str = "controlled",
        format: str = "byte",
        points: StrictInt | None = None,
        uncertainty: bool = True,
        restore_state: bool = False,
        timeout_ms: int | None = None,
    ) -> WaveformResult:
        """Capture a waveform trace from one scope channel.

        Acquires the channel and returns it as a first-class
        :class:`WaveformResult`.

        ``mode="read_only"`` preserves the non-invasive verification posture at
        the API boundary. ``mode="controlled"`` uses the waveform setup aliases
        in the instrument profile and records that intent in the acquisition
        trace. ``format="auto"`` prefers WORD when the profile supports it.
        Full arbitrary state restoration is deliberately not guessed; the trace
        records whether restoration was requested and whether PyTestLab had enough
        state to restore.
        """

        normalized_mode = mode.lower().replace("-", "_")
        if normalized_mode not in {"read_only", "controlled"}:
            raise InstrumentParameterError(
                parameter="mode",
                value=mode,
                valid_range=("read_only", "controlled"),
                message="mode must be 'read_only' or 'controlled'.",
            )
        if format not in {"auto", "byte", "word"}:
            raise InstrumentParameterError(
                parameter="format",
                value=format,
                valid_range=("auto", "byte", "word"),
                message="Oscilloscope.acquire_waveform supports 'auto', 'byte', or 'word'.",
            )
        if points is not None:
            self._validate_waveform_points(points, run_after=normalized_mode == "controlled")

        state_before = None
        if normalized_mode == "controlled":
            try:
                scale, position = self.get_time_axis()
                state_before = ScopeStateSnapshot(
                    mode="partial",
                    values={"timebase_scale": float(scale), "timebase_position": float(position)},
                )
            except (
                InstrumentCommunicationError,
                InstrumentConfigurationError,
                InstrumentDataError,
                KeyError,
                ValueError,
            ) as exc:  # pragma: no cover - hardware/profile dependent
                self._logger.debug(
                    "Could not snapshot oscilloscope state before acquisition: %s", exc
                )

        resolved_format = (
            self._resolve_waveform_format(format)
            if hasattr(self, "_resolve_waveform_format")
            else format
        )
        point_options = {"points": points} if points is not None else {}
        if format == "byte":
            result = self.read_channels(
                channel,
                timeout_ms=timeout_ms,
                run_after=normalized_mode == "controlled",
                **point_options,
            )
        else:
            result = self.read_channels(
                channel,
                timeout_ms=timeout_ms,
                waveform_format=format,
                run_after=normalized_mode == "controlled",
                **point_options,
            )
        wave = result.waveform(channel)
        notes = [
            "read_channels acquisition path used",
            f"requested_format={format}",
            "raw waveform transfer payload is not retained by WaveformResult",
        ]
        restored: bool | None = None
        if restore_state:
            if state_before is not None:
                try:
                    self.set_time_axis(
                        scale=float(state_before.values["timebase_scale"]),
                        position=float(state_before.values["timebase_position"]),
                    )
                    restored = True
                except (
                    InstrumentCommunicationError,
                    InstrumentConfigurationError,
                    InstrumentDataError,
                    KeyError,
                    ValueError,
                ) as exc:  # pragma: no cover - hardware/profile dependent
                    restored = False
                    notes.append(f"state restore failed: {exc}")
            else:
                restored = False
                notes.append(
                    "state restore requested but no restorable state snapshot was available"
                )
        profile_commands = (
            set(self._scpi_engine.list_names()) if hasattr(self, "_scpi_engine") else set()
        )
        controlled_commands = [
            "set_wave_source",
            f"set_wave_format_{resolved_format}",
        ]
        transfer = (getattr(result, "envelope", {}) or {}).get("waveform_transfer", {})
        if "points_commands" in transfer:
            controlled_commands.extend(transfer["points_commands"])
        elif points is None:
            controlled_commands.append("set_wave_points_max")
        if points is not None:
            notes.extend(
                [
                    f"requested_points={points}",
                    f"effective_points={transfer.get('effective_points', {})}",
                ]
            )
        if resolved_format == "word":
            controlled_commands.append("set_wave_byteorder_lsb")
        points_mode_aliases = (
            (getattr(result, "envelope", {}) or {})
            .get("waveform_transfer", {})
            .get("points_mode_aliases", [])
        )
        if points_mode_aliases:
            controlled_commands.extend(points_mode_aliases)
        else:
            controlled_commands.append(
                "set_wave_points_mode_normal"
                if resolved_format == "word" and "set_wave_points_mode_normal" in profile_commands
                else "set_wave_points_mode_raw"
            )
        controlled_commands.append("wave_data")
        trace = AcquisitionTrace(
            mode=normalized_mode,
            commands=(
                tuple(controlled_commands) if normalized_mode == "controlled" else ("wave_data",)
            ),
            state_before=state_before,
            restored=restored,
            notes=tuple(notes if uncertainty else [*notes, "uncertainty model not requested"]),
        )
        if uncertainty:
            model = wave.model
            metadata = wave.metadata
        else:
            model = WaveformUncertaintyModel(
                unit=wave.unit,
                channel=wave.channel,
                data_origin=wave.model.data_origin,
                evidence_purpose=wave.model.evidence_purpose,
                origin_detail=wave.model.origin_detail,
                provenance_complete=False,
                assumptions=("uncertainty model disabled by caller",),
            )
            metadata = {}
        return WaveformResult(
            wave.values,
            time=wave.time,
            unit=wave.unit,
            channel=wave.channel,
            instrument=wave.instrument,
            model=model,
            acquisition=trace,
            metadata=metadata,
        )

    @validate_call
    def acquire_waveforms(
        self,
        channels: list[int] | tuple[int, ...],
        *,
        run_after: bool = True,
        timebase: float | None = None,
        timeout_ms: int | None = None,
    ) -> WaveformSetResult:
        """Acquire multiple channels as one shared-clock waveform set."""

        if not channels:
            raise InstrumentParameterError(message="No channels specified.")
        result = self.read_channels(
            *list(channels),
            run_after=run_after,
            timebase=timebase,
            timeout_ms=timeout_ms,
        )
        waves = {channel: result.waveform(channel) for channel in result.channels}
        trace = AcquisitionTrace(
            mode="controlled" if run_after else "read_only",
            commands=(
                "digitize",
                "set_wave_source",
                "wave_preamble",
                "wave_data",
            ),
            notes=("multi-channel read_channels acquisition path used",),
        )
        first = next(iter(waves.values()))
        return WaveformSetResult(
            waves,
            acquisition=trace,
            clock_model=SharedClockModel(
                source_key=_shared_clock_source_key(self.config.model, waves),
                timebase_relative_std=first.model.axis.timebase_relative_std,
                trigger_jitter_std_s=first.model.axis.trigger_jitter_std_s,
                sample_aperture_s=first.model.axis.sample_aperture_s,
                interpolation_model=first.model.axis.interpolation_model,
                channel_skew_std_s=first.model.axis.channel_skew_std_s,
            ),
        )

    def plot_channels(
        self,
        *channels: int | list[int] | tuple[int, ...],
        points: int | None = None,
        run_after: bool = True,
        timebase: float | None = None,
        spec: PlotSpec | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Convenience: acquire one or more channels and plot the result.

        Args:
            channels: Channel numbers to read (e.g., 1 or (1,2)).
            points: Optional point count (instrument-specific behavior).
            run_after: Whether to run a fresh acquisition prior to readback.
            timebase: Optional time-base scale in seconds.
            spec: Optional PlotSpec. If omitted, constructed from kwargs.
            **kwargs: PlotSpec fields (kind, x, y, title, xlabel, ylabel, legend, grid).

        Returns:
            A matplotlib Figure.
        """
        from ..plotting import PlotSpec  # local import keeps plotting optional

        result = self.read_channels(
            *channels, points=points, run_after=run_after, timebase=timebase
        )
        plot_spec = spec or (PlotSpec(**kwargs) if kwargs else PlotSpec())
        return result.plot(plot_spec)

    @validate_call
    def analyze_segments(self) -> None:
        """Analyze all captured segmented-acquisition records."""
        self.acquisition.analyze_all_segments()

    @validate_call
    def get_sampling_rate(self) -> float:
        """
        Get the current sampling rate of the oscilloscope.
        Returns:
            float: The sampling rate in Hz.
        """
        v = self._scpi_engine.parse(
            "acquire_sample_rate", self._query(self._scpi_engine.build("acquire_sample_rate")[0])
        )
        return np.float64(v)

    @validate_call
    def get_probe_attenuation(self, channel: int) -> str:  # Returns string like "10:1"
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
        response_str = self._query(self._scpi_engine.build("probe_get", channel=channel)[0]).strip()
        try:
            # Firmware may append a documented status token after the numeric
            # field; only the profile-declared numeric field is meaningful.
            num_factor = float(response_str.split(",", 1)[0].strip())
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model,
                f"Profile probe response is not numeric: {response_str!r}",
            ) from exc
        if not math.isfinite(num_factor) or num_factor <= 0:
            raise InstrumentDataError(
                self.config.model,
                f"Profile probe response is not a valid attenuation: {response_str!r}",
            )
        return f"{int(num_factor) if num_factor.is_integer() else num_factor}:1"

    @validate_call
    def set_probe_attenuation(self, channel: int, scale: float) -> None:
        """
        Sets the probe scale for a given channel.

        Parameters:
            channel (int): The oscilloscope channel to set the scale for.
            scale (float): The numeric probe attenuation ratio, including supported values below 1.
        """
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )

        if not math.isfinite(scale) or scale <= 0:
            raise InstrumentParameterError(
                parameter="scale",
                value=scale,
                message="Probe attenuation must be finite and positive.",
            )
        operation = self.config.operation_options.operation("channel_setup")
        if operation is not None and "probe_attenuation" in operation.parameters:
            resolved = self._resolve_operation_arguments(
                "channel_setup", {"channel": channel, "probe_attenuation": scale}
            )
            probe_alias = operation.transport["probe"]
            probe_arguments = {"channel": channel, **resolved[probe_alias]}
            self._send_profile_alias(probe_alias, **probe_arguments)
        else:
            channel_model_config = self.config.channels[channel - 1]
            if scale not in channel_model_config.probe_attenuation:
                raise InstrumentParameterError(
                    parameter="scale",
                    value=scale,
                    valid_range=channel_model_config.probe_attenuation,
                    message=f"Scale not in supported probe_attenuation list for channel {channel}.",
                )
            for cmd in self._scpi_engine.build("probe_set", channel=channel, scale=scale):
                self._send_command(cmd)
        self._logger.debug(f"Set probe scale to {scale}:1 for channel {channel}.")

    @validate_call
    def set_acquisition_time(self, time: float) -> None:
        """
        Set full-screen acquisition duration, ten horizontal divisions.

        Preserve an existing delay when compatible with the effective duration;
        otherwise leave delay at zero rather than issuing an invalid position.

        Args:
            time (float): The total acquisition time in seconds.
        """
        resolved = self._resolve_operation_arguments("acquisition_time", {"time": time})
        time_axis_operation = self.config.operation_options.operation("time_axis")
        mode = self._time_axis_mode(time_axis_operation)
        self._validate_time_position(time_axis_operation, time / 10, 0, mode)
        commands = [
            command
            for alias, arguments in resolved.items()
            for command in self._build_profile_alias(alias, **arguments)
        ]
        self._apply_time_axis(time_axis_operation, time / 10, None, mode, range_commands=commands)

    @validate_call
    def set_acquisition_type(self, acq_type: str) -> Self:
        """Set acquisition type using the profile's semantic choices.

        Values come from the loaded profile; use discovery to list supported choices.
        """
        semantic = str(getattr(acq_type, "name", acq_type)).lower()
        resolved = self._resolve_operation_parameter("set_acquisition_type", "acq_type", semantic)
        for cmd in self._scpi_engine.build("acq_set_type", value=resolved.transport_value):
            self._send_command(cmd)
        self._wait()
        return self

    @validate_call
    def set_acquisition_mode(self, mode: str) -> Self:
        """Set acquisition mode using the profile's semantic choices."""
        resolved = self._resolve_operation_parameter("set_acquisition_mode", "mode", mode)
        for cmd in self._scpi_engine.build("acq_set_mode", value=resolved.transport_value):
            self._send_command(cmd)
        self._wait()
        return self

    @validate_call
    def set_sample_rate(self, rate: str) -> None:
        """
        Sets the sample rate for the oscilloscope.

        Args:
        rate (str): The desired sample rate. Valid values are 'MAX' and 'AUTO'. Case-insensitive.
        """
        rate_upper: str = rate.upper()
        valid_values: list[str] = ["MAX", "AUTO"]
        if rate_upper not in valid_values:
            raise InstrumentParameterError(
                parameter="rate",
                value=rate,
                valid_range=valid_values,
                message="Invalid rate.",
            )
        for cmd in self._scpi_engine.build("acquire_set_rate", rate=rate_upper):
            self._send_command(cmd)

    def _bandwidth_commands(self, channel: int, bandwidth: str | float) -> list[str]:
        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )

        options = getattr(self.config, "operation_options", None)
        bandwidth_spec = (
            options.parameter("bandwidth_limit", "bandwidth")
            if options is not None and hasattr(options, "parameter")
            else None
        )
        if options is not None and bandwidth_spec is not None and bandwidth_spec.kind == "enum":
            resolved = self._resolve_operation_parameter("bandwidth_limit", "bandwidth", bandwidth)
            if str(resolved.value).casefold() == "full":
                operation = options.operation("bandwidth_limit")
                full_alias = operation.transport.get("full") if operation is not None else None
                if not full_alias:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Profile does not declare how to disable the channel bandwidth filter.",
                    )
                commands = self._scpi_engine.build(full_alias, channel=channel)
            else:
                if resolved.alias is None or resolved.transport_parameter is None:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Profile does not declare a transport for the selected bandwidth limit.",
                    )
                commands = self._scpi_engine.build(
                    resolved.alias,
                    channel=channel,
                    **{resolved.transport_parameter: resolved.transport_value},
                )
        else:
            # Profiles that predate semantic bandwidth metadata retain their
            # existing behavior until their supported command forms are declared.
            commands = self._scpi_engine.build(
                "channel_bandwidth", channel=channel, bandwidth=bandwidth
            )
        return commands

    @validate_call
    def set_bandwidth_limit(self, channel: int, bandwidth: str | float) -> None:
        """Apply a profile-supported bandwidth limit; FULL disables the filter."""
        commands = self._bandwidth_commands(channel, bandwidth)
        sensitivity = self._bandwidth_sensitivity_constraint("bandwidth_limit", "bandwidth")
        if sensitivity:
            choice = self._resolve_operation_parameter("bandwidth_limit", "bandwidth", bandwidth)
            if str(choice.value).casefold() == "full":
                context = self._channel_axis_context(
                    channel, self.config.operation_options.operation("channel_axis")
                )
                scale, _offset = self.get_channel_axis(channel)
                self._validate_bandwidth_sensitivity(
                    "bandwidth", bandwidth, scale, context, sensitivity
                )
        for cmd in commands:
            self._send_command(cmd)

    def _bandwidth_sensitivity_constraint(self, operation_id, parameter):
        options = getattr(self.config, "operation_options", None)
        specification = (
            options.parameter(operation_id, parameter)
            if options is not None and hasattr(options, "parameter")
            else None
        )
        return (
            specification.constraints.get("full_bandwidth_minimum_input_referred_scale")
            if specification is not None
            else None
        )

    def _validate_bandwidth_sensitivity(self, parameter, requested, scale, context, constraint):
        probe = float(context["probe_attenuation"])
        live_scale = float(scale)
        if (
            not math.isfinite(probe)
            or probe <= 0
            or not math.isfinite(live_scale)
            or live_scale <= 0
        ):
            raise InstrumentDataError(
                self.config.model,
                "Channel scale/probe readback is not a positive finite value; "
                "cannot validate full bandwidth safely.",
            )
        input_scale = live_scale / probe
        if not math.isfinite(input_scale) or input_scale <= 0:
            raise InstrumentDataError(
                self.config.model,
                "Channel scale/probe readback is not a positive finite value; "
                "cannot validate full bandwidth safely.",
            )
        if context["input_impedance"] != constraint["input_impedance"]:
            return
        if input_scale < float(constraint["value"]):
            raise InstrumentParameterError(
                parameter=parameter,
                value=requested,
                message=(
                    "Full bandwidth requires an input-referred scale of at least "
                    f"{constraint['value']:.3g} V/div at {constraint['input_impedance']} Ohm; "
                    f"the current context is {input_scale:.3g} V/div."
                ),
            )

    @validate_call
    # @ConfigRequires("function_generator")
    def wave_gen(self, state: bool) -> None:
        """
        Enable or disable the waveform generator of the oscilloscope.

        Args:
        state (bool): True to enable ('ON'), False to disable ('OFF').
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        resolved = self._resolve_operation_parameter("wave_generator_basic", "state", state)
        cmds = self._scpi_engine.build("wgen_output", state=resolved.transport_value)
        for cmd in cmds:
            self._send_command(cmd)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wave_gen_func(self, func_type: str) -> None:
        """
        Set the waveform function for the oscilloscope's waveform generator.

        Args:
        func_type: A semantic waveform value returned by profile discovery.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )

        semantic = str(getattr(func_type, "name", func_type)).lower()
        resolved = self._resolve_operation_parameter("set_wave_gen_func", "func_type", semantic)
        cmds = self._scpi_engine.build("wgen_set_func", func=resolved.transport_value)
        for cmd in cmds:
            self._send_command(cmd)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wave_gen_freq(self, freq: float) -> None:
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
        self.config.function_generator.frequency.assert_in_range(
            freq, name="Waveform generator frequency"
        )
        cmds = self._scpi_engine.build("wgen_set_freq", frequency=freq)
        for cmd in cmds:
            self._send_command(cmd)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wave_gen_amp(self, amp: float) -> None:
        """
        Set the amplitude for the waveform generator.

        Args:
        amp (float): The desired amplitude for the waveform generator in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.config.function_generator.amplitude.assert_in_range(
            amp, name="Waveform generator amplitude"
        )
        cmds = self._scpi_engine.build("wgen_set_volt", amplitude=amp)
        for cmd in cmds:
            self._send_command(cmd)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wave_gen_offset(self, offset: float) -> None:
        """
        Set the voltage offset for the waveform generator.

        Args:
        offset (float): The desired voltage offset for the waveform generator in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.config.function_generator.offset.assert_in_range(
            offset, name="Waveform generator offset"
        )
        cmds = self._scpi_engine.build("wgen_set_offset", offset=offset)
        for cmd in cmds:
            self._send_command(cmd)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wgen_sin(self, amp: float, offset: float, freq: float) -> None:
        """Sets the waveform generator to a sine wave.

        :param amp: The amplitude of the sine wave in volts
        :param offset: The offset of the sine wave in volts
        :param freq: The frequency of the sine wave in Hz.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.set_wave_gen_func("sine")
        self.set_wave_gen_amp(amp)
        self.set_wave_gen_offset(offset)
        self.set_wave_gen_freq(freq)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wgen_square(
        self, v0: float, v1: float, freq: float, duty_cycle: int | None = None, **kwargs
    ) -> None:
        """Sets the waveform generator to a square wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param freq: The frequency of the square wave in Hz.
        :param duty_cycle: The duty cycle (1% to 99%).
        """
        if "dutyCycle" in kwargs:
            duty_cycle = kwargs["dutyCycle"]

        if duty_cycle is None:
            duty_cycle = 50

        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )

        self.set_wave_gen_func("square")

        arguments = self._resolve_operation_arguments(
            "wave_generator_shapes",
            {"v0": v0, "v1": v1, "freq": freq, "duty_cycle": duty_cycle},
        )
        for alias, params in arguments.items():
            self._send_profile_alias(alias, **params)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wgen_ramp(self, v0: float, v1: float, freq: float, symmetry: int) -> None:
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
        self.set_wave_gen_func("ramp")

        def clamp_symmetry(number: int) -> int:
            return max(0, min(number, 100))

        for cmd in self._scpi_engine.build("wgen_set_low", value=v0):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build("wgen_set_high", value=v1):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build("wgen_set_freq", frequency=freq):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build(
            "wgen_set_ramp_symmetry", symmetry=clamp_symmetry(symmetry)
        ):
            self._send_command(cmd)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wgen_pulse(
        self, v0: float, v1: float, period: float, pulse_width: float | None = None, **kwargs
    ) -> None:
        """Sets the waveform generator to a pulse wave.

        :param v0: The voltage of the low state in volts
        :param v1: The voltage of the high state in volts
        :param period: The period of the pulse wave in seconds.
        :param pulse_width: The pulse width in seconds.
        """
        if "pulseWidth" in kwargs:
            pulse_width = kwargs["pulseWidth"]

        if pulse_width is None:
            raise InstrumentParameterError(message="pulse_width is required.")

        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.set_wave_gen_func("pulse")

        for cmd in self._scpi_engine.build("wgen_set_low", value=v0):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build("wgen_set_high", value=v1):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build("wgen_set_period", period=period):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build("wgen_set_pulse_width", width=pulse_width):
            self._send_command(cmd)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wgen_dc(self, offset: float) -> None:
        """Sets the waveform generator to a DC wave.

        :param offset: The offset of the DC wave in volts
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.set_wave_gen_func("dc")
        self.set_wave_gen_offset(offset)

    @validate_call
    # @ConfigRequires("function_generator")
    def set_wgen_noise(self, v0: float, v1: float, offset: float) -> None:
        """Sets the waveform generator to a noise wave.

        :param v0: The 'low' amplitude component or similar parameter for noise.
        :param v1: The 'high' amplitude component or similar parameter for noise.
        :param offset: The offset of the noise wave in volts.
        """
        if self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "Function generator not configured."
            )
        self.set_wave_gen_func("noise")
        for cmd in self._scpi_engine.build("wgen_set_low", value=v0):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build("wgen_set_high", value=v1):
            self._send_command(cmd)
        self.set_wave_gen_offset(offset)

    @validate_call
    def display_channel(self, channels: int | list[int], state: bool = True) -> None:
        """
        Display or hide the specified channel(s) on the oscilloscope.

        Args:
        channels (Union[int, List[int]]): A single channel number or a list of channel numbers.
        state (bool): True to display (ON), False to hide (OFF). Default is True.
        """
        ch_list: list[int]
        if isinstance(channels, int):
            ch_list = [channels]
        elif isinstance(channels, list) and all(isinstance(ch, int) for ch in channels):
            ch_list = channels
        else:
            # validate_call should catch this if type hints are precise enough
            raise InstrumentParameterError(message="channels must be an int or a list of ints")

        for ch_num in ch_list:
            if not (1 <= ch_num <= len(self.config.channels)):
                raise InstrumentParameterError(
                    parameter="channels",
                    value=ch_num,
                    valid_range=(1, len(self.config.channels)),
                    message="Channel number is out of range.",
                )
            arguments = self._resolve_operation_arguments(
                "display_channel", {"channels": ch_num, "state": state}
            )
            for alias, params in arguments.items():
                self._send_profile_alias(alias, **params)

    @validate_call
    # @ConfigRequires("fft")
    def fft_display(self, state: bool = True) -> None:
        """
        Switches on or off the FFT display.

        :param state: True to enable FFT display, False to disable.
        """
        if self.config.fft is None:
            raise InstrumentConfigurationError(
                self.config.model, "FFT not configured for this instrument."
            )
        arguments = self._resolve_operation_arguments("fft_display", {"state": state})
        for alias, params in arguments.items():
            self._send_profile_alias(alias, **params)
        self._logger.debug(f"FFT display {'enabled' if state else 'disabled'}.")

    @validate_call
    # @ConfigRequires("function_generator")
    def function_display(self, state: bool = True) -> None:
        """
        Switches on or off the function display (e.g. Math or WGEN waveform).

        :param state: True to enable display, False to disable.
        """
        arguments = self._resolve_operation_arguments("function_display", {"state": state})
        for alias, params in arguments.items():
            self._send_profile_alias(alias, **params)
        self._logger.debug(f"Function display {'enabled' if state else 'disabled'}.")

    @validate_call
    # @ConfigRequires("fft")
    def configure_fft(
        self,
        source_channel: int,
        scale: float | None = None,
        offset: float | None = None,
        span: float | None = None,
        window_type: str = "hanning",
        units: str = "decibel",
        display: bool = True,
    ) -> None:
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

        arguments = self._resolve_operation_arguments(
            "fft",
            {
                "source_channel": source_channel,
                "scale": scale,
                "offset": offset,
                "span": span,
                "window_type": window_type,
                "units": units,
                "display": display,
            },
        )
        for alias, params in arguments.items():
            self._send_profile_alias(alias, **params)

        self._logger.debug(f"FFT configured for channel {source_channel}.")

    def _convert_binary_block_to_data(
        self, binary_block: bytes
    ) -> np.ndarray:  # Synchronous method for converting binary data
        """
        Converts a SCPI binary block to a NumPy array.
        Assumes format like #<N><LengthBytes><DataBytes>
        This method's original implementation was problematic.
        This is a more standard interpretation of SCPI binary blocks.
        The actual data type (e.g., int8, int16) depends on :WAVeform:FORMat.
        """
        try:
            return definite_length_block_to_array(binary_block, dtype=np.int8)
        except BinaryBlockParseError as exc:
            raise InstrumentDataError(
                self.config.model, f"Invalid binary block format: {exc}"
            ) from exc

    @validate_call
    def read_fft_data(
        self, channel: int, window: str | None = "hann", timeout_ms: int | None = None
    ) -> FFTResult:
        """
        Acquires time-domain data for the specified channel and computes the FFT using
        the analysis submodule.

        Args:
            channel (int): The channel number to perform FFT on.
            window (Optional[str]): The windowing function to apply before FFT
                                     (e.g., 'hann', 'hamming', None).
            timeout_ms: Optional one-shot communication budget for the underlying
                waveform acquisition. Use for long on-device/readback workflows.

        Returns:
            FFTResult: An object containing the computed FFT data (frequency and linear magnitude).
        """
        self._logger.debug(
            f"Initiating FFT computation for channel {channel} using analysis module."
        )

        if not (1 <= channel <= len(self.config.channels)):
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=(1, len(self.config.channels)),
                message="Channel number is out of range.",
            )

        # 1. Acquire raw time-domain waveform data
        waveform_data: ChannelReadingResult = self.read_channels(channel, timeout_ms=timeout_ms)

        if not isinstance(waveform_data.values, pl.DataFrame) or waveform_data.values.is_empty():
            self._logger.warning(
                f"No waveform data acquired for channel {channel}. Cannot compute FFT."
            )
            # Return an empty FFTResult or raise an error
            return FFTResult(
                instrument=self.config.model,
                units="Linear",
                measurement_type="FFT_computed_python",
                values=pl.DataFrame(
                    {"Frequency (Hz)": np.array([]), "Magnitude (Linear)": np.array([])}
                ),
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
            time_array=time_array, voltage_array=voltage_array, window=window
        )

        # 3. Return or further process the results
        return FFTResult(
            instrument=self.config.model,
            units="Linear",  # compute_fft returns linear magnitude
            measurement_type="FFT_computed_python",
            values=pl.DataFrame(
                {"Frequency (Hz)": frequency_array, "Magnitude (Linear)": magnitude_array}
            ),
        )

    @validate_call
    def screenshot(self, timeout_ms: int | None = None) -> Image.Image:
        """
        Capture a screenshot of the oscilloscope display.

        Args:
            timeout_ms: Optional one-shot communication budget for this screenshot
                transfer. Defaults to the backend's normal communication timeout.

        :return Image: A PIL Image object containing the screenshot.
        """
        with self.temporary_communication_timeout(timeout_ms):
            binary_data_response: bytes = self._query_raw(self._scpi_engine.build("screenshot")[0])

        try:
            image_data_bytes = strip_definite_length_block(binary_data_response)
        except BinaryBlockParseError as exc:
            raise InstrumentDataError(
                self.config.model, f"Invalid screenshot data format: {exc}"
            ) from exc

        return Image.open(BytesIO(image_data_bytes))

    @validate_call
    # @ConfigRequires("franalysis")
    # @ConfigRequires("function_generator")
    def franalysis_sweep(
        self,
        input_channel: int,
        output_channel: int,
        start_freq: float,
        stop_freq: float,
        amplitude: float,
        points: int = 10,
        trace: str = "none",
        load: str = "onemeg",
        disable_on_complete: bool = True,
    ) -> FRanalysisResult:
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

        # SCPI commands for frequency response analysis sweep via SCPIEngine only
        if self.config.franalysis is None or self.config.function_generator is None:
            raise InstrumentConfigurationError(
                self.config.model, "FRAnalysis or function generator not configured."
            )

        operation = self.config.operation_options.operation("frequency_response_analysis")
        if operation is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not declare frequency-response analysis."
            )
        transport = operation.transport
        fetch_alias = transport.get("fetch")
        if fetch_alias is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not declare frequency-response readback."
            )
        response_spec = self._scpi_engine.describe(fetch_alias).get("response") or {}
        response_type = response_spec.get("type", "raw")

        def send_step(logical_name: str) -> bool:
            """Send a fixed profile-owned workflow step when declared."""
            alias = transport.get(logical_name)
            if alias is None:
                return False
            self._send_profile_alias(alias)
            return True

        disable_sent = False
        try:
            send_step("select")
            enabled = send_step("enable")
            send_step("mode")
            resolved = self._resolve_operation_arguments(
                "frequency_response_analysis",
                {
                    "input_channel": input_channel,
                    "output_channel": output_channel,
                    "start_freq": start_freq,
                    "stop_freq": stop_freq,
                    "amplitude": amplitude,
                    "points": points,
                    "trace": trace,
                    "load": load,
                },
            )
            for alias, params in resolved.items():
                self._send_profile_alias(alias, **params)
            ran = send_step("run")
            if not ran and not enabled:
                raise InstrumentConfigurationError(
                    self.config.model,
                    "FRA profile must provide either 'fran_enable' or 'fran_run'.",
                )
            if not ran and disable_on_complete:
                disable_sent = True
                send_step("disable")
            self._wait()
            fetch_command = self._scpi_engine.build(fetch_alias)[0]
            if response_type == "binblock":
                try:
                    payload = strip_definite_length_block(self._query_raw(fetch_command))
                    result_data = payload.decode("ascii")
                except (BinaryBlockParseError, UnicodeDecodeError) as exc:
                    raise InstrumentDataError(
                        self.config.model, f"Invalid FRA binary response: {exc}"
                    ) from exc
            else:
                result_data = self._query(fetch_command)
        finally:
            if disable_on_complete and not disable_sent:
                send_step("disable")

        response_fields = list(response_spec.get("fields") or [])
        tokens = [
            token.strip()
            for row in result_data.replace("\r", "\n").splitlines()
            for token in row.split(",")
            if token.strip()
        ]
        parsed_results = [float(token) for token in tokens]
        if response_fields:
            width = len(response_fields)
            if len(parsed_results) % width:
                raise InstrumentDataError(
                    self.config.model,
                    f"FRA response has {len(parsed_results)} values, not a multiple of {width} fields.",
                )
            rows = [
                parsed_results[index : index + width]
                for index in range(0, len(parsed_results), width)
            ]
            column_names = {
                "frequency_hz": "Frequency (Hz)",
                "amplitude_vpp": "Amplitude (Vpp)",
                "gain_db": "Gain (dB)",
                "phase_deg": "Phase (deg)",
            }
            return FRanalysisResult(
                instrument=self.config.model,
                units="",
                measurement_type="FrequencyResponse",
                values=pl.DataFrame(
                    rows,
                    schema=[column_names.get(field) or field for field in response_fields],
                    orient="row",
                ),
            )

        if len(parsed_results) % 2:
            raise InstrumentDataError(
                self.config.model,
                f"FRA response has an odd number of legacy two-column values: {len(parsed_results)}.",
            )
        freq_values = parsed_results[0::2]
        mag_values = parsed_results[1::2]

        return FRanalysisResult(
            instrument=self.config.model,
            units="",
            measurement_type="FrequencyResponse",
            values=pl.DataFrame({"Frequency (Hz)": freq_values, "Magnitude": mag_values}),
        )


def _shared_clock_source_key(model: str, waves: dict[int, WaveformResult]) -> str:
    payload = {
        str(channel): hashlib.sha256(wave.values.tobytes()).hexdigest()
        for channel, wave in sorted(waves.items())
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{model}:shared_clock:{digest}"
