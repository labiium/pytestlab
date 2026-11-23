from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from math import ceil
from math import isfinite
from re import fullmatch
from time import monotonic
from time import time
from typing import Literal
from typing import cast

import polars as pl

from ..config.operation_options import OperationTransportSpec
from ..config.spectrum_analyzer_config import SpectrumAnalyzerConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ..experiments.results import MeasurementResult
from ..experiments.results import NativeMeasurementResult
from ._spectrum_uncertainty import SpectrumBoundDistribution
from ._spectrum_uncertainty import SpectrumMarkerConditions
from ._spectrum_uncertainty import marker_amplitude_uncertainty as _marker_amplitude_uncertainty
from .instrument import Instrument
from .operation_contract import OperationDescriptor
from .operation_contract import OperationPythonArgument

SpectrumDetector = Literal[
    "auto_peak", "positive_peak", "negative_peak", "sample", "rms", "average"
]
SpectrumTriggerSource = Literal[
    "free_run",
    "external_1",
    "external_2",
    "external_3",
    "video",
    "rf_burst",
    "rf_power",
    "if_power",
]
SpectrumExternalTriggerSource = Literal["external_1", "external_2", "external_3"]
SpectrumTriggerSlope = Literal["rising", "falling"]
SpectrumTraceMode = Literal["clear_write", "average", "max_hold", "min_hold", "view", "blank"]
_ACCUMULATING_MODES = ("average", "max_hold", "min_hold")

# Both programmers' references assign these bits to calibration, sweep, measurement and trigger wait.
_SWEEP_BUSY_FLAGS = (1 << 0) | (1 << 3) | (1 << 4) | (1 << 5)

_AMPLITUDE_UNITS = {
    "DBM": "dBm",
    "DBMV": "dBmV",
    "DBMA": "dBmA",
    "DBUVM": "dBµV/m",
    "DBUAM": "dBµA/m",
    "DBG": "dBG",
    "DBUV": "dBµV",
    "DBUA": "dBµA",
    "DBPW": "dBpW",
    "DBPT": "dBpT",
    "WATT": "W",
    "VOLT": "V",
    "AMP": "A",
    "AMPERE": "A",
    "W": "W",
    "V": "V",
    "A": "A",
}


@dataclass(frozen=True)
class SpectrumSweepSettings:
    """Current front-panel sweep settings, not a cached copy of requested values."""

    center_freq_hz: float
    span_hz: float
    rbw_hz: float
    vbw_hz: float
    sweep_points: int
    amplitude_unit: str


@dataclass(frozen=True)
class SpectrumSweepReadiness:
    """Verified single-sweep preparation; no measurement has been initiated."""

    channel: int
    span_hz: float
    sweep_points: int
    amplitude_unit: str
    axis_unit: Literal["Hz", "s"]
    continuous: Literal[False]
    transfer_format: Literal["ascii"]
    trace_mode: Literal["clear_write"]
    display_evidence: Literal["normal_selected", "diagram_verified"]


@dataclass(frozen=True)
class SpectrumRFInputSettings:
    """Current RF input settings in dB and the display reference level in dBm."""

    reference_level_dbm: float
    attenuation_db: float
    attenuation_auto: bool
    preamp: bool | None  # None when the supported option is not installed.


@dataclass(frozen=True)
class SpectrumSweepControl:
    """Current sweep duration, coupling and trigger source."""

    sweep_time_s: float
    sweep_time_auto: bool | None  # None when auto timing is not applicable.
    trigger_source: SpectrumTriggerSource
    continuous: bool


@dataclass(frozen=True)
class SpectrumExternalTriggerSettings:
    """Voltage and edge for an external trigger input."""

    source: SpectrumExternalTriggerSource
    level_v: float
    slope: SpectrumTriggerSlope | None
    active: bool


@dataclass(frozen=True)
class SpectrumTraceSettings:
    """Current state of a display trace and the analyzer-wide accumulation count."""

    channel: int
    mode: SpectrumTraceMode
    detector: SpectrumDetector
    detector_auto: bool
    accumulation_count: int
    updating: bool


@dataclass(frozen=True, kw_only=True)
class _SpectrumMeasurement:
    """Host readout context; the profile model is not a live identity query."""

    instrument: str | None = field(default=None, compare=False, repr=False)
    readout_timestamp: float | None = field(default=None, compare=False, repr=False)

    def _measurement_result(
        self,
        values: pl.DataFrame | float,
        unit: str,
        measurement_type: str,
        *,
        acquisition: Literal["fresh", "held", "derived"],
        native_uncertainty: bool = False,
        **details: object,
    ) -> MeasurementResult:
        captured = self.readout_timestamp is not None
        identity_source = "profile_model" if captured else "caller_supplied"
        result_type = NativeMeasurementResult if native_uncertainty else MeasurementResult
        return result_type(
            values=values,
            instrument=self.instrument or "unknown",
            units=unit,
            measurement_type=measurement_type,
            timestamp=self.readout_timestamp,
            envelope={
                "acquisition": acquisition if captured else "unknown",
                "capture_origin": "driver" if captured else "caller",
                "timestamp_kind": "host_receipt" if captured else "conversion_time",
                "instrument_identity_source": identity_source if self.instrument else "unknown",
                "uncertainty_status": "not_evaluated",
                **details,
            },
        )


@dataclass(frozen=True)
class SpectrumChannelPower(_SpectrumMeasurement):
    """Fresh native integrated power and the actual integration bandwidth."""

    power_dbm: float
    bandwidth_hz: float

    def to_measurement_result(self) -> MeasurementResult:
        """Return integrated power, with actual integration bandwidth in the envelope."""
        return self._measurement_result(
            self.power_dbm,
            "dBm",
            "spectrum_channel_power",
            acquisition="fresh",
            bandwidth_hz=self.bandwidth_hz,
        )


@dataclass(frozen=True)
class SpectrumOccupiedBandwidth(_SpectrumMeasurement):
    """Fresh native occupied bandwidth and the actual power percentage."""

    bandwidth_hz: float
    power_percent: float

    def to_measurement_result(self) -> MeasurementResult:
        """Return occupied bandwidth, with the actual power percentage in the envelope."""
        return self._measurement_result(
            self.bandwidth_hz,
            "Hz",
            "spectrum_occupied_bandwidth",
            acquisition="fresh",
            power_percent=self.power_percent,
        )


@dataclass(frozen=True)
class SpectrumAdjacentChannelPower(_SpectrumMeasurement):
    """Fresh native power for one carrier and one symmetric adjacent pair."""

    carrier_power_dbm: float
    lower_power_dbm: float
    upper_power_dbm: float
    lower_relative_dbc: float
    upper_relative_dbc: float
    carrier_bandwidth_hz: float
    adjacent_bandwidth_hz: float
    spacing_hz: float

    def to_measurement_result(self) -> MeasurementResult:
        """Return distinct carrier/lower/upper bands with signed relative offsets."""
        pair = SpectrumAdjacentChannelPair(
            1,
            self.spacing_hz,
            self.adjacent_bandwidth_hz,
            self.lower_power_dbm,
            self.upper_power_dbm,
            self.lower_relative_dbc,
            self.upper_relative_dbc,
        )
        return self._measurement_result(
            _acp_table((pair,), carrier=(self.carrier_power_dbm, self.carrier_bandwidth_hz)),
            "dBm",
            "spectrum_adjacent_channel_power",
            acquisition="fresh",
            column_units=_ACP_COLUMN_UNITS.copy(),
            adjacent_power_source=(
                "derived_from_carrier_and_relative_power"
                if self.readout_timestamp is not None
                else "caller_supplied"
            ),
        )


@dataclass(frozen=True)
class SpectrumAdjacentChannelPair:
    """Power in one symmetric pair of offsets; pair 1 is nearest the carrier."""

    pair: int
    spacing_hz: float
    bandwidth_hz: float
    lower_power_dbm: float
    upper_power_dbm: float
    lower_relative_dbc: float
    upper_relative_dbc: float


_ACP_COLUMN_UNITS = {
    "offset_hz": "Hz",
    "bandwidth_hz": "Hz",
    "power_dbm": "dBm",
    "relative_power_dbc": "dBc",
}


def _acp_table(
    pairs: tuple[SpectrumAdjacentChannelPair, ...], *, carrier: tuple[float, float]
) -> pl.DataFrame:
    power, bandwidth = carrier
    rows: list[tuple[str, int | None, float, float, float, float | None]] = [
        ("carrier", None, 0.0, bandwidth, power, None)
    ]
    rows.extend(
        (band, pair.pair, offset, pair.bandwidth_hz, absolute, relative)
        for pair in pairs
        for band, offset, absolute, relative in (
            ("lower", -pair.spacing_hz, pair.lower_power_dbm, pair.lower_relative_dbc),
            ("upper", pair.spacing_hz, pair.upper_power_dbm, pair.upper_relative_dbc),
        )
    )
    return pl.DataFrame(
        rows,
        schema={
            "band": pl.String,
            "pair": pl.Int64,
            "offset_hz": pl.Float64,
            "bandwidth_hz": pl.Float64,
            "power_dbm": pl.Float64,
            "relative_power_dbc": pl.Float64,
        },
        orient="row",
    )


@dataclass(frozen=True)
class SpectrumAdjacentChannelPowerSeries(_SpectrumMeasurement):
    """One carrier and its measured adjacent/alternate bands, nearest first."""

    carrier_power_dbm: float
    carrier_bandwidth_hz: float
    pairs: tuple[SpectrumAdjacentChannelPair, ...]

    def to_measurement_result(self) -> MeasurementResult:
        """Return all bands by pair in nearest-first order, without inventing a center frequency."""
        return self._measurement_result(
            _acp_table(self.pairs, carrier=(self.carrier_power_dbm, self.carrier_bandwidth_hz)),
            "dBm",
            "spectrum_adjacent_channel_power_series",
            acquisition="fresh",
            column_units=_ACP_COLUMN_UNITS.copy(),
            adjacent_power_source=(
                (
                    "derived_from_carrier_and_relative_power"
                    if len(self.pairs) == 1
                    else "instrument"
                )
                if self.readout_timestamp is not None
                else "caller_supplied"
            ),
        )


@dataclass(frozen=True)
class SpectrumMarker(_SpectrumMeasurement):
    """A normal instrument marker on a held, non-zero-span, dBm trace."""

    marker: int
    channel: int
    frequency_hz: float
    amplitude_dbm: float

    def to_measurement_result(
        self,
        *,
        uncertainty: bool = False,
        conditions: SpectrumMarkerConditions | None = None,
        bound_distribution: SpectrumBoundDistribution | None = None,
    ) -> MeasurementResult:
        """Return the marker table with an optional manufacturer amplitude component.

        This conversion performs no I/O. Conditions must describe the acquisition
        behind the held marker, not the instrument's later state. Keysight's hard
        limit requires an explicitly selected distribution to produce standard
        uncertainty. FSW26 uses the published coverage factor. No frequency
        uncertainty or correlation is inferred.
        """
        if type(uncertainty) is not bool:
            raise ValueError("uncertainty must be a bool")
        if bound_distribution not in (None, "rectangular", "triangular"):
            raise ValueError("bound_distribution must be rectangular or triangular")
        if not uncertainty and (conditions is not None or bound_distribution is not None):
            raise ValueError("Pass uncertainty=True to evaluate the capture conditions")
        evidence = (
            _marker_amplitude_uncertainty(
                model=self.instrument,
                frequency_hz=self.frequency_hz,
                amplitude_dbm=self.amplitude_dbm,
                driver_readout=self.readout_timestamp is not None,
                conditions=conditions,
                bound_distribution=bound_distribution,
            )
            if uncertainty
            else {}
        )
        return self._measurement_result(
            pl.DataFrame(
                {"frequency_hz": [self.frequency_hz], "amplitude_dbm": [self.amplitude_dbm]},
                schema={"frequency_hz": pl.Float64, "amplitude_dbm": pl.Float64},
            ),
            "dBm",
            "spectrum_marker",
            acquisition="held",
            marker=self.marker,
            trace=self.channel,
            column_units={"frequency_hz": "Hz", "amplitude_dbm": "dBm"},
            native_uncertainty=uncertainty,
            **evidence,
        )


@dataclass(frozen=True)
class SpectrumMarkerDelta(_SpectrumMeasurement):
    """Comparison of two read-back markers on the same held trace."""

    reference: SpectrumMarker
    target: SpectrumMarker

    @property
    def frequency_delta_hz(self) -> float:
        return self.target.frequency_hz - self.reference.frequency_hz

    @property
    def amplitude_delta_db(self) -> float:
        return self.target.amplitude_dbm - self.reference.amplitude_dbm

    def to_measurement_result(self) -> MeasurementResult:
        """Return the two marker readouts and their target-minus-reference differences."""
        fields = {
            "reference_frequency_hz": [self.reference.frequency_hz],
            "target_frequency_hz": [self.target.frequency_hz],
            "frequency_delta_hz": [self.frequency_delta_hz],
            "reference_amplitude_dbm": [self.reference.amplitude_dbm],
            "target_amplitude_dbm": [self.target.amplitude_dbm],
            "amplitude_delta_db": [self.amplitude_delta_db],
        }
        return self._measurement_result(
            pl.DataFrame(fields, schema={name: pl.Float64 for name in fields}),
            "dB",
            "spectrum_marker_delta",
            acquisition="derived",
            source_acquisition="held" if self.readout_timestamp is not None else None,
            trace=self.target.channel,
            reference_marker=self.reference.marker,
            marker=self.target.marker,
            column_units={
                "reference_frequency_hz": "Hz",
                "target_frequency_hz": "Hz",
                "frequency_delta_hz": "Hz",
                "reference_amplitude_dbm": "dBm",
                "target_amplitude_dbm": "dBm",
                "amplitude_delta_db": "dB",
            },
        )


def _axis_name(unit: Literal["Hz", "s"]) -> str:
    return "frequency_hz" if unit == "Hz" else "time_s"


@dataclass(frozen=True)
class SpectrumPeak(_SpectrumMeasurement):
    """One measured trace bin (no interpolation or instrument marker state)."""

    index: int
    coordinate: float
    axis_unit: Literal["Hz", "s"]
    amplitude: float
    amplitude_unit: str
    trace: int | None = field(default=None, kw_only=True, compare=False, repr=False)
    source_acquisition: Literal["held", "fresh"] | None = field(
        default=None,
        kw_only=True,
        compare=False,
        repr=False,
    )

    def to_measurement_result(self) -> MeasurementResult:
        """Return the selected measured bin with its original axis and amplitude units."""
        axis_name = _axis_name(self.axis_unit)
        return self._measurement_result(
            pl.DataFrame(
                {axis_name: [self.coordinate], "amplitude": [self.amplitude]},
                schema={axis_name: pl.Float64, "amplitude": pl.Float64},
            ),
            self.amplitude_unit,
            "spectrum_peak",
            acquisition="derived",
            bin_index=self.index,
            trace=self.trace,
            source_acquisition=self.source_acquisition
            if self.readout_timestamp is not None
            else None,
            axis_source="instrument" if self.readout_timestamp is not None else "caller_supplied",
            column_units={axis_name: self.axis_unit, "amplitude": self.amplitude_unit},
        )


@dataclass(frozen=True)
class SpectrumTrace(_SpectrumMeasurement):
    """Measured trace samples with instrument-returned coordinates and units."""

    trace: int
    axis: tuple[float, ...]
    amplitudes: tuple[float, ...]
    axis_kind: Literal["frequency", "time"]
    amplitude_unit: str
    acquisition: Literal["held", "fresh"] = "held"
    sweep_count: int | None = None
    trace_mode: SpectrumTraceMode | None = None

    @property
    def axis_unit(self) -> Literal["Hz", "s"]:
        return "Hz" if self.axis_kind == "frequency" else "s"

    @property
    def x(self) -> list[float]:
        """Compatibility accessor for code using get_trace().x."""
        return list(self.axis)

    @property
    def y(self) -> list[float]:
        """Compatibility accessor for code using get_trace().y."""
        return list(self.amplitudes)

    @property
    def x_label(self) -> str:
        return f"{self.axis_kind.capitalize()} ({self.axis_unit})"

    @property
    def y_label(self) -> str:
        return f"Amplitude ({self.amplitude_unit})"

    def peak(self) -> SpectrumPeak:
        """Return the highest measured bin; ties select the first coordinate."""
        index = max(range(len(self.amplitudes)), key=self.amplitudes.__getitem__)
        return SpectrumPeak(
            index,
            self.axis[index],
            self.axis_unit,
            self.amplitudes[index],
            self.amplitude_unit,
            instrument=self.instrument,
            readout_timestamp=self.readout_timestamp,
            trace=self.trace,
            source_acquisition=self.acquisition,
        )

    def to_measurement_result(self) -> MeasurementResult:
        """Return the instrument-provided axis and corresponding samples."""
        axis_name = _axis_name(self.axis_unit)
        return self._measurement_result(
            pl.DataFrame(
                {axis_name: self.axis, "amplitude": self.amplitudes},
                schema={axis_name: pl.Float64, "amplitude": pl.Float64},
            ),
            self.amplitude_unit,
            "spectrum_trace",
            acquisition=self.acquisition,
            trace=self.trace,
            sweep_count=self.sweep_count,
            trace_mode=self.trace_mode,
            axis_source="instrument" if self.readout_timestamp is not None else "caller_supplied",
            column_units={axis_name: self.axis_unit, "amplitude": self.amplitude_unit},
        )


@dataclass(frozen=True)
class SpectrumTraceFrame(_SpectrumMeasurement):
    """Two or more ordered display traces verified from one passive sweep."""

    traces: tuple[SpectrumTrace, ...]
    axis: tuple[float, ...]
    axis_unit: Literal["Hz", "s"]
    amplitude_unit: str

    @property
    def channels(self) -> tuple[int, ...]:
        return tuple(trace.trace for trace in self.traces)

    def to_measurement_result(self) -> MeasurementResult:
        """Return the shared axis and one column per display trace in the captured order."""
        if (
            len(self.traces) < 2
            or len(set(self.channels)) != len(self.traces)
            or any(
                trace.axis != self.axis
                or trace.axis_unit != self.axis_unit
                or trace.amplitude_unit != self.amplitude_unit
                or len(trace.amplitudes) != len(self.axis)
                or trace.acquisition != "fresh"
                for trace in self.traces
            )
        ):
            raise ValueError(
                "Spectrum frame requires distinct fresh traces on the same axis and unit."
            )
        axis_name = _axis_name(self.axis_unit)
        columns = {f"trace_{trace.trace}": trace.amplitudes for trace in self.traces}
        return self._measurement_result(
            pl.DataFrame(
                {axis_name: self.axis, **columns},
                schema={name: pl.Float64 for name in (axis_name, *columns)},
            ),
            self.amplitude_unit,
            "spectrum_trace_frame",
            acquisition="fresh",
            trace_order=list(self.channels),
            traces=[
                {
                    "trace": trace.trace,
                    "sweep_count": trace.sweep_count,
                    "trace_mode": trace.trace_mode,
                    "readout_timestamp": trace.readout_timestamp,
                }
                for trace in self.traces
            ],
            axis_source="instrument" if self.readout_timestamp is not None else "caller_supplied",
            column_units={axis_name: self.axis_unit, **dict.fromkeys(columns, self.amplitude_unit)},
        )


class SpectrumAnalyser(Instrument[SpectrumAnalyzerConfig]):
    _spectrum_session_uncertain = False

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "configure_measurement",
            public_method="configure_measurement",
            group="sweep",
            scope="family",
        ),
        OperationDescriptor(
            "prepare_sweep",
            capability="single_sweep",
            required=False,
            group="sweep",
            scope="family",
        ),
        OperationDescriptor(
            "configure_rf_input",
            capability="rf_input",
            required=False,
            group="rf-input",
            scope="family",
        ),
        OperationDescriptor(
            "get_rf_input",
            capability="rf_input",
            safety_class="read",
            required=False,
            group="rf-input",
            scope="family",
        ),
        OperationDescriptor(
            "configure_sweep_control",
            capability="sweep_control",
            required=False,
            group="sweep",
            scope="family",
        ),
        OperationDescriptor(
            "get_sweep_control",
            capability="sweep_control",
            safety_class="read",
            required=False,
            group="sweep",
            scope="family",
        ),
        OperationDescriptor(
            "configure_external_trigger",
            capability="sweep_control",
            required=False,
            group="trigger",
            scope="family",
        ),
        OperationDescriptor(
            "get_external_trigger_settings",
            capability="sweep_control",
            safety_class="read",
            required=False,
            group="trigger",
            scope="family",
        ),
        OperationDescriptor(
            "configure_trace",
            capability="trace_setup",
            required=False,
            group="trace",
            scope="family",
        ),
        OperationDescriptor(
            "set_marker", capability="markers", required=False, group="markers", scope="family"
        ),
        OperationDescriptor(
            "measure_channel_power",
            capability="single_sweep",
            required=False,
            group="measurements",
            scope="family",
        ),
        OperationDescriptor(
            "measure_adjacent_channel_power",
            capability="single_sweep",
            required=False,
            group="measurements",
            scope="model",
        ),
        OperationDescriptor(
            "measure_adjacent_channel_pairs",
            capability="single_sweep",
            required=False,
            group="measurements",
            scope="model",
        ),
        OperationDescriptor(
            "measure_occupied_bandwidth",
            capability="single_sweep",
            required=False,
            group="measurements",
            scope="family",
        ),
        OperationDescriptor(
            "find_marker_peak",
            capability="markers",
            required=False,
            group="markers",
            scope="family",
        ),
        OperationDescriptor(
            "measure_marker_delta",
            capability="markers",
            required=False,
            group="markers",
            scope="family",
        ),
        OperationDescriptor(
            "get_trace_settings",
            capability="trace_setup",
            safety_class="read",
            required=False,
            group="trace",
            scope="family",
        ),
        OperationDescriptor(
            "get_trace",
            capability="trace_readback",
            public_method="get_trace",
            safety_class="read",
            required=False,
            group="trace",
            scope="family",
        ),
        OperationDescriptor(
            "get_sweep_settings",
            capability="trace_readback",
            public_method="get_sweep_settings",
            safety_class="read",
            required=False,
            group="sweep",
            scope="family",
        ),
        OperationDescriptor(
            "acquire_trace",
            capability="single_sweep",
            public_method="acquire_trace",
            required=False,
            group="trace",
            scope="family",
        ),
        OperationDescriptor(
            "acquire_traces",
            capability="single_sweep",
            required=False,
            group="trace",
            scope="family",
            python_arguments=(
                OperationPythonArgument(
                    "channels", "Sequence[int]", "Two or more distinct display trace indexes."
                ),
            ),
        ),
    )

    def configure_measurement(
        self,
        center_freq: float | None = None,
        span: float | None = None,
        rbw: float | None = None,
        *,
        vbw: float | None = None,
        sweep_points: int | None = None,
    ) -> None:
        """Write only supplied sweep settings; frequencies/bandwidths are in Hz."""
        if sweep_points is not None and type(sweep_points) is not int:
            raise InstrumentConfigurationError(
                self.config.model, "Sweep points must be an integer."
            )
        arguments = {
            name: value
            for name, value in {
                "center_freq": center_freq,
                "span": span,
                "rbw": rbw,
                "vbw": vbw,
                "sweep_points": sweep_points,
            }.items()
            if value is not None
        }
        resolved = self._resolve_operation_arguments("configure_measurement", arguments)
        # Check every requested setting and build the full write plan before I/O.
        plan = [
            command
            for alias, params in resolved.items()
            for command in self._build_profile_alias(alias, **params)
        ]
        if not plan:
            return
        guard: dict[str, str] = {}
        if self.config.single_sweep is not None:
            keys = ("trace_mode", "source_mode", "error_queue")
            if self.config.single_sweep.sweep_guard == "sweep_count":
                keys += ("source_options", "sequencer")
            guard = self._query_plan("acquire_trace", keys)
        with self._spectrum_transaction():
            if guard:

                def ask(key: str) -> str:
                    return self._query(guard[key], skip_check=True)

                self._check_error_reply(ask("error_queue"))
                self._check_mode(ask("trace_mode"))
                self._check_passive(ask, guard)
                self._check_error_reply(ask("error_queue"))
            for command in plan:
                self._send_command(command)

    def prepare_sweep(
        self, channel: int = 1, *, stop_continuous: bool = False, timeout_ms: int = 10_000
    ) -> SpectrumSweepReadiness:
        """Prepare an active Clear/Write trace for a passive ASCII single sweep.

        The analyzer must already be in ordinary Spectrum mode. Refuses
        retained average/hold, trace math, active generator control, or
        unsupported FSW layouts instead of overwriting them. Changes only
        continuous mode, transfer format, and the Keysight display selection.
        Set stop_continuous=True to stop an ongoing continuous run. The
        method never initiates a sweep or promises to preserve pending data.
        """
        operation = "prepare_sweep"
        self._validate_timeout(timeout_ms)
        if not self.supports_operation(operation):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement {operation}."
            )
        self._require_int("Trace index", channel)
        if type(stop_continuous) is not bool:
            raise InstrumentConfigurationError(self.config.model, "stop_continuous must be a bool.")
        self._resolve_operation_parameter(operation, "channel", channel)
        self._resolve_operation_parameter(operation, "stop_continuous", stop_continuous)
        self._resolve_operation_parameter(operation, "timeout_ms", timeout_ms)
        spec = self.config.single_sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Missing passive sweep safeguards."
            )
        trace_plan = self._trace_plan(channel)
        key = spec.sweep_guard == "active_trace_types"
        fields = ("source_mode", "error_queue", "trace_mode")
        if key:
            fields += ("normalization",)
            selected_keys = ("trace_type", "trace_update", "trace_math")
        else:
            fields += ("source_options", "sequencer", "sweep_count", "trace_math")
            selected_keys = ("trace_type",)
        state = self._query_plan("acquire_trace", fields)
        selected = self._query_plan("acquire_trace", selected_keys, channel=channel)
        others = (
            [
                self._query_plan("acquire_trace", selected_keys, channel=other)
                for other in range(1, 7)
                if other != channel
            ]
            if key
            else []
        )
        fsw_layout = (
            {}
            if key
            else self._query_plan(operation, ("operating_mode", "window_catalog", "window_type"))
        )
        fsw_active = (
            None
            if key
            else self._query_plan("get_trace_settings", ("updating",), channel=channel)["updating"]
        )
        normal = self._single_command("acquire_trace", "normal_view") if key else None
        set_single = self._single_command(operation, "set_single")
        set_ascii = self._single_command(operation, "set_ascii")
        condition = self._single_command(operation, "operation_condition", query=True)
        with self._spectrum_transaction():
            query, send = self._bounded_exchange(operation, timeout_ms)

            def ask(name: str) -> str:
                return query(trace_plan[name])

            def check_errors() -> None:
                self._check_error_reply(query(state["error_queue"]))

            def write(command: str) -> None:
                send(command)
                check_errors()

            def inspect() -> tuple[bool, bool, tuple[float, int, str]]:
                check_errors()
                self._check_mode(ask("trace_mode"))
                self._check_passive(lambda name: query(state[name]), state)
                if key:
                    self._check_keysight_trace(query, state, (selected,), others)
                else:
                    self._require_fsw_capture_layout(query, fsw_layout)
                    if self._native_count(query(state["sweep_count"])) not in {0, 1}:
                        raise InstrumentDataError(
                            self.config.model, "Set FSW sweep count to 0 or 1."
                        )
                    if self._is_on(query(state["trace_math"])):
                        raise InstrumentDataError(
                            self.config.model, "Disable FSW trace math before preparing."
                        )
                    assert fsw_active is not None
                    if not self._is_on(query(fsw_active)):
                        raise InstrumentDataError(
                            self.config.model, "Enable the selected FSW display trace first."
                        )
                if not self._is_write(query(selected["trace_type"])):
                    raise InstrumentDataError(
                        self.config.model, "Select an updating Clear/Write trace."
                    )
                continuous = self._is_on(ask("trace_continuous"))
                ascii_format = self._prepare_trace_format(ask("trace_format"), keysight=key)
                metadata = self._trace_metadata(ask)
                check_errors()
                return continuous, ascii_format, metadata

            continuous, ascii_format, _ = inspect()
            if continuous:
                if not stop_continuous:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Pass stop_continuous=True to stop the ongoing continuous acquisition.",
                    )
                write(set_single)
            self._check_held(ask("trace_continuous"))
            self._check_completion(ask("trace_complete"))
            self._require_prepare_idle(query(condition))
            check_errors()
            if not ascii_format:
                write(set_ascii)
            if normal is not None:
                write(normal)
            continuous, ascii_format, (span, points, unit) = inspect()
            if continuous or not ascii_format:
                raise InstrumentDataError(
                    self.config.model,
                    "Spectrum analyzer did not confirm single sweep and ASCII transfer.",
                )
            self._require_prepare_idle(query(condition))
            check_errors()
            return SpectrumSweepReadiness(
                channel=channel,
                span_hz=span,
                sweep_points=points,
                amplitude_unit=unit,
                axis_unit="s" if span == 0 else "Hz",
                continuous=False,
                transfer_format="ascii",
                trace_mode="clear_write",
                display_evidence="normal_selected" if key else "diagram_verified",
            )

    def _prepare_trace_format(self, raw: str, *, keysight: bool) -> bool:
        # Only switch a documented transfer format; unrecognized replies could be stale.
        fields = tuple(self._token(field) for field in raw.split(",", maxsplit=2))
        if fields[0] in {"ASC", "ASCII"} and (
            len(fields) == 1 or (len(fields) == 2 and fields[1].isdigit())
        ):
            return True
        binary_formats = {("REAL", "32"), ("REAL", "64")}
        binary_formats.update({("INT", "32"), ("INTEGER", "32")} if keysight else {("REAL", "16")})
        if fields in binary_formats:
            return False
        raise InstrumentDataError(self.config.model, "Unexpected spectrum trace transfer format.")

    def _require_prepare_idle(self, raw: str) -> None:
        value = self._scalar("operation condition", raw)
        if not 0 <= value <= 32_767 or value != int(value):
            raise InstrumentDataError(self.config.model, "Invalid spectrum operation condition.")
        if int(value) & _SWEEP_BUSY_FLAGS:
            raise InstrumentDataError(
                self.config.model,
                "Analyzer still reports an active sweep, measurement, trigger wait or alignment.",
            )

    def configure_rf_input(
        self,
        *,
        reference_level_dbm: float | None = None,
        attenuation_db: float | None = None,
        attenuation_auto: bool | None = None,
        preamp: bool | None = None,
    ) -> None:
        """Change supplied RF input controls without enabling an RF source.

        A manual attenuation value turns auto attenuation off. Preamp
        control requires an installed, profile-recognized internal preamp.
        """
        self._require_optional_bool("attenuation_auto", attenuation_auto)
        self._require_optional_bool("preamp", preamp)
        if attenuation_db is not None and attenuation_auto is True:
            raise InstrumentConfigurationError(
                self.config.model, "Manual attenuation and auto attenuation are mutually exclusive."
            )
        operation = "configure_rf_input"
        plan = self._settings_plan(
            operation,
            {
                "preamp": preamp if preamp is False else None,
                "attenuation_auto": attenuation_auto,
                "attenuation_db": attenuation_db,
                "reference_level_dbm": reference_level_dbm,
            },
        )
        if preamp is True:
            plan += self._settings_plan(operation, {"preamp": preamp})
        if not plan:
            return
        state = self._rf_state(operation, ("unit",))
        with self._spectrum_transaction():
            self._setup_guard()
            if reference_level_dbm is not None:
                self._require_dbm(self._query(state["unit"], skip_check=True))
            if preamp is not None or "frontend" in state:
                options = self._read_rf_options(state)
                if preamp is not None and not self._preamp_installed(options):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "The profile did not detect a supported internal preamp option.",
                    )
            self._check_setup_errors("acquire_trace")
            self._write_setup(plan)

    def get_rf_input(self) -> SpectrumRFInputSettings:
        """Read actual RF input settings; requires a dBm amplitude scale."""
        operation = "get_rf_input"
        keys = (
            "unit",
            "reference_level",
            "attenuation",
            "attenuation_auto",
            "preamp",
        )
        state = self._rf_state(operation, keys)
        with self._spectrum_transaction():
            self._check_standard_mode(operation)
            self._require_dbm(self._query(state["unit"], skip_check=True))
            options = self._read_rf_options(state)
            reference = self._scalar(
                "reference level", self._query(state["reference_level"], skip_check=True)
            )
            attenuation = self._scalar(
                "attenuation", self._query(state["attenuation"], skip_check=True)
            )
            if attenuation < 0:
                raise InstrumentDataError(self.config.model, "Invalid input attenuation.")
            auto = self._is_on(self._query(state["attenuation_auto"], skip_check=True))
            preamp = (
                self._is_on(self._query(state["preamp"], skip_check=True))
                if self._preamp_installed(options)
                else None
            )
            self._check_setup_errors(operation)
            return SpectrumRFInputSettings(reference, attenuation, auto, preamp)

    def configure_sweep_control(
        self,
        *,
        sweep_time_s: float | None = None,
        sweep_time_auto: bool | None = None,
        trigger_source: SpectrumTriggerSource | None = None,
        continuous: bool | None = None,
    ) -> None:
        """Set sweep timing, triggering and/or continuous operation.

        Set span with configure_measurement first. A manual time decouples
        timing where available. Selecting continuous starts analyzer activity.
        """
        self._require_optional_bool("sweep_time_auto", sweep_time_auto)
        self._require_optional_bool("continuous", continuous)
        if sweep_time_s is not None and sweep_time_auto is True:
            raise InstrumentConfigurationError(
                self.config.model, "Choose a manual or automatic sweep time."
            )
        operation = "configure_sweep_control"
        args = {
            "continuous": continuous if continuous is False else None,
            "trigger_source": trigger_source,
            "sweep_time_auto": sweep_time_auto,
            "sweep_time_s": sweep_time_s,
        }
        plan = self._settings_plan(operation, args)
        if continuous is True:
            plan += self._settings_plan(operation, {"continuous": continuous})
        if not plan:
            return
        state = self._query_plan(operation, ("span", "sweep_type"))
        direction = None
        if trigger_source is not None and self.config.sweep_control == "fsw":
            source = self._resolve_operation_parameter(operation, "trigger_source", trigger_source)
            if source.value in {"external_2", "external_3"}:
                direction = self._external_direction_command(
                    "configure_external_trigger", cast(SpectrumExternalTriggerSource, source.value)
                )
        with self._spectrum_transaction():
            self._setup_guard()
            if direction is not None:
                self._check_external_direction(direction)
                self._check_setup_errors("acquire_trace")
            if sweep_time_s is not None or sweep_time_auto is not None:
                auto_available, manual_available = self._timing_modes(state)
                if sweep_time_auto is not None and not auto_available:
                    raise InstrumentConfigurationError(
                        self.config.model, "This sweep does not support automatic timing control."
                    )
                if sweep_time_s is not None and not manual_available:
                    raise InstrumentConfigurationError(
                        self.config.model, "This sweep does not support manual timing control."
                    )
            self._write_setup(plan)

    def get_sweep_control(self) -> SpectrumSweepControl:
        """Read the actual duration and active triggering/continuous settings."""
        operation = "get_sweep_control"
        keys = (
            "span",
            "sweep_type",
            "sweep_time",
            "sweep_time_auto",
            "trigger_source",
            "continuous",
        )
        state = self._query_plan(operation, keys)
        with self._spectrum_transaction():
            self._check_standard_mode(operation)
            auto_available, _ = self._timing_modes(state)
            duration = self._scalar("sweep time", self._query(state["sweep_time"], skip_check=True))
            if duration <= 0:
                raise InstrumentDataError(self.config.model, "Invalid sweep time.")
            auto = (
                self._is_on(self._query(state["sweep_time_auto"], skip_check=True))
                if auto_available
                else None
            )
            trigger = cast(
                SpectrumTriggerSource,
                self._read_setting(
                    "configure_sweep_control",
                    "trigger_source",
                    self._query(state["trigger_source"], skip_check=True),
                ),
            )
            continuous = self._is_on(self._query(state["continuous"], skip_check=True))
            self._check_setup_errors(operation)
            return SpectrumSweepControl(duration, auto, trigger, continuous)

    def configure_external_trigger(
        self,
        source: SpectrumExternalTriggerSource = "external_1",
        *,
        level_v: float | None = None,
        slope: SpectrumTriggerSlope | None = None,
    ) -> None:
        """Select an external input and optionally configure its threshold and edge.

        The analyzer must be in single sweep. This method never initiates
        acquisition or changes a connector's input/output direction. The
        FSW slope control is applied with this source selected.
        """
        operation = "configure_external_trigger"
        direction = self._external_direction_command(operation, source)
        select = self._settings_plan("configure_sweep_control", {"trigger_source": source})
        plan = self._settings_plan(
            operation, {"level_v": level_v, "slope": slope}, selectors={"source": source}
        )
        continuous = self._single_command(operation, "continuous", query=True)
        with self._spectrum_transaction():
            self._setup_guard()
            self._check_held(self._query(continuous, skip_check=True))
            self._check_external_direction(direction)
            self._check_setup_errors("acquire_trace")
            self._write_setup(select + plan)

    def get_external_trigger_settings(
        self, source: SpectrumExternalTriggerSource = "external_1"
    ) -> SpectrumExternalTriggerSettings:
        """Read the requested external input and whether it is the current source."""
        operation = "get_external_trigger_settings"
        direction = self._external_direction_command(operation, source)
        spec = self.config.operation_options.operations[operation]
        source = cast(
            SpectrumExternalTriggerSource,
            self._resolve_operation_parameter(operation, "source", source).value,
        )
        args = self._bound_arguments(operation, {"source": source})
        level = self._single_command(
            operation, "level", query=True, args=args[spec.transport["level"]]
        )
        edge = self._single_command(
            operation, "edge", query=True, args=args.get(spec.transport["edge"])
        )
        current = self._single_command(operation, "source", query=True)
        with self._spectrum_transaction():
            self._check_standard_mode(operation)
            self._check_external_direction(direction)
            active = self._read_setting(
                "configure_sweep_control", "trigger_source", self._query(current, skip_check=True)
            )
            value = self._scalar("trigger voltage", self._query(level, skip_check=True))
            minimum, maximum = (
                (-5.0, 5.0) if self.config.sweep_control == "keysight" else (0.5, 3.5)
            )
            if not minimum <= value <= maximum:
                raise InstrumentDataError(self.config.model, "Invalid external trigger threshold.")
            slope = None
            if self.config.sweep_control == "keysight" or active == source:
                slope = cast(
                    SpectrumTriggerSlope,
                    self._read_setting(
                        "configure_external_trigger", "slope", self._query(edge, skip_check=True)
                    ),
                )
            self._check_setup_errors(operation)
            return SpectrumExternalTriggerSettings(source, value, slope, active == source)

    def _external_direction_command(
        self, operation: str, source: SpectrumExternalTriggerSource
    ) -> str | None:
        if not self.supports_operation(operation):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement {operation}."
            )
        resolved = self._resolve_operation_parameter(operation, "source", source)
        if self.config.sweep_control == "fsw" and resolved.value != "external_1":
            return self._single_command(
                operation, "direction", query=True, args={"port": resolved.transport_value}
            )
        return None

    def _check_external_direction(self, command: str | None) -> None:
        if command is None:
            return
        if self._token(self._query(command, skip_check=True)) not in {"INP", "INPUT"}:
            raise InstrumentDataError(
                self.config.model, "Set the FSW trigger connector to Input before selecting it."
            )

    def configure_trace(
        self,
        channel: int = 1,
        *,
        mode: SpectrumTraceMode | None = None,
        detector: SpectrumDetector | None = None,
        detector_auto: bool | None = None,
        accumulation_count: int | None = None,
    ) -> None:
        """Set native trace processing and detector for one display trace.

        The count is analyzer-wide, not per trace. Mode changes can clear
        trace history, change auto detector selection or restart a sweep.
        """
        self._require_optional_bool("detector_auto", detector_auto)
        if detector is not None and detector_auto is True:
            raise InstrumentConfigurationError(
                self.config.model, "Choose an explicit or automatic detector."
            )
        self._require_int("Trace index", channel)
        if accumulation_count is not None:
            self._require_int("Accumulation count", accumulation_count)
        changes = {
            "accumulation_count": accumulation_count,
            "mode": mode,
            "detector_auto": False if detector is not None else detector_auto,
            "detector": detector,
        }
        operation = "configure_trace"
        plan = self._settings_plan(operation, changes, selectors={"channel": channel})
        if not plan:
            return
        with self._spectrum_transaction():
            self._setup_guard()
            self._write_setup(plan)

    def get_trace_settings(self, channel: int = 1) -> SpectrumTraceSettings:
        """Read the trace processing state independently of trace samples."""
        operation = "get_trace_settings"
        keys = ("trace_type", "detector", "detector_auto", "count", "updating")
        state = self._query_plan(operation, keys, channel=channel)
        with self._spectrum_transaction():
            self._check_standard_mode(operation)
            mode = self._trace_mode(self._query(state["trace_type"], skip_check=True))
            detector = cast(
                SpectrumDetector,
                self._read_setting(
                    "configure_trace", "detector", self._query(state["detector"], skip_check=True)
                ),
            )
            auto = self._is_on(self._query(state["detector_auto"], skip_check=True))
            count = self._native_count(self._query(state["count"], skip_check=True))
            enabled = self._is_on(self._query(state["updating"], skip_check=True))
            # On FSW, a displayed VIEW trace is enabled but frozen.
            updating = enabled and mode not in {"view", "blank"}
            self._check_setup_errors(operation)
            return SpectrumTraceSettings(channel, mode, detector, auto, count, updating)

    def set_marker(
        self, frequency_hz: float, *, marker: int = 1, channel: int = 1
    ) -> SpectrumMarker:
        """Position a normal marker on a held swept trace and read its actual location."""
        operation = "set_marker"
        plan = self._marker_commands(operation, marker, channel, frequency_hz=frequency_hz)
        with self._spectrum_transaction():
            self._marker_guard(operation, channel)
            return self._position_marker(operation, marker, channel, plan, action="position")

    def find_marker_peak(
        self, *, marker: int = 1, channel: int = 1, next_peak: bool = False
    ) -> SpectrumMarker:
        """Move a normal marker to a native peak on the held trace.

        Set next_peak after finding a peak with the same marker and trace.
        Search uses the analyzer's own peak criteria.
        """
        if type(next_peak) is not bool:
            raise InstrumentConfigurationError(self.config.model, "next_peak must be a bool.")
        operation = "find_marker_peak"
        plan = self._marker_commands(operation, marker, channel)
        with self._spectrum_transaction():
            self._marker_guard(operation, channel)
            return self._position_marker(
                operation, marker, channel, plan, action="next" if next_peak else "peak"
            )

    def measure_marker_delta(
        self,
        reference_hz: float,
        target_hz: float,
        *,
        reference_marker: int = 1,
        marker: int = 2,
        channel: int = 1,
    ) -> SpectrumMarkerDelta:
        """Read back two normal markers and calculate target minus reference."""
        if marker == reference_marker:
            raise InstrumentConfigurationError(self.config.model, "Choose distinct marker indexes.")
        operation = "measure_marker_delta"
        if not self.supports_operation(operation):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement {operation}."
            )
        self._bound_arguments(
            operation,
            dict(
                reference_marker=reference_marker,
                marker=marker,
                channel=channel,
                reference_hz=reference_hz,
                target_hz=target_hz,
            ),
        )
        reference = self._marker_commands(
            operation, reference_marker, channel, frequency_hz=reference_hz
        )
        target = self._marker_commands(operation, marker, channel, frequency_hz=target_hz)
        with self._spectrum_transaction():
            self._marker_guard(operation, channel)
            return SpectrumMarkerDelta(
                self._position_marker(
                    operation, reference_marker, channel, reference, action="position"
                ),
                self._position_marker(operation, marker, channel, target, action="position"),
                instrument=self.config.model,
                readout_timestamp=time(),
            )

    def measure_channel_power(
        self, *, bandwidth_hz: float | None = None, timeout_ms: int = 10_000
    ) -> SpectrumChannelPower:
        """Start and fetch native single-carrier integrated power in dBm.

        Select Channel Power in the Keysight SA application first. The FSW
        workflow selects its Channel Power measurement in the Spectrum channel.
        """
        power, actual = self._measure_scalar(
            "measure_channel_power", "bandwidth_hz", bandwidth_hz, timeout_ms=timeout_ms
        )
        return SpectrumChannelPower(
            power, actual, instrument=self.config.model, readout_timestamp=time()
        )

    def measure_occupied_bandwidth(
        self, *, power_percent: float | None = None, timeout_ms: int = 10_000
    ) -> SpectrumOccupiedBandwidth:
        """Start and fetch native occupied bandwidth in Hz for a power percentage.

        Select Occupied BW in the Keysight SA application first. The FSW
        workflow selects its Occupied BW measurement in the Spectrum channel.
        """
        bandwidth, actual = self._measure_scalar(
            "measure_occupied_bandwidth", "power_percent", power_percent, timeout_ms=timeout_ms
        )
        return SpectrumOccupiedBandwidth(
            bandwidth, actual, instrument=self.config.model, readout_timestamp=time()
        )

    def measure_adjacent_channel_power(
        self,
        *,
        carrier_bandwidth_hz: float | None = None,
        adjacent_bandwidth_hz: float | None = None,
        spacing_hz: float | None = None,
        timeout_ms: int = 10_000,
    ) -> SpectrumAdjacentChannelPower:
        """Measure one carrier and its lower/upper adjacent channels.

        Spacing is center-to-center. Unspecified geometry is read from the
        analyzer. Select Keysight SA > ACP with radio standard None, one
        carrier, and only offset A. This workflow is supported by the
        bundled N9000A profile only.
        """
        operation = "measure_adjacent_channel_power"
        changes = dict(
            carrier_bandwidth_hz=carrier_bandwidth_hz,
            adjacent_bandwidth_hz=adjacent_bandwidth_hz,
            spacing_hz=spacing_hz,
        )
        result = self._measure_acp(operation, pair_count=1, changes=changes, timeout_ms=timeout_ms)
        pair = result.pairs[0]
        return SpectrumAdjacentChannelPower(
            result.carrier_power_dbm,
            pair.lower_power_dbm,
            pair.upper_power_dbm,
            pair.lower_relative_dbc,
            pair.upper_relative_dbc,
            result.carrier_bandwidth_hz,
            pair.bandwidth_hz,
            pair.spacing_hz,
            instrument=result.instrument,
            readout_timestamp=result.readout_timestamp,
        )

    def measure_adjacent_channel_pairs(
        self, pair_count: int, *, timeout_ms: int = 10_000
    ) -> SpectrumAdjacentChannelPowerSeries:
        """Measure preconfigured adjacent and alternate pairs for one carrier.

        Pair count is verified, not set. Use contiguous, symmetric,
        non-overlapping bands, nearest first, starting at Keysight offset A.
        The method never turns on an RF source.
        """
        operation = "measure_adjacent_channel_pairs"
        self._require_int("Adjacent pair count", pair_count)
        if not self.supports_operation(operation):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement {operation}."
            )
        self._resolve_operation_parameter(operation, "pair_count", pair_count)
        return self._measure_acp(
            operation, pair_count=pair_count, changes={}, timeout_ms=timeout_ms
        )

    def _measure_acp(
        self,
        operation: str,
        *,
        pair_count: int,
        changes: Mapping[str, float | None],
        timeout_ms: int,
    ) -> SpectrumAdjacentChannelPowerSeries:
        self._validate_timeout(timeout_ms)
        sweep = self.config.single_sweep
        if sweep is None or sweep.sweep_guard != "active_trace_types":
            raise InstrumentConfigurationError(
                self.config.model,
                "ACP requires a profile with verified symmetric channel topology.",
            )
        base_operation = "measure_adjacent_channel_power"
        writes = self._settings_plan(base_operation, changes)
        queries = (
            "trace_mode",
            "source_mode",
            "error_queue",
            "continuous",
            "complete",
            "result",
            "carrier_count",
            "carrier_bandwidth_hz",
            "adjacent_bandwidth_hz",
            "spacing_hz",
            "span",
            "application",
            "averaging",
            "radio_standard",
            "reference_type",
            "power_reference",
            "method",
            "offset_enabled",
            "offset_side",
            "offset_type",
        )
        state = self._query_plan(base_operation, queries)
        initiate = self._single_command(base_operation, "initiate")
        with self._spectrum_transaction():
            query, send = self._bounded_exchange(operation, timeout_ms)

            def ask(name: str) -> str:
                return query(state[name])

            def write(command: str) -> None:
                send(command)
                self._check_error_reply(ask("error_queue"))

            def require_application() -> None:
                if (
                    self._token(ask("trace_mode")) not in {"ACP", "ACPOWER"}
                    or self._scalar("application", ask("application")) != 1
                ):
                    raise InstrumentDataError(
                        self.config.model, "Select ACP in the Keysight SA application first."
                    )

            self._check_error_reply(ask("error_queue"))
            require_application()
            self._check_held(ask("continuous"))
            self._check_passive(ask, state)
            self._check_error_reply(ask("error_queue"))
            self._check_acp_result_mode(ask, pair_count=pair_count)
            carrier_bandwidth, bands = self._acp_geometry(ask, pair_count=pair_count)
            if writes:
                prospective = tuple(
                    requested if requested is not None else current
                    for requested, current in zip(
                        changes.values(), (carrier_bandwidth, *bands[0]), strict=True
                    )
                )
                self._check_acp_passbands(prospective[0], ((prospective[1], prospective[2]),))
                self._check_error_reply(ask("error_queue"))
                for command in writes:
                    write(command)
                self._check_acp_result_mode(ask, pair_count=pair_count)
                carrier_bandwidth, bands = self._acp_geometry(ask, pair_count=pair_count)
            required_span = self._check_acp_passbands(carrier_bandwidth, bands)
            if self._scalar("ACP span", ask("span")) < required_span:
                raise InstrumentDataError(
                    self.config.model, "Increase ACP span to include all adjacent channels."
                )
            self._check_error_reply(ask("error_queue"))
            send(initiate)
            self._check_completion(ask("complete"))
            if pair_count > 1:
                require_application()
            self._check_acp_result_mode(ask, pair_count=pair_count)
            if pair_count > 1 and self._acp_geometry(ask, pair_count=pair_count) != (
                carrier_bandwidth,
                bands,
            ):
                raise InstrumentDataError(
                    self.config.model, "ACP channel geometry changed during capture."
                )
            self._check_error_reply(ask("error_queue"))
            raw = ask("result")
            self._check_error_reply(ask("error_queue"))
            return self._acp_power_results(raw, carrier_bandwidth=carrier_bandwidth, bands=bands)

    def _check_acp_result_mode(self, ask: Callable[[str], str], *, pair_count: int) -> None:
        if self._scalar("carrier count", ask("carrier_count")) != 1:
            raise InstrumentDataError(self.config.model, "Configure exactly one ACP carrier.")
        tokens = (
            ("radio_standard", {"NONE"}, "radio standard None"),
            ("reference_type", {"TPR", "TPREF"}, "Total Power Ref"),
            ("power_reference", {"RCAR", "RCARRIER"}, "Reference Carrier power"),
            ("method", {"IBW"}, "Integration BW method"),
            ("offset_type", {"CTOC", "CTOCENTER"}, "center-to-center offset"),
        )
        for name, accepted, target in tokens:
            if self._token(ask(name)) not in accepted:
                raise InstrumentDataError(self.config.model, f"Set Keysight ACP to {target}.")
        enabled = [self._is_on(value) for value in ask("offset_enabled").split(",", maxsplit=6)]
        if enabled != [True] * pair_count + [False] * (6 - pair_count):
            message = (
                "Enable only Keysight ACP offset A."
                if pair_count == 1
                else f"Enable exactly the first {pair_count} Keysight ACP offsets, with no gaps."
            )
            raise InstrumentDataError(self.config.model, message)
        side = ask("offset_side").split(",", maxsplit=6)
        if len(side) < pair_count or any(
            self._token(field) != "BOTH" for field in side[:pair_count]
        ):
            raise InstrumentDataError(
                self.config.model, "Enable both sides of each selected Keysight ACP offset."
            )
        if self._is_on(ask("averaging")):
            raise InstrumentDataError(
                self.config.model, "Turn off Keysight ACP measurement averaging."
            )

    def _acp_geometry(
        self, ask: Callable[[str], str], *, pair_count: int
    ) -> tuple[float, tuple[tuple[float, float], ...]]:
        def read(name: str, count: int = 1, limit: int = 1) -> tuple[float, ...]:
            fields = ask(name).split(",", maxsplit=limit)
            if not count <= len(fields) <= limit:
                raise InstrumentDataError(self.config.model, f"Unexpected ACP {name} list.")
            values = tuple(self._scalar(name, field) for field in fields[:count])
            if any(value <= 0 for value in values):
                raise InstrumentDataError(self.config.model, f"Invalid ACP {name}.")
            return values

        carrier = read("carrier_bandwidth_hz", limit=18)[0]
        widths = read("adjacent_bandwidth_hz", count=pair_count, limit=6)
        spacings = read("spacing_hz", count=pair_count, limit=6)
        return carrier, tuple(zip(widths, spacings, strict=True))

    def _check_acp_passbands(self, carrier: float, bands: tuple[tuple[float, float], ...]) -> float:
        previous_edge = carrier / 2
        for index, (width, spacing) in enumerate(bands):
            if spacing - width / 2 < previous_edge:
                subject = "carrier and adjacent" if index == 0 else "adjacent or alternate"
                raise InstrumentDataError(
                    self.config.model, f"ACP {subject} passbands overlap or are out of order."
                )
            previous_edge = spacing + width / 2
        return 2 * previous_edge

    def _acp_power_results(
        self,
        raw: str,
        *,
        carrier_bandwidth: float,
        bands: tuple[tuple[float, float], ...],
    ) -> SpectrumAdjacentChannelPowerSeries:
        count = len(bands)
        if count > 1:
            values = self._parse_trace_values(raw, 28)
            if values[0] != 0 or values[2] != 0 or values[1] == -999:
                raise InstrumentDataError(
                    self.config.model, "Invalid Keysight ACP Total Power result."
                )
            carrier = values[3]
            if carrier == -999:
                raise InstrumentDataError(
                    self.config.model, "Missing Keysight ACP reference carrier power."
                )
            pairs = [
                (values[i + 1], values[i + 3], values[i], values[i + 2])
                for i in range(4, 4 + 4 * count, 4)
            ]
        else:
            carrier, *offsets = self._parse_trace_values(raw, 1 + 2 * count)
            if carrier == -999 or -999 in offsets:
                message = (
                    "Analyzer did not return all three ACP powers."
                    if count == 1
                    else "Analyzer did not return all active ACP powers."
                )
                raise InstrumentDataError(self.config.model, message)
            lower, upper = offsets
            pairs = [(carrier + lower, carrier + upper, lower, upper)]
        if any(-999 in result for result in pairs):
            raise InstrumentDataError(
                self.config.model, "Analyzer did not return all active ACP powers."
            )
        result = tuple(
            SpectrumAdjacentChannelPair(index, spacing, bandwidth, *powers)
            for index, ((bandwidth, spacing), powers) in enumerate(
                zip(bands, pairs, strict=True), 1
            )
        )
        return SpectrumAdjacentChannelPowerSeries(
            carrier,
            carrier_bandwidth,
            result,
            instrument=self.config.model,
            readout_timestamp=time(),
        )

    def _measure_scalar(
        self, operation: str, parameter: str, value: float | None, *, timeout_ms: int
    ) -> tuple[float, float]:
        self._validate_timeout(timeout_ms)
        writes = self._settings_plan(operation, {parameter: value})
        spec = self.config.single_sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Missing passive sweep safeguards."
            )
        key = spec.sweep_guard == "active_trace_types"
        power = parameter == "bandwidth_hz"
        keys = ("trace_mode", "continuous", "complete", "error_queue", "setting", "result")
        keys += ("source_mode",)
        if key:
            keys += ("application", "averaging")
        else:
            keys += (
                "source_options",
                "sequencer",
                "span",
                "count",
                "trace_type",
                "trace_active",
                "trace_math",
            )
            if power:
                keys += ("unit", "scale", "tx_channels", "power_trace_mode", "power_density")
        state = self._query_plan(operation, keys)
        select = None if key else self._single_command(operation, "select")
        trace_one = None if key else self._single_command(operation, "trace_one")
        stop_power = None if key else self._single_command(operation, "stop_power")
        initiate = self._single_command(operation, "initiate")
        with self._native_power_transaction() as fsw_power_selected:
            query, send = self._bounded_exchange(operation, timeout_ms)

            def ask(name: str) -> str:
                return query(state[name])

            def write(command: str) -> None:
                send(command)
                self._check_error_reply(ask("error_queue"))

            self._check_error_reply(ask("error_queue"))
            mode = ask("trace_mode")
            if key:
                expected = {"CHP", "CHPOWER"} if power else {"OBW", "OBWIDTH"}
                if (
                    self._token(mode) not in expected
                    or self._scalar("application", ask("application")) != 1
                ):
                    name = "Channel Power" if power else "Occupied BW"
                    raise InstrumentDataError(
                        self.config.model, f"Select {name} in the Keysight SA application first."
                    )
                if self._is_on(ask("averaging")):
                    raise InstrumentDataError(
                        self.config.model, "Turn off native measurement averaging first."
                    )
            else:
                self._check_mode(mode)
                if self._scalar("span", ask("span")) <= 0:
                    raise InstrumentDataError(
                        self.config.model, "The native measurement requires a non-zero span."
                    )
            self._check_held(ask("continuous"))
            self._check_passive(ask, state)
            self._check_error_reply(ask("error_queue"))
            if select is not None:
                fsw_power_selected(True)
                write(select)
                self._check_mode(ask("trace_mode"))
                self._check_passive(ask, state)
                self._check_held(ask("continuous"))
                if self._native_count(ask("count")) not in {0, 1}:
                    raise InstrumentDataError(self.config.model, "Set FSW sweep count to 0 or 1.")
                self._require_fsw_power_trace(ask)
                if power:
                    self._require_dbm(ask("unit"))
                    self._require_log_scale(ask("scale"))
                    if self._scalar("TX channel count", ask("tx_channels")) != 1:
                        raise InstrumentDataError(
                            self.config.model, "Select one FSW transmit channel."
                        )
                    if not self._is_write(ask("power_trace_mode")):
                        raise InstrumentDataError(
                            self.config.model, "Set FSW power mode to Clear/Write."
                        )
                assert trace_one is not None
                write(trace_one)
            for command in writes:
                write(command)
            actual = self._scalar(parameter, ask("setting"))
            if actual <= 0 or (not power and not 10 <= actual < 100):
                raise InstrumentDataError(self.config.model, f"Invalid readback for {parameter}.")
            if "power_density" in state:
                self._require_absolute_power(ask("power_density"))
            self._check_error_reply(ask("error_queue"))
            send(initiate)
            self._check_completion(ask("complete"))
            if "power_density" in state:
                self._require_absolute_power(ask("power_density"))
            self._check_error_reply(ask("error_queue"))
            result = self._scalar("native spectrum result", ask("result"))
            self._check_error_reply(ask("error_queue"))
            if not power and result <= 0:
                raise InstrumentDataError(self.config.model, "Invalid occupied bandwidth.")
            if stop_power is not None:
                write(stop_power)
                fsw_power_selected(False)
            return result, actual

    @contextmanager
    def _native_power_transaction(self) -> Iterator[Callable[[bool], None]]:
        power_view_may_be_active = False

        def fsw_power_selected(active: bool) -> None:
            nonlocal power_view_may_be_active
            power_view_may_be_active = active

        with self._spectrum_transaction():
            try:
                yield fsw_power_selected
            finally:
                if power_view_may_be_active:
                    # INST:SEL? does not distinguish an active FSW power measurement from plain Spectrum.
                    self._spectrum_session_uncertain = True

    def _require_fsw_power_trace(self, ask: Callable[[str], str]) -> None:
        if (
            self._is_on(ask("trace_math"))
            or not self._is_write(ask("trace_type"))
            or not self._is_on(ask("trace_active"))
        ):
            raise InstrumentDataError(
                self.config.model,
                "Select an active FSW Trace 1 Clear/Write trace with trace math off.",
            )

    def _require_absolute_power(self, reply: str) -> None:
        if self._is_on(reply):
            raise InstrumentDataError(
                self.config.model, "Turn off FSW channel power density (/Hz) for integrated dBm."
            )

    def _marker_guard(self, operation: str, channel: int) -> None:
        keys = ("trace_mode", "continuous", "complete", "span", "unit", "error_queue")
        if self.config.markers == "fsw":
            keys += ("scale",)
        state = self._query_plan(operation, keys)
        trace = None
        normal_view = None
        if self.config.markers == "keysight":
            trace = self._query_plan(
                "get_trace_settings", ("trace_type", "updating"), channel=channel
            )
            normal_view = self._single_command("acquire_trace", "normal_view")

        def ask(key: str) -> str:
            return self._query(state[key], skip_check=True)

        def require_span() -> None:
            if self._scalar("span", ask("span")) <= 0:
                raise InstrumentDataError(self.config.model, "Markers require a non-zero span.")

        def require_active_trace(trace_state: Mapping[str, str]) -> None:
            if not self._is_on(
                self._query(trace_state["updating"], skip_check=True)
            ) or not self._is_write(self._query(trace_state["trace_type"], skip_check=True)):
                raise InstrumentDataError(
                    self.config.model, "Select an updating Clear/Write trace for Keysight markers."
                )

        self._check_error_reply(ask("error_queue"))
        self._check_mode(ask("trace_mode"))
        self._check_held(ask("continuous"))
        self._check_completion(ask("complete"))
        require_span()
        self._require_dbm(ask("unit"))
        if "scale" in state:
            self._require_log_scale(ask("scale"))
        if trace is not None:
            # A frozen trace may still be in zero span even when the current measurement is swept.
            require_active_trace(trace)
        self._check_error_reply(ask("error_queue"))
        if normal_view is not None and trace is not None:
            self._send_command(normal_view, skip_check=True)
            self._check_error_reply(ask("error_queue"))
            require_span()
            require_active_trace(trace)
            self._check_error_reply(ask("error_queue"))

    def _marker_commands(
        self, operation: str, marker: int, channel: int, *, frequency_hz: float | None = None
    ) -> dict[str, str]:
        if not self.supports_operation(operation):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement {operation}."
            )
        self._require_int("Marker index", marker)
        self._require_int("Trace index", channel)
        # Delta has two public marker and coordinate inputs but uses the same private bindings.
        binding_operation = "set_marker" if operation == "measure_marker_delta" else operation
        arguments: dict[str, object] = {"marker": marker, "channel": channel}
        positioned = operation != "find_marker_peak"
        if positioned:
            arguments["frequency_hz"] = frequency_hz
        args = self._bound_arguments(binding_operation, arguments)
        binding = self.config.operation_options.operations[binding_operation]
        queries = {"frequency", "amplitude"}
        keys = ["activate", "assign", "frequency", "amplitude"]
        if self.config.markers == "keysight":
            keys.extend(("disable_function", "frequency_readout"))
        keys += ["position"] if positioned else ["peak", "next"]
        return {
            key: self._single_command(
                binding_operation, key, query=key in queries, args=args.get(binding.transport[key])
            )
            for key in keys
        }

    def _position_marker(
        self,
        operation: str,
        marker: int,
        channel: int,
        plan: Mapping[str, str],
        *,
        action: Literal["position", "peak", "next"],
    ) -> SpectrumMarker:
        setup = ("activate", "assign", "disable_function", "frequency_readout")
        error = self._single_command(operation, "error_queue", query=True)

        def write(key: str) -> None:
            self._send_command(plan[key], skip_check=True)
            self._check_error_reply(self._query(error, skip_check=True))

        def position() -> float:
            return self._scalar("marker frequency", self._query(plan["frequency"], skip_check=True))

        for setting in setup:
            if setting in plan:
                write(setting)
        before = position() if action == "next" else None
        write(action)
        after = position()
        if after < 0:
            raise InstrumentDataError(self.config.model, "Invalid marker frequency.")
        if before == after:
            raise InstrumentDataError(self.config.model, "No distinct marker peak was found.")
        amplitude = self._scalar(
            "marker amplitude", self._query(plan["amplitude"], skip_check=True)
        )
        self._check_error_reply(self._query(error, skip_check=True))
        return SpectrumMarker(
            marker,
            channel,
            after,
            amplitude,
            instrument=self.config.model,
            readout_timestamp=time(),
        )

    def _settings_plan(
        self,
        operation: str,
        changes: Mapping[str, object],
        *,
        selectors: Mapping[str, object] | None = None,
    ) -> list[str]:
        if not self.supports_operation(operation):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement {operation}."
            )
        supplied = {key: value for key, value in changes.items() if value is not None}
        if not supplied:
            if selectors:
                for key, value in selectors.items():
                    self._resolve_operation_parameter(operation, key, value)
            return []
        resolved = self._bound_arguments(operation, {**(selectors or {}), **supplied})
        spec = self.config.operation_options.operations[operation]
        aliases = {
            spec.transport[binding.alias]: binding.alias
            for key in supplied
            for binding in spec.parameters[key].bindings
        }
        # Selector bindings also resolve unrequested commands; execute only requested changes.
        return [
            self._single_command(operation, alias, args=resolved[private])
            for private, alias in aliases.items()
        ]

    def _bound_arguments(
        self, operation: str, values: Mapping[str, object]
    ) -> dict[str, dict[str, object]]:
        spec = self.config.operation_options.operations[operation]
        result: dict[str, dict[str, object]] = {}
        for key, value in values.items():
            resolved = self._resolve_operation_parameter(operation, key, value)
            for binding in spec.parameters[key].bindings:
                private = spec.transport[binding.alias]
                result.setdefault(private, {})[binding.parameter] = resolved.transport_value
        return result

    def _write_setup(self, plan: list[str]) -> None:
        error = self._single_command("acquire_trace", "error_queue", query=True)
        for command in plan:
            self._send_command(command, skip_check=True)
            self._check_error_reply(self._query(error, skip_check=True))

    def _check_setup_errors(self, operation: str) -> None:
        command = self._single_command(operation, "error_queue", query=True)
        self._check_error_reply(self._query(command, skip_check=True))

    def _check_standard_mode(self, operation: str) -> None:
        command = self._single_command(operation, "trace_mode", query=True)
        self._check_mode(self._query(command, skip_check=True))

    def _setup_guard(self) -> None:
        spec = self.config.single_sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Missing passive sweep safeguards."
            )
        keys = ("trace_mode", "source_mode", "error_queue")
        if spec.sweep_guard == "sweep_count":
            keys += ("source_options", "sequencer")
        state = self._query_plan("acquire_trace", keys)

        def ask(key: str) -> str:
            return self._query(state[key], skip_check=True)

        self._check_error_reply(ask("error_queue"))
        self._check_mode(ask("trace_mode"))
        self._check_passive(ask, state)
        self._check_error_reply(ask("error_queue"))

    def _require_dbm(self, reply: str) -> None:
        if self._amplitude_unit(reply) != "dBm":
            raise InstrumentDataError(
                self.config.model, "Set the analyzer amplitude scale to dBm first."
            )

    def _rf_state(self, operation: str, keys: tuple[str, ...]) -> dict[str, str]:
        keys += ("preamp_options",)
        if self.config.rf_input is not None and self.config.rf_input.external_frontend_option:
            keys += ("frontend",)
        return self._query_plan(operation, keys)

    def _read_rf_options(self, state: Mapping[str, str]) -> set[str]:
        raw = self._query(state["preamp_options"], skip_check=True)
        options = {self._token(option) for option in raw.split(",")}
        if not options or not all(option.replace("-", "").isalnum() for option in options):
            raise InstrumentDataError(
                self.config.model, "Cannot verify installed spectrum options."
            )
        spec = self.config.rf_input
        if (
            spec is not None
            and spec.external_frontend_option in options
            and self._is_on(self._query(state["frontend"], skip_check=True))
        ):
            raise InstrumentDataError(
                self.config.model,
                "Disable external RF frontend before using this RF input operation.",
            )
        return options

    def _require_log_scale(self, reply: str) -> None:
        if self._token(reply) not in {"LOG", "LOGARITHMIC"}:
            raise InstrumentDataError(self.config.model, "Select a logarithmic dBm scale.")

    def _preamp_installed(self, options: set[str]) -> bool:
        spec = self.config.rf_input
        return spec is not None and not options.isdisjoint(spec.preamp_options)

    def _timing_modes(self, state: Mapping[str, str]) -> tuple[bool, bool]:
        span = self._scalar("span", self._query(state["span"], skip_check=True))
        if span < 0:
            raise InstrumentDataError(self.config.model, "Instrument reported negative span.")
        if self.config.sweep_control == "keysight":
            if span == 0:
                return False, True
            mode = self._token(self._query(state["sweep_type"], skip_check=True))
            if mode not in {"FFT", "SWE", "SWEEP"}:
                raise InstrumentDataError(self.config.model, "Unknown Keysight sweep type.")
            return mode != "FFT", mode != "FFT"
        return True, True

    def _read_setting(self, operation: str, setting: str, raw: str) -> str:
        spec = self.config.operation_options.operations[operation].parameters[setting]
        token = self._token(raw)
        for option in spec.options:
            options = {self._token(alias) for alias in option.aliases}
            if isinstance(option.transport, OperationTransportSpec):
                options.add(self._token(str(option.transport.value)))
            if token in options:
                return str(option.value)
        raise InstrumentDataError(self.config.model, f"Unsupported spectrum {setting}: {token!r}.")

    def _trace_mode(self, raw: str) -> SpectrumTraceMode:
        return cast(SpectrumTraceMode, self._read_setting("configure_trace", "mode", raw))

    def _native_count(self, raw: str) -> int:
        count = self._scalar("accumulation count", raw)
        if count != int(count) or not 0 <= count <= 200_000:
            raise InstrumentDataError(self.config.model, "Invalid spectrum accumulation count.")
        return int(count)

    def _require_optional_bool(self, name: str, value: bool | None) -> None:
        if value is not None and type(value) is not bool:
            raise InstrumentConfigurationError(self.config.model, f"{name} must be a bool.")

    def _require_int(self, name: str, value: int) -> None:
        if type(value) is not int:
            raise InstrumentConfigurationError(self.config.model, f"{name} must be an integer.")

    def get_sweep_settings(self) -> SpectrumSweepSettings:
        """Read settings from an instrument already in standard spectrum mode."""
        if self.config.trace_readback is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement sweep settings readback."
            )
        keys = ("trace_mode", "center", "trace_span", "rbw", "vbw", "trace_points", "trace_unit")
        plan = self._query_plan("get_sweep_settings", keys)
        with self._spectrum_transaction():
            self._check_mode(self._query(plan["trace_mode"], skip_check=True))
            values = {
                key: self._query(plan[key], skip_check=True) for key in keys if key != "trace_mode"
            }
        center, span, rbw, vbw = (
            self._scalar(key, values[key]) for key in ("center", "trace_span", "rbw", "vbw")
        )
        if center < 0 or span < 0 or rbw <= 0 or vbw <= 0:
            raise InstrumentDataError(
                self.config.model, "Instrument reported invalid sweep settings."
            )
        return SpectrumSweepSettings(
            center,
            span,
            rbw,
            vbw,
            self._point_count(values["trace_points"]),
            self._amplitude_unit(values["trace_unit"]),
        )

    def get_trace(self, channel: int = 1) -> SpectrumTrace:
        """Read an existing held trace without starting a measurement.

        The channel argument is the display trace index, not an RF input.
        Requires a standard spectrum measurement, continuous sweep off, and
        ASCII transfer. The data may be stale, averaged, or held.
        """
        plan = self._trace_plan(channel)

        def ask(key: str) -> str:
            return self._query(plan[key], skip_check=True)

        with self._spectrum_transaction():
            self._check_mode(ask("trace_mode"))
            self._check_held(ask("trace_continuous"))
            self._check_completion(ask("trace_complete"))
            self._check_format(ask("trace_format"))
            return self._read_trace(channel, ask, acquisition="held")

    def acquire_trace(
        self,
        channel: int = 1,
        *,
        timeout_ms: int = 10_000,
        accumulation_count: int | None = None,
    ) -> SpectrumTrace:
        """Acquire a passive sweep or an explicitly requested native sweep batch.

        By default, acquire one Clear/Write sweep. For native averaging or hold,
        first configure a matching accumulation count (at least two sweeps)
        and pass it here. INIT discards the previous accumulation on both models.
        A successful capture never mixes in an earlier run. Single sweep and
        ASCII transfer are required. On timeout, recover the instrument interface
        and open a new session; no stale data is returned.
        """
        return self._acquire_trace_set(
            (channel,), timeout_ms=timeout_ms, accumulation_count=accumulation_count
        )[0]

    def acquire_traces(
        self, channels: Sequence[int], *, timeout_ms: int = 10_000
    ) -> SpectrumTraceFrame:
        """Capture distinct active Clear/Write traces from one fresh sweep.

        Channels are display trace indexes, in return order. The analyzer is
        started once with one deadline for every read. Mismatched coordinates,
        axis types or amplitude units cause the whole frame to be rejected.
        """
        if not self.supports_operation("acquire_traces"):
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement synchronized spectrum traces."
            )
        if not isinstance(channels, Sequence) or not 2 <= len(channels) <= 6:
            raise InstrumentConfigurationError(
                self.config.model, "Choose between two and six distinct display trace indexes."
            )
        indexes = tuple(channels)
        for index in indexes:
            self._require_int("Trace index", index)
        if len(set(indexes)) != len(indexes):
            raise InstrumentConfigurationError(
                self.config.model, "Choose distinct display trace indexes."
            )
        captured = self._acquire_trace_set(indexes, timeout_ms=timeout_ms)
        first = captured[0]
        return SpectrumTraceFrame(
            captured,
            first.axis,
            first.axis_unit,
            first.amplitude_unit,
            instrument=self.config.model,
            readout_timestamp=time(),
        )

    def _acquire_trace_set(
        self,
        channels: tuple[int, ...],
        *,
        timeout_ms: int,
        accumulation_count: int | None = None,
    ) -> tuple[SpectrumTrace, ...]:
        self._validate_timeout(timeout_ms)
        spec = self.config.single_sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement single spectrum acquisition."
            )
        accumulation_query = None
        if accumulation_count is not None:
            self._require_int("Accumulation count", accumulation_count)
            self._resolve_operation_parameter(
                "acquire_trace", "accumulation_count", accumulation_count
            )
            accumulation_query = self._single_command(
                "acquire_trace", "accumulation_count", query=True
            )
        multi = len(channels) > 1
        operation = "acquire_traces" if multi else "acquire_trace"
        trace_plans = {channel: self._trace_plan(channel) for channel in channels}
        trace_plan = trace_plans[channels[0]]
        active_fsw: tuple[str, ...] = ()
        fsw_layout: dict[str, str] = {}
        if spec.sweep_guard == "active_trace_types":
            keys = ("trace_type", "trace_update", "trace_math")
            selected = {
                channel: self._query_plan("acquire_trace", keys, channel=channel)
                for channel in channels
            }
            # Keysight's average/hold count is shared across all updating
            # traces, so another active trace could cause more than one sweep.
            others = [
                self._query_plan("acquire_trace", keys, channel=index)
                for index in range(1, 7)
                if index not in channels
            ]
            state = self._query_plan(
                "acquire_trace", ("trace_mode", "source_mode", "error_queue", "normalization")
            )
            normal_view = self._single_command("acquire_trace", "normal_view")
        else:
            selected = {
                channel: self._query_plan("acquire_trace", ("trace_type",), channel=channel)
                for channel in channels
            }
            if multi:
                active_fsw = tuple(
                    self._query_plan("get_trace_settings", ("updating",), channel=channel)[
                        "updating"
                    ]
                    for channel in channels
                )
                fsw_layout = self._query_plan(
                    operation, ("operating_mode", "window_catalog", "window_type")
                )
            others = []
            normal_view = None
            state = self._query_plan(
                "acquire_trace",
                (
                    "trace_mode",
                    "source_options",
                    "source_mode",
                    "error_queue",
                    "sequencer",
                    "sweep_count",
                    "trace_math",
                ),
            )
        initiate = self._single_command(operation, "initiate")
        with self._spectrum_transaction():
            query, send = self._bounded_exchange(operation, timeout_ms)

            def ask(key: str) -> str:
                return query(trace_plan[key])

            self._check_error_reply(query(state["error_queue"]))
            self._check_mode(ask("trace_mode"))
            if fsw_layout:
                self._require_fsw_capture_layout(query, fsw_layout)
            self._check_held(ask("trace_continuous"))
            self._check_format(ask("trace_format"))
            preflight_metadata = self._trace_metadata(ask)
            self._check_passive(lambda key: query(state[key]), state)
            if spec.sweep_guard == "active_trace_types":
                self._check_keysight_trace(query, state, tuple(selected.values()), others)
            else:
                if accumulation_count is None and self._scalar(
                    "sweep count", query(state["sweep_count"])
                ) not in {0, 1}:
                    raise InstrumentDataError(
                        self.config.model, "Set sweep count to 0 or 1 for a single sweep."
                    )
                if self._is_on(query(state["trace_math"])):
                    raise InstrumentDataError(
                        self.config.model, "Disable FSW trace math before sweeping."
                    )

            def require_active_fsw() -> None:
                if any(not self._is_on(query(command)) for command in active_fsw):
                    raise InstrumentDataError(
                        self.config.model, "Every selected FSW display trace must be enabled."
                    )

            def check_trace_mode(plan: Mapping[str, str]) -> SpectrumTraceMode:
                reply = query(plan["trace_type"])
                if accumulation_query is None:
                    if not self._is_write(reply):
                        raise InstrumentDataError(
                            self.config.model, "Select an updating Clear/Write trace."
                        )
                    return "clear_write"
                mode = self._trace_mode(reply)
                if mode not in _ACCUMULATING_MODES:
                    raise InstrumentDataError(
                        self.config.model,
                        "Select an updating Average, Max Hold, or Min Hold trace.",
                    )
                if self._native_count(query(accumulation_query)) != accumulation_count:
                    raise InstrumentDataError(
                        self.config.model,
                        "Native spectrum accumulation count does not match the request.",
                    )
                return mode

            require_active_fsw()
            trace_modes = {index: check_trace_mode(plan) for index, plan in selected.items()}
            self._check_error_reply(query(state["error_queue"]))
            if normal_view is not None:
                # Spectrogram could otherwise return a historical Trace 1. The
                # N9000A manual documents a setter, not a reliable view query.
                send(normal_view)
                self._check_keysight_trace(query, state, tuple(selected.values()), others)
                trace_modes = {index: check_trace_mode(plan) for index, plan in selected.items()}
                self._check_error_reply(query(state["error_queue"]))
            send(initiate)
            self._check_completion(ask("trace_complete"))
            self._check_error_reply(query(state["error_queue"]))
            if multi:
                self._check_mode(ask("trace_mode"))
                if fsw_layout:
                    self._require_fsw_capture_layout(query, fsw_layout)
                self._check_held(ask("trace_continuous"))
                self._check_format(ask("trace_format"))
                if self._trace_metadata(ask) != preflight_metadata:
                    raise InstrumentDataError(
                        self.config.model, "Spectrum trace metadata changed during the sweep."
                    )
                if spec.sweep_guard == "active_trace_types":
                    self._check_keysight_trace(query, state, tuple(selected.values()), others)
                else:
                    require_active_fsw()
                    if self._is_on(query(state["trace_math"])):
                        raise InstrumentDataError(
                            self.config.model, "FSW trace math changed during the sweep."
                        )
                if any(
                    check_trace_mode(plan) != trace_modes[index] for index, plan in selected.items()
                ):
                    raise InstrumentDataError(
                        self.config.model, "Spectrum trace mode changed during the sweep."
                    )
                self._check_error_reply(query(state["error_queue"]))

            def read(index: int) -> SpectrumTrace:
                return self._read_trace(
                    index,
                    lambda key: query(trace_plans[index][key]),
                    acquisition="fresh",
                    sweep_count=accumulation_count or 1,
                    trace_mode=trace_modes[index],
                    expected_metadata=preflight_metadata if multi else None,
                )

            first = read(channels[0])
            traces = [first]
            for index in channels[1:]:
                trace = read(index)
                if (
                    trace.axis != first.axis
                    or trace.axis_kind != first.axis_kind
                    or trace.amplitude_unit != first.amplitude_unit
                ):
                    raise InstrumentDataError(
                        self.config.model,
                        "Spectrum traces do not share the same coordinates and units.",
                    )
                traces.append(trace)
            self._check_error_reply(query(state["error_queue"]))
            return tuple(traces)

    def _require_fsw_capture_layout(
        self, query: Callable[[str], str], plan: Mapping[str, str]
    ) -> None:
        self._check_mode(query(plan["operating_mode"]))
        catalog = query(plan["window_catalog"]).strip()
        # The SCPI catalog is a sequence of quoted window-name/index pairs.
        single_window_one = r"""(?:'(?:[^']|'')*'|"(?:[^"]|"")*")\s*,\s*1"""
        if fullmatch(single_window_one, catalog) is None:
            raise InstrumentDataError(
                self.config.model,
                "FSW spectrum capture requires exactly one display window at index 1.",
            )
        if self._token(query(plan["window_type"])) not in {"DIAG", "DIAGRAM"}:
            raise InstrumentDataError(
                self.config.model,
                "FSW spectrum capture requires a frequency or time Diagram window.",
            )

    def _validate_timeout(self, timeout_ms: int) -> None:
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 3_600_000:
            raise InstrumentConfigurationError(
                self.config.model, "timeout_ms must be an integer between 1 and 3600000."
            )

    def _bounded_exchange(
        self, operation: str, timeout_ms: int
    ) -> tuple[Callable[[str], str], Callable[[str], None]]:
        self._ensure_backend_connected()
        deadline = monotonic() + timeout_ms / 1_000

        def remaining() -> int:
            seconds = deadline - monotonic()
            if seconds <= 0:
                raise InstrumentCommunicationError(
                    self.config.model, operation, "Spectrum acquisition timed out."
                )
            return min(timeout_ms, ceil(seconds * 1_000))

        def query(command: str) -> str:
            reply = self._query(command, skip_check=True, timeout_ms=remaining())
            remaining()  # A backend may return after its configured timeout.
            return reply

        def send(command: str) -> None:
            self._send_command(command, skip_check=True, timeout_ms=remaining())
            remaining()

        return query, send

    @contextmanager
    def _spectrum_transaction(self) -> Iterator[None]:
        with self._profile_transaction():
            if self._spectrum_session_uncertain:
                raise InstrumentCommunicationError(
                    self.config.model,
                    message=(
                        "Spectrum session state is uncertain. Restore the standard spectrum display, "
                        "recover or clear the instrument interface, and open a new session."
                    ),
                )
            try:
                yield
            except (InstrumentCommunicationError, KeyboardInterrupt):
                # A failed send may still start a sweep; a failed query may
                # leave its reply behind. Retrying on this instance risks
                # reading that stale reply as the result of a new command.
                self._spectrum_session_uncertain = True
                raise

    def _check_passive(self, ask: Callable[[str], str], state: Mapping[str, str]) -> None:
        if "source_options" not in state:
            if self._token(ask("source_mode")) != "OFF":
                raise InstrumentDataError(
                    self.config.model,
                    "Disable analyzer source control before changing sweep settings or triggering.",
                )
            return
        options = {self._token(token) for token in ask("source_options").split(",")}
        if not options or any(
            len(opt) < 2 or opt[0] not in "BK" or not opt[1:].isdigit() for opt in options
        ):
            raise InstrumentDataError(self.config.model, "Cannot verify installed FSW options.")
        if "B10" in options and self._is_on(ask("source_mode")):
            raise InstrumentDataError(
                self.config.model, "Disable external generator control first."
            )
        if self._is_on(ask("sequencer")):
            raise InstrumentDataError(
                self.config.model, "Disable the FSW measurement sequencer first."
            )

    def _check_keysight_trace(
        self,
        query: Callable[[str], str],
        state: dict[str, str],
        selected: tuple[dict[str, str], ...],
        others: list[dict[str, str]],
    ) -> None:
        if self._is_on(query(state["normalization"])):
            raise InstrumentDataError(
                self.config.model, "Disable Keysight trace normalization before sweeping."
            )
        for plan in selected:
            if self._token(query(plan["trace_math"]).partition(",")[0]) != "OFF":
                raise InstrumentDataError(
                    self.config.model, "Disable Keysight trace math before sweeping."
                )
            if not self._is_on(query(plan["trace_update"])):
                raise InstrumentDataError(
                    self.config.model, "Selected spectrum trace is not updating."
                )
        for other in others:
            if self._is_on(query(other["trace_update"])) and not self._is_write(
                query(other["trace_type"])
            ):
                raise InstrumentDataError(
                    self.config.model, "An active averaged or held trace prevents a single sweep."
                )

    def _query_plan(
        self, operation_id: str, keys: tuple[str, ...], *, channel: int | None = None
    ) -> dict[str, str]:
        operation = self.config.operation_options.operations.get(operation_id)
        if operation is None:
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement {operation_id}."
            )
        params: dict[str, dict[str, object]] = {}
        if channel is not None:
            if type(channel) is not int:
                raise InstrumentConfigurationError(
                    self.config.model, "Trace index must be an integer."
                )
            selector = self._resolve_operation_parameter(operation_id, "channel", channel)
            for binding in operation.parameters["channel"].bindings:
                alias = operation.transport[binding.alias]
                params.setdefault(alias, {})[binding.parameter] = selector.transport_value
        plan = {}
        for key in keys:
            alias = operation.transport.get(key)
            if alias is None:
                raise InstrumentConfigurationError(
                    self.config.model, f"Spectrum readback is missing the '{key}' binding."
                )
            args = params.get(alias, {})
            if (
                channel is not None
                and key
                in {
                    "trace_data",
                    "trace_axis",
                    "trace_type",
                    "trace_update",
                    "trace_math",
                    "detector",
                    "detector_auto",
                    "updating",
                }
                and not args
            ):
                raise InstrumentConfigurationError(
                    self.config.model, f"Spectrum readback '{key}' must bind the trace index."
                )
            plan[key] = self._single_command(operation_id, key, query=True, args=args)
        return plan

    def _single_command(
        self,
        operation_id: str,
        key: str,
        *,
        query: bool = False,
        args: Mapping[str, object] | None = None,
    ) -> str:
        operation = self.config.operation_options.operations.get(operation_id)
        alias = operation.transport.get(key) if operation is not None else None
        if alias is None:
            raise InstrumentConfigurationError(
                self.config.model, f"Spectrum operation is missing the '{key}' binding."
            )
        commands = self._build_profile_alias(alias, **(args or {}))
        response = self._scpi_engine.describe(alias).get("response") or {}
        if (
            len(commands) != 1
            or any(char in commands[0] for char in ";\r\n")
            or not commands[0].strip()
            or commands[0].split(maxsplit=1)[0].endswith("?") != query
            or (query and response.get("transport", "query") != "query")
        ):
            kind = "text query" if query else "write"
            raise InstrumentConfigurationError(
                self.config.model, f"'{key}' must be a single {kind}."
            )
        return commands[0]

    def _trace_plan(self, channel: int) -> dict[str, str]:
        spec = self.config.trace_readback
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement spectrum trace readback."
            )
        keys = (
            "trace_mode",
            "trace_continuous",
            "trace_complete",
            "trace_format",
            "trace_span",
            "trace_points",
            "trace_unit",
            "trace_data",
        )
        if spec.layout == "split_xy":
            keys += ("trace_axis",)
        return self._query_plan("get_trace", keys, channel=channel)

    def _read_trace(
        self,
        channel: int,
        ask: Callable[[str], str],
        *,
        acquisition: Literal["held", "fresh"],
        sweep_count: int | None = None,
        trace_mode: SpectrumTraceMode | None = None,
        expected_metadata: tuple[float, int, str] | None = None,
    ) -> SpectrumTrace:
        spec = self.config.trace_readback
        assert spec is not None  # _trace_plan() verified capability before I/O.
        metadata = self._trace_metadata(ask)
        if expected_metadata is not None and metadata != expected_metadata:
            raise InstrumentDataError(
                self.config.model, "Spectrum trace metadata changed before transfer."
            )
        span, count, unit = metadata
        if spec.layout == "interleaved_xy":
            data = self._parse_trace_values(ask("trace_data"), 2 * count)
            axis, amplitudes = data[0::2], data[1::2]
        else:
            axis = self._parse_trace_values(ask("trace_axis"), count)
            amplitudes = self._parse_trace_values(ask("trace_data"), count)

        if any(left >= right for left, right in zip(axis, axis[1:], strict=False)):
            raise InstrumentDataError(self.config.model, "Trace coordinates are not increasing.")
        return SpectrumTrace(
            trace=channel,
            axis=axis,
            amplitudes=amplitudes,
            axis_kind="time" if span == 0 else "frequency",
            amplitude_unit=unit,
            acquisition=acquisition,
            sweep_count=sweep_count,
            trace_mode=trace_mode,
            instrument=self.config.model,
            readout_timestamp=time(),
        )

    def _trace_metadata(self, ask: Callable[[str], str]) -> tuple[float, int, str]:
        span = self._scalar("span", ask("trace_span"))
        if span < 0:
            raise InstrumentDataError(self.config.model, "Instrument reported negative span.")
        return span, self._point_count(ask("trace_points")), self._amplitude_unit(ask("trace_unit"))

    @staticmethod
    def _token(raw: str) -> str:
        return raw.strip().strip("\"'").strip().upper()

    def _is_on(self, raw: str) -> bool:
        token = self._token(raw)
        if token not in {"0", "OFF", "1", "ON"}:
            raise InstrumentDataError(self.config.model, f"Unexpected spectrum state {token!r}.")
        return token in {"1", "ON"}

    def _is_write(self, raw: str) -> bool:
        return self._token(raw) in {"WRIT", "WRITE"}

    def _check_mode(self, raw: str) -> None:
        spec = self.config.trace_readback
        if spec is None or self._token(raw) not in {value.upper() for value in spec.mode_values}:
            raise InstrumentDataError(self.config.model, "Expected standard spectrum mode.")

    def _check_held(self, raw: str) -> None:
        if self._is_on(raw):
            raise InstrumentDataError(
                self.config.model,
                "Turn continuous sweep off before spectrum trace acquisition or readback.",
            )

    def _check_format(self, raw: str) -> None:
        if self._token(raw.partition(",")[0]) not in {"ASC", "ASCII"}:
            raise InstrumentDataError(
                self.config.model, "Spectrum readback requires ASCII transfer format."
            )

    def _check_completion(self, raw: str) -> None:
        if raw.strip() != "1":
            self._spectrum_session_uncertain = True
            raise InstrumentDataError(self.config.model, "Sweep completion was not confirmed.")

    def _check_error_reply(self, raw: str) -> None:
        try:
            code = int(raw.partition(",")[0])
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model, "Invalid spectrum error-queue reply."
            ) from exc
        if code:
            raise InstrumentDataError(
                self.config.model, f"Spectrum analyzer reported an error: {raw}"
            )

    def _point_count(self, raw: str) -> int:
        spec = self.config.trace_readback
        assert spec is not None
        points = self._scalar("point count", raw)
        if not 1 <= points <= spec.max_points or points != int(points):
            raise InstrumentDataError(self.config.model, "Instrument reported invalid trace size.")
        return int(points)

    def _amplitude_unit(self, raw: str) -> str:
        token = self._token(raw)
        if token not in _AMPLITUDE_UNITS:
            raise InstrumentDataError(
                self.config.model, f"Unsupported spectrum amplitude unit {token!r}."
            )
        return _AMPLITUDE_UNITS[token]

    def _scalar(self, field: str, raw: str) -> float:
        try:
            value = float(raw)
        except ValueError as exc:
            raise InstrumentDataError(self.config.model, f"Invalid spectrum {field}.") from exc
        # Some instruments emit a large finite numeric sentinel in place of NaN.
        if not isfinite(value) or abs(value) >= 9.9e37:
            raise InstrumentDataError(self.config.model, f"Invalid spectrum {field}.")
        return value

    def _parse_trace_values(self, raw: str, count: int) -> tuple[float, ...]:
        # Count first, so truncated and unexpectedly large transfers cannot
        # produce partial results or create a large number of float objects.
        if not raw.strip() or raw.count(",") + 1 != count:
            raise InstrumentDataError(
                self.config.model, f"Expected {count} values in spectrum trace response."
            )
        return tuple(self._scalar("trace sample", field) for field in raw.split(","))
