from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from csv import Error as CSVError
from csv import reader as csv_reader
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from math import ceil
from math import isclose
from math import isfinite
from math import log10
from math import remainder
from struct import iter_unpack
from threading import get_ident
from time import monotonic
from time import sleep
from typing import Any
from typing import Literal
from typing import cast

import polars as pl

from ..config.power_meter_config import PowerMeterConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ..experiments.results import MeasurementResult
from ..experiments.results import NativeMeasurementResult
from ._power_uncertainty import PowerCWConditions
from ._power_uncertainty import cw_accuracy
from ._power_uncertainty import reported_reflection_uncertainty
from .instrument import Instrument
from .operation_contract import OperationDescriptor
from .operation_contract import ResolvedOperationParameter
from .scpi_binary import BinaryBlockParseError
from .scpi_binary import strip_definite_length_block
from .self_test import InstrumentSelfTestResult

ScalarPowerMode = Literal["average", "gated_average", "pulse_average", "peak", "random_sample"]
PowerMode = ScalarPowerMode | Literal["buffered_average"]
PowerTrigger = Literal["immediate", "internal", "external", "external_1", "external_2"]
PowerTriggerEdge = Literal["rising", "falling"]
PowerAveraging = Literal["manual", "automatic", "disabled"]
PowerZeroMode = Literal["internal", "external"]
TraceTrigger = Literal["external", "internal"]
PowerTraceResolution = Literal["high", "medium", "low"]
PowerUnit = Literal["dBm", "W", "mW", "uW"]
_WATT_SCALES = {"W": 1.0, "mW": 1e-3, "uW": 1e-6}
_OFF = {"OFF", "0", "+0"}
_ON = {"ON", "1", "+1"}
_KEYSIGHT_IDENTITY_NAMES = frozenset({"keysight technologies", "agilent technologies"})
_RS_IDENTITY_NAMES = frozenset({"rohde & schwarz", "rohde&schwarz"})
_TRIGGER_TOKENS: dict[str, PowerTrigger] = {
    "IMM": "immediate",
    "IMMEDIATE": "immediate",
    "INT": "internal",
    "INTERNAL": "internal",
    "INT1": "internal",
    "INTERNAL1": "internal",
    "EXT": "external",
    "EXTERNAL": "external",
    "EXT1": "external_1",
    "EXTERNAL1": "external_1",
    "EXT2": "external_2",
    "EXTERNAL2": "external_2",
}
_EDGE_TOKENS: dict[str, PowerTriggerEdge] = {
    "POS": "rising",
    "POSITIVE": "rising",
    "NEG": "falling",
    "NEGATIVE": "falling",
}
_UNIT_TOKENS: dict[str, PowerUnit] = {"DBM": "dBm", "W": "W", "MW": "mW", "UW": "uW"}


def _power_result(
    values: float | pl.DataFrame,
    *,
    instrument: str,
    unit: str,
    kind: str,
    received: datetime | None = None,
    envelope: dict[str, Any],
    result_type: type[MeasurementResult] = MeasurementResult,
) -> MeasurementResult:
    return result_type(
        values=values,
        instrument=instrument,
        units=unit,
        measurement_type=kind,
        timestamp=received.timestamp() if received is not None else None,
        envelope={
            "uncertainty_status": "not_evaluated",
            "timestamp_kind": "host_receipt" if received is not None else "conversion",
            **envelope,
        },
    )


def _power_sample_table(values: tuple[float, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        {"sample_index": range(len(values)), "power": values},
        schema={"sample_index": pl.Int64, "power": pl.Float64},
    )


@dataclass(frozen=True)
class PowerReading:
    """One completed power acquisition, with its actual compensation setting."""

    value: float
    unit: PowerUnit
    channel: int
    correction_frequency_hz: float
    _model: str | None = field(default=None, kw_only=True, repr=False, compare=False)
    _receipt: datetime | None = field(default=None, kw_only=True, repr=False, compare=False)

    def to_measurement_result(self, *, instrument: str | None = None) -> MeasurementResult:
        """Return the nominal scalar in its reported unit without adding an accuracy model."""
        return _power_result(
            self.value,
            instrument=instrument or self._model or "power_meter",
            unit=self.unit,
            kind="rf_power",
            received=self._receipt,
            envelope={
                "channel": self.channel,
                "correction_frequency_hz": self.correction_frequency_hz,
            },
        )


@dataclass(frozen=True)
class PowerSettings:
    """Live sensor configuration for an absolute average-power workflow."""

    model: str
    channel: int
    mode: PowerMode
    correction_frequency_hz: float
    averaging_count: int
    native_unit: PowerUnit
    detector: str
    feed: str
    trigger_source: PowerTrigger
    aperture_s: float | None = None
    gate_offset_s: float | None = None
    gate_duration_s: float | None = None
    trigger_edge: PowerTriggerEdge | None = None
    averaging_mode: PowerAveraging = "manual"
    sample_count: int = 1
    duty_cycle_percent: float | None = None
    trigger_level_dbm: float | None = None
    trigger_delay_s: float | None = None

    @property
    def gate_window_s(self) -> tuple[float, float] | None:
        """Gate bounds in seconds relative to the detected edge, when applicable."""
        if self.gate_offset_s is None or self.gate_duration_s is None:
            return None
        start = (self.trigger_delay_s or 0.0) + self.gate_offset_s
        return start, start + self.gate_duration_s


@dataclass(frozen=True)
class PowerAcquisition(PowerReading):
    """Fresh reading and its sensor settings; timestamp is host receipt time."""

    settings: PowerSettings
    received_at_utc: datetime

    def to_measurement_result(
        self, *, instrument: str | None = None, cw_conditions: PowerCWConditions | None = None
    ) -> MeasurementResult:
        """Return the fresh scalar, optionally with a conditional CW datasheet term.

        The nominal value and unit are unchanged. Unsupported conditions leave
        the result nominal and explain why no accuracy term was attached.
        """
        return _power_result(
            self.value,
            instrument=instrument or self.settings.model,
            unit=self.unit,
            kind="rf_power",
            received=self.received_at_utc,
            result_type=NativeMeasurementResult if cw_conditions is not None else MeasurementResult,
            envelope={
                "channel": self.channel,
                "correction_frequency_hz": self.correction_frequency_hz,
                "acquisition": "fresh",
                "settings": asdict(self.settings),
                **(cw_accuracy(self, cw_conditions) if cw_conditions is not None else {}),
            },
        )


@dataclass(frozen=True)
class PowerBuffer:
    """Ordered hardware-buffered average-power results with no invented time axis."""

    values: tuple[float, ...]
    unit: PowerUnit
    settings: PowerSettings
    received_at_utc: datetime

    def to_measurement_result(self, *, instrument: str | None = None) -> MeasurementResult:
        """Return an indexed power table without assigning sample times."""
        return _power_result(
            _power_sample_table(self.values),
            instrument=instrument or self.settings.model,
            unit=self.unit,
            kind="rf_power_buffer",
            received=self.received_at_utc,
            envelope={
                "acquisition": "fresh",
                "settings": asdict(self.settings),
                "column_units": {"sample_index": "1", "power": self.unit},
            },
        )


class ArmedPowerCapture:
    """One ready, externally triggered power acquisition owned by its context."""

    def __init__(
        self,
        settings: PowerSettings,
        ready_at_utc: datetime,
        finish: Callable[[], PowerAcquisition | PowerBuffer],
    ) -> None:
        self.settings = settings
        self.ready_at_utc = ready_at_utc
        self._finish = finish
        self._owner = get_ident()
        self._used = False
        self._closed = False
        self._needs_abort = True

    def fetch(self) -> PowerAcquisition | PowerBuffer:
        """Wait for and read this acquisition once; never rearm or retry it."""
        if get_ident() != self._owner:
            raise RuntimeError("Fetch must run on the thread that owns the power-arm context.")
        if self._closed or self._used:
            raise RuntimeError("This armed power capture is no longer available.")
        self._used = True
        return self._finish()


@dataclass(frozen=True)
class PowerTraceSettings:
    """Live trigger-referenced RF envelope capture settings."""

    model: str
    channel: int
    correction_frequency_hz: float
    native_unit: Literal["dBm", "W"]
    trigger_source: TraceTrigger
    trigger_edge: PowerTriggerEdge
    trigger_level_dbm: float | None
    offset_s: float
    duration_s: float
    trigger_delay_s: float = 0.0

    @property
    def time_window_s(self) -> tuple[float, float]:
        """Capture window bounds in seconds relative to the trigger edge."""
        start = self.trigger_delay_s + self.offset_s
        return start, start + self.duration_s


@dataclass(frozen=True)
class PowerTrace:
    """Ordered power envelope samples. The time window is verified, not a per-point clock."""

    values: tuple[float, ...]
    unit: PowerUnit
    resolution: PowerTraceResolution
    settings: PowerTraceSettings
    received_at_utc: datetime

    @property
    def sampled_peak(self) -> float:
        """Maximum returned sample, not a guaranteed peak of the RF pulse."""
        return max(self.values)

    def to_measurement_result(self, *, instrument: str | None = None) -> MeasurementResult:
        """Return an indexed trace, retaining the verified window but no sample clock."""
        return _power_result(
            _power_sample_table(self.values),
            instrument=instrument or self.settings.model,
            unit=self.unit,
            kind="rf_power_trace",
            received=self.received_at_utc,
            envelope={
                "acquisition": "fresh",
                "settings": asdict(self.settings),
                "resolution": self.resolution,
                "time_window_s": list(self.settings.time_window_s),
                "column_units": {"sample_index": "1", "power": self.unit},
            },
        )


@dataclass(frozen=True)
class _PowerIO:
    query: Callable[[str], str]
    send: Callable[[str], None]
    pending: Callable[[bool], None]
    query_raw: Callable[[str], bytes]
    remaining: Callable[[], int]
    recover_if_uncertain: Callable[[BaseException], None]


@dataclass(frozen=True)
class PowerCorrections:
    """Live native correction settings, not an estimate of total applied correction."""

    correction_frequency_hz: float
    fixed_offset_enabled: bool
    fixed_offset_db: float
    duty_cycle_enabled: bool
    duty_cycle_percent: float
    frequency_table_enabled: bool | None = None
    frequency_table_name: str | None = None
    s_parameter_enabled: bool | None = None
    s_parameter_set: int | None = None


@dataclass(frozen=True)
class PowerFixedOffset:
    """The native signed setpoint, retained while the sensor's correction is disabled."""

    enabled: bool
    offset_db: float


@dataclass(frozen=True)
class PowerSParameterCorrection:
    """Selection of an already-installed S-parameter correction data set."""

    enabled: bool
    data_set: int


@dataclass(frozen=True)
class PowerSourceReflectionCorrection:
    """Source reflection coefficient used by the sensor's mismatch correction."""

    enabled: bool
    magnitude: float
    phase_deg: float


@dataclass(frozen=True)
class PowerInputReflection:
    """Native input-plane reflection coefficient and expanded magnitude uncertainty."""

    frequency_hz: float
    magnitude: float
    phase_deg: float
    expanded_magnitude_uncertainty: float
    reference_plane: Literal["sensor_input", "s_parameter_device_input"]
    s_parameter_set: int | None
    uncertainty_coverage_factor: Literal[2] = 2
    _model: str | None = field(default=None, kw_only=True, repr=False, compare=False)
    _receipt: datetime | None = field(default=None, kw_only=True, repr=False, compare=False)

    def to_measurement_result(self, *, instrument: str | None = None) -> MeasurementResult:
        """Preserve the reported expanded magnitude uncertainty, not a phase uncertainty."""
        frame = pl.DataFrame(
            {
                "frequency_hz": [self.frequency_hz],
                "magnitude": [self.magnitude],
                "phase_deg": [self.phase_deg],
                "expanded_magnitude_uncertainty": [self.expanded_magnitude_uncertainty],
            },
            schema={
                "frequency_hz": pl.Float64,
                "magnitude": pl.Float64,
                "phase_deg": pl.Float64,
                "expanded_magnitude_uncertainty": pl.Float64,
            },
        )
        return _power_result(
            frame,
            instrument=instrument or self._model or "power_meter",
            unit="1",
            kind="rf_power_input_reflection",
            received=self._receipt,
            envelope={
                "acquisition": "input_reflection_readback",
                "reference_plane": self.reference_plane,
                "s_parameter_set": self.s_parameter_set,
                "uncertainty_status": "instrument_reported",
                "uncertainty": reported_reflection_uncertainty(self),
                "expanded_magnitude_uncertainty_coverage_factor": self.uncertainty_coverage_factor,
                "column_units": {
                    "frequency_hz": "Hz",
                    "magnitude": "1",
                    "phase_deg": "deg",
                    "expanded_magnitude_uncertainty": "1",
                },
            },
        )


@dataclass(frozen=True)
class PowerTriggerTiming:
    """Live timing for a selected edge; optional fields are inapplicable or unsupported."""

    source: PowerTrigger | Literal["bus", "hold"]
    edge: PowerTriggerEdge | None = None
    delay_s: float | None = None
    delay_auto: bool | None = None
    holdoff_s: float | None = None
    hysteresis_db: float | None = None
    dropout_s: float | None = None


@dataclass(frozen=True)
class PowerTriggerState:
    """Non-clearing status snapshot for an acquisition or calibration in progress."""

    continuous: bool
    waiting_for_trigger: bool
    measuring: bool
    calibrating: bool

    @property
    def idle(self) -> bool:
        return not (
            self.continuous or self.waiting_for_trigger or self.measuring or self.calibrating
        )


@dataclass(frozen=True)
class PowerSensorStatus:
    """A live snapshot of non-clearing sensor condition registers."""

    manufacturer: str
    model: str
    serial_number: str
    firmware: str
    channel: int
    power_condition: int
    calibration_condition: int
    active_conditions: tuple[str, ...]

    @property
    def measurement_ok(self) -> bool:
        """No power or calibration condition was reported, including unknown bits."""
        return self.power_condition == 0 and self.calibration_condition == 0


@dataclass(frozen=True)
class PowerZeroResult:
    """A successful deliberate zero; failures raise rather than returning success."""

    channel: int
    mode: PowerZeroMode
    completed_at_utc: datetime


class PowerMeter(Instrument[PowerMeterConfig]):
    """Drives a Power Meter instrument for power measurements.

    This class provides a high-level interface for controlling a power meter,
    building upon the base `Instrument` class. It includes methods for
    configuring the power sensor and reading power values.
    """

    _power_stream_uncertain = False
    _power_arm_active = False
    _maintenance_outcome_uncertain: Literal["zero", "self-test"] | None = None

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "read_power",
            public_method="read_power",
            safety_class="read",
            group="measurements",
            scope="family",
        ),
        OperationDescriptor(
            "measure_power",
            public_method="measure_power",
            required=False,
            group="measurements",
            scope="family",
        ),
        OperationDescriptor(
            "configure_sensor",
            public_method="configure_sensor",
            required=False,
            group="setup",
            scope="family",
        ),
        OperationDescriptor("configure_power", required=False, group="setup", scope="family"),
        OperationDescriptor("acquire_power", required=False, group="measurements", scope="family"),
        OperationDescriptor(
            "read_power_settings",
            safety_class="read",
            required=False,
            group="setup",
            scope="family",
        ),
        OperationDescriptor(
            "configure_power_trace", required=False, group="capture", scope="model"
        ),
        OperationDescriptor("acquire_power_trace", required=False, group="capture", scope="model"),
        OperationDescriptor("acquire_power_buffer", required=False, group="capture", scope="model"),
        OperationDescriptor("arm_power", required=False, group="trigger", scope="model"),
        OperationDescriptor(
            "sensor_status",
            safety_class="read",
            required=False,
            group="diagnostics",
            scope="family",
        ),
        OperationDescriptor(
            "read_power_corrections",
            safety_class="read",
            required=False,
            group="correction",
            scope="family",
        ),
        OperationDescriptor(
            "configure_power_offset", required=False, group="correction", scope="family"
        ),
        OperationDescriptor(
            "configure_power_s_parameter", required=False, group="correction", scope="model"
        ),
        OperationDescriptor(
            "configure_power_source_reflection", required=False, group="correction", scope="model"
        ),
        OperationDescriptor(
            "read_power_source_reflection",
            required=False,
            safety_class="read",
            group="correction",
            scope="model",
        ),
        OperationDescriptor(
            "read_power_input_reflection",
            required=False,
            safety_class="read",
            group="correction",
            scope="model",
        ),
        OperationDescriptor(
            "read_power_trigger_state",
            safety_class="read",
            required=False,
            group="trigger",
            scope="family",
        ),
        OperationDescriptor(
            "configure_power_trigger_timing", required=False, group="trigger", scope="family"
        ),
        OperationDescriptor(
            "read_power_trigger_timing",
            safety_class="read",
            required=False,
            group="trigger",
            scope="family",
        ),
        OperationDescriptor(
            "zero_sensor",
            required=False,
            group="correction",
            scope="family",
            direct_python_only=True,
        ),
        OperationDescriptor(
            "run_self_test",
            required=False,
            group="diagnostics",
            scope="family",
            direct_python_only=True,
            direct_transport_queries=("self_test",),
        ),
    )

    def configure_power(
        self,
        channel: int = 1,
        *,
        frequency_hz: float,
        averaging_count: int | None = None,
        mode: PowerMode = "average",
        gate_offset_s: float | None = None,
        gate_duration_s: float | None = None,
        aperture_s: float | None = None,
        trigger_source: PowerTrigger | None = None,
        trigger_edge: PowerTriggerEdge | None = None,
        trigger_level_dbm: float | None = None,
        averaging_mode: PowerAveraging = "manual",
        native_unit: Literal["dBm", "W"] = "dBm",
        sample_count: int | None = None,
        duty_cycle_percent: float | None = None,
        timeout_ms: int = 5_000,
    ) -> PowerSettings:
        """Configure and verify absolute average power without resetting or zeroing.

        Fixed averaging defaults to eight measurements. A gated measurement
        requires both gate times; a buffered measurement requires a sample
        count. Pulse-average requires the known RF duty cycle in percent; it
        is not peak power. Aperture, peak, random, and trigger choices are profile-specific.
        """
        operation = "configure_power"
        channel = self._power_channel(operation, channel)
        mode = cast(PowerMode, self._resolve_operation_parameter(operation, "mode", mode).value)
        parameters: dict[str, Any] = {"channel": channel, "mode": mode}
        parameters["frequency_hz"] = parameters["frequency"] = self._resolve_operation_parameter(
            operation, "frequency_hz", frequency_hz
        ).value
        extras: list[str] = []
        spec = self.config.operation_options.operation(operation)
        assert spec is not None
        if "timeout_ms" in spec.parameters or timeout_ms != 5_000:
            timeout_ms = self._power_timeout(operation, timeout_ms)

        def resolve(name: str, value: Any, legacy: Any = None) -> ResolvedOperationParameter:
            if name not in spec.parameters and value == legacy:
                return ResolvedOperationParameter(value=value, transport_value=value)
            return self._resolve_operation_parameter(operation, name, value, context={"mode": mode})

        averaging_mode = cast(
            PowerAveraging, resolve("averaging_mode", averaging_mode, "manual").value
        )
        if averaging_mode == "manual":
            averaging_count = 8 if averaging_count is None else averaging_count
            parameters["averaging_count"] = parameters["count"] = self._resolve_operation_parameter(
                operation, "averaging_count", averaging_count
            ).value
        elif averaging_count is not None:
            raise ValueError("averaging_count is only valid with manual averaging.")

        if mode == "gated_average":
            if gate_offset_s is None or gate_duration_s is None:
                raise ValueError("Gated average requires both gate_offset_s and gate_duration_s.")
            for name, val in (
                ("gate_offset_s", gate_offset_s),
                ("gate_duration_s", gate_duration_s),
            ):
                parameters[name] = resolve(name, val).value
        elif gate_offset_s is not None or gate_duration_s is not None:
            raise ValueError("Gate times are only valid with gated_average mode.")

        if mode == "buffered_average":
            if sample_count is None:
                raise ValueError("Buffered average requires sample_count.")
            parameters["sample_count"] = resolve("sample_count", sample_count).value
        elif sample_count is not None:
            raise ValueError("sample_count is only valid with buffered_average mode.")

        if mode == "pulse_average":
            if duty_cycle_percent is None:
                raise ValueError("Pulse average requires duty_cycle_percent.")
            parameters["duty_cycle_percent"] = resolve(
                "duty_cycle_percent", duty_cycle_percent
            ).value
            extras.append("set_duty_cycle")
        elif duty_cycle_percent is not None:
            raise ValueError("duty_cycle_percent is only valid with pulse_average mode.")

        if mode in {"peak", "random_sample"}:
            extras.append("set_peak_feed" if mode == "peak" else "set_random_feed")

        default_trigger: PowerTrigger = "external" if mode == "gated_average" else "immediate"
        trigger = resolve(
            "trigger_source",
            default_trigger if trigger_source is None else trigger_source,
            default_trigger,
        )
        source = cast(PowerTrigger, trigger.value)
        if mode == "gated_average" and source not in {"external", "internal"}:
            raise ValueError("gated_average mode requires an external or internal trigger.")
        if source == "external" and mode != "gated_average":
            raise ValueError("This external trigger selection requires gated_average mode.")
        if (source == "internal") != (trigger_level_dbm is not None):
            raise ValueError("Provide trigger_level_dbm only and always for an internal trigger.")
        if (
            source == "internal"
            and mode != "gated_average"
            and "read_auto_trigger" not in spec.transport
        ):
            raise ValueError("This profile requires gated_average mode for an internal trigger.")
        edge: PowerTriggerEdge | None = None
        if source == "external_2":
            if trigger_edge is not None:
                raise ValueError("trigger_edge is not available for the EXT2 (SMB) input.")
        elif source != "immediate":
            edge_choice = resolve(
                "trigger_edge", "rising" if trigger_edge is None else trigger_edge, "rising"
            )
            edge = cast(PowerTriggerEdge, edge_choice.value)
            if source != default_trigger or edge != "rising":
                parameters["edge"] = edge_choice.transport_value
                extras.append("set_trigger_edge")
        elif trigger_edge is not None:
            raise ValueError("trigger_edge requires an internal or external trigger.")
        if source != default_trigger:
            parameters["source"] = trigger.transport_value
            # The existing external-source alias remains supported on third-party profiles.
            source_alias = (
                "set_internal_gate_trigger" if mode == "gated_average" else "set_external_trigger"
            )
            extras[:0] = [source_alias]
        if trigger_level_dbm is not None:
            level = self._resolve_operation_parameter(
                operation,
                "trigger_level_dbm",
                trigger_level_dbm,
                context={"mode": mode, "trigger_source": source},
            )
            parameters["trigger_level_dbm"] = level.value
            extras.append("set_trigger_level")
        unit = resolve("native_unit", native_unit, "dBm")
        native_unit = unit.value
        if native_unit != "dBm":
            parameters["units"] = unit.transport_value
            extras.append("set_power_units")
        if aperture_s is not None:
            parameters["aperture_s"] = resolve("aperture_s", aperture_s).value
            extras.append("set_aperture")

        setup = self._power_commands(
            operation,
            [
                f"setup_{mode}",
                "set_sensor_frequency",
                f"configure_{averaging_mode}_averaging",
                *extras,
            ],
            **parameters,
        )
        readbacks = self._power_readback(operation, mode, channel)
        error = self._power_commands(operation, ["get_error"], channel=channel)[0]
        trigger_sender = readbacks.get("read_trigger_sender") if source == "internal" else None
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            query, send = io.query, io.send
            if trigger_sender is not None:
                sender = self._power_boolean(query(trigger_sender), "trigger sender")
                if sender:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Disable the trigger sender before configuring an internal trigger.",
                    )
            for command in setup:
                send(command)
            self._require_no_power_error(query(error))
            settings = self._read_power_settings(channel, mode, readbacks, query)
            self._require_no_power_error(query(error))
            if settings.trigger_delay_s not in {None, 0.0}:
                raise InstrumentConfigurationError(
                    self.config.model, "Sensor did not reset the trigger delay to zero."
                )
            if (
                settings.native_unit,
                settings.trigger_source,
                settings.trigger_edge,
                settings.averaging_mode,
                settings.sample_count,
            ) != (native_unit, source, edge, averaging_mode, sample_count or 1):
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Sensor did not apply the requested unit, trigger, "
                    "averaging mode, or sample count.",
                )
            expected = (
                ("aperture", settings.aperture_s, aperture_s, 0.0),
                ("trigger level", settings.trigger_level_dbm, trigger_level_dbm, 0.05000001),
                ("duty cycle", settings.duty_cycle_percent, duty_cycle_percent, 0.0),
                ("correction frequency", settings.correction_frequency_hz, frequency_hz, 0.0),
                ("averaging count", settings.averaging_count, averaging_count, 0.0),
                ("gate offset", settings.gate_offset_s, gate_offset_s, 0.500001e-6),
                ("gate duration", settings.gate_duration_s, gate_duration_s, 0.500001e-6),
            )
            for name, actual, requested, tolerance in expected:
                if requested is not None and (
                    actual is None
                    or not isclose(actual, requested, rel_tol=1e-9, abs_tol=tolerance)
                ):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Sensor reported {name} {actual!r}; requested {requested!r}.",
                    )
            return settings

    def read_power_settings(
        self, channel: int = 1, *, mode: PowerMode = "average", timeout_ms: int = 2_000
    ) -> PowerSettings:
        """Check the expected workflow and return actual settings without arming it."""
        operation = "read_power_settings"
        channel = self._power_channel(operation, channel)
        timeout_ms = self._power_timeout(operation, timeout_ms)
        mode = cast(PowerMode, self._resolve_operation_parameter(operation, "mode", mode).value)
        readbacks = self._power_readback(operation, mode, channel)
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            query = io.query
            return self._read_power_settings(channel, mode, readbacks, query)

    def acquire_power(
        self,
        channel: int = 1,
        *,
        mode: ScalarPowerMode = "average",
        unit: PowerUnit = "dBm",
        timeout_ms: int = 10_000,
    ) -> PowerAcquisition:
        """Acquire one fresh scalar under a shared SCPI I/O budget."""
        settings, readings, unit, received = self._acquire_power_results(
            "acquire_power", channel, mode, unit, timeout_ms
        )
        return PowerAcquisition(
            readings[0],
            unit,
            settings.channel,
            settings.correction_frequency_hz,
            settings,
            received,
        )

    def acquire_power_buffer(
        self,
        channel: int = 1,
        *,
        unit: PowerUnit = "dBm",
        timeout_ms: int = 10_000,
    ) -> PowerBuffer:
        """Acquire the complete hardware buffer configured by ``configure_power``."""
        settings, readings, unit, received = self._acquire_power_results(
            "acquire_power_buffer", channel, "buffered_average", unit, timeout_ms
        )
        return PowerBuffer(readings, unit, settings, received)

    def _acquire_power_results(
        self, operation: str, channel: int, mode: PowerMode, unit: PowerUnit, timeout_ms: int
    ) -> tuple[PowerSettings, tuple[float, ...], PowerUnit, datetime]:
        channel = self._power_channel(operation, channel)
        if operation == "acquire_power":
            mode = cast(PowerMode, self._resolve_operation_parameter(operation, "mode", mode).value)
        unit = cast(PowerUnit, self._resolve_operation_parameter(operation, "unit", unit).value)
        timeout_ms = self._power_timeout(operation, timeout_ms)
        *prepare_fetch, fetch = self._power_commands(operation, [f"fetch_{mode}"], channel=channel)
        readbacks = self._power_readback(operation, mode, channel)
        quality, error = self._power_commands(
            operation, ["read_quality", "get_error"], channel=channel
        )
        spec = self.config.operation_options.operation(operation)
        assert spec is not None
        start = (
            self._power_commands(operation, ["start"], channel=channel)
            if "start" in spec.transport
            else []
        )
        completion = (
            self._power_commands(operation, ["opc_query"], channel=channel)[0] if start else None
        )
        count_query = (
            self._power_commands(operation, ["read_buffer_count"], channel=channel)[0]
            if mode == "buffered_average"
            else None
        )

        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            query, send, pending = io.query, io.send, io.pending
            settings = self._read_power_settings(channel, mode, readbacks, query)
            self._require_safe_power_trigger(settings, readbacks, query)
            self._require_no_power_error(query(error))
            for command in start:
                pending(True)
                send(command)
            if completion is not None:
                # An INIT error must never return the sensor's last-valid result.
                if query(completion).strip() not in {"1", "+1"}:
                    raise InstrumentDataError(
                        self.config.model, "Power acquisition did not complete."
                    )
                pending(False)
                self._require_no_power_error(query(error))
            if count_query is not None and (
                self._power_register(query(count_query), "buffer count") != settings.sample_count
            ):
                raise InstrumentDataError(
                    self.config.model, "Sensor did not fill the power buffer."
                )
            for command in prepare_fetch:
                send(command)
            pending(completion is None)
            return self._read_acquired_power(settings, unit, io, fetch, quality, error)

    def _require_safe_power_trigger(
        self, settings: PowerSettings, readbacks: dict[str, str], query: Callable[[str], str]
    ) -> None:
        if "read_trigger_sender" in readbacks and self._power_boolean(
            query(readbacks["read_trigger_sender"]), "trigger sender"
        ):
            raise InstrumentConfigurationError(
                self.config.model, "Disable the trigger sender before acquiring power."
            )
        if (
            settings.trigger_source == "immediate"
            and "read_trigger_sync" in readbacks
            and self._power_boolean(query(readbacks["read_trigger_sync"]), "trigger sync")
        ):
            raise InstrumentConfigurationError(
                self.config.model, "Disable immediate trigger sync before acquiring power."
            )

    def _read_acquired_power(
        self,
        settings: PowerSettings,
        unit: PowerUnit,
        io: _PowerIO,
        fetch: str,
        quality: str,
        error: str,
    ) -> tuple[PowerSettings, tuple[float, ...], PowerUnit, datetime]:
        response = io.query(fetch)
        io.pending(False)
        received = datetime.now(UTC)
        parts = response.split(",")
        if len(parts) != settings.sample_count:
            raise InstrumentDataError(
                self.config.model,
                f"Expected {settings.sample_count} power readings; received {len(parts)}.",
            )
        readings = tuple(self._number(part, "power reading") for part in parts)
        if settings.native_unit != "dBm" and any(value < 0 for value in readings):
            raise InstrumentDataError(self.config.model, "Negative absolute power.")
        if self._power_register(io.query(quality), "power condition"):
            raise InstrumentDataError(self.config.model, "Sensor reports questionable power data.")
        self._require_no_power_error(io.query(error))
        return (
            settings,
            tuple(self._convert_power(value, settings.native_unit, unit) for value in readings),
            unit,
            received,
        )

    @contextmanager
    def arm_power(
        self,
        channel: int = 1,
        *,
        mode: PowerMode = "average",
        unit: PowerUnit = "dBm",
        timeout_ms: int = 10_000,
    ) -> Iterator[ArmedPowerCapture]:
        """Yield after the sensor is waiting for an external trigger; fetch once inside.

        Supported profiles publish a live waiting condition, not merely acceptance
        of INIT. Use a separate source to supply the trigger. The SCPI deadline
        also counts time spent arranging that trigger inside the context,
        but does not preempt Python caller code.
        """
        op = "arm_power"
        channel = self._power_channel(op, channel)
        mode = cast(PowerMode, self._resolve_operation_parameter(op, "mode", mode).value)
        unit = cast(PowerUnit, self._resolve_operation_parameter(op, "unit", unit).value)
        timeout_ms = self._power_timeout(op, timeout_ms)
        continuous, calibrating, measuring, ready, error, abort = self._power_commands(
            op,
            [
                "read_continuous",
                "read_calibrating",
                "read_measuring",
                "read_triggering",
                "get_error",
                "abort",
            ],
            channel=channel,
        )
        capture_op = "acquire_power_buffer" if mode == "buffered_average" else "acquire_power"
        readbacks = self._power_readback(capture_op, mode, channel)
        start = self._power_commands(capture_op, ["start"], channel=channel)
        completion, quality, fetch = self._power_commands(
            capture_op, ["opc_query", "read_quality", f"fetch_{mode}"], channel=channel
        )
        count_query = (
            self._power_commands(capture_op, ["read_buffer_count"], channel=channel)[0]
            if mode == "buffered_average"
            else None
        )
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            settings = self._read_power_settings(channel, mode, readbacks, io.query)
            if settings.trigger_source not in {"external_1", "external_2"}:
                raise InstrumentConfigurationError(
                    self.config.model, "Scoped arm requires an EXT1 or EXT2 trigger."
                )
            self._require_safe_power_trigger(settings, readbacks, io.query)
            operations = (calibrating, measuring, ready)
            self._require_idle_sensor(io, continuous, operations, "Scoped arm")
            self._require_no_power_error(io.query(error))
            io.pending(True)
            for command in start:
                io.send(command)
            self._require_no_power_error(io.query(error))
            while not self._power_register(io.query(ready), "trigger condition") & 0x02:
                sleep(min(0.01, io.remaining() / 1000))

            def finish() -> PowerAcquisition | PowerBuffer:
                # An expired caller budget is not an uncertain query. Keep
                # the verified ABOR path if no acquisition I/O can be attempted.
                io.remaining()
                capture._needs_abort = False
                try:
                    io.pending(True)
                    if io.query(completion).strip() not in {"1", "+1"}:
                        raise InstrumentDataError(
                            self.config.model, "Armed power acquisition did not complete."
                        )
                    self._require_no_power_error(io.query(error))
                    # A plausible completion token must not justify reading last memory
                    # while this sensor is still measuring or waiting for another edge.
                    self._require_idle_sensor(io, continuous, operations, "Scoped fetch")
                    io.pending(False)
                    if count_query is not None and (
                        self._power_register(io.query(count_query), "buffer count")
                        != settings.sample_count
                    ):
                        raise InstrumentDataError(
                            self.config.model, "Sensor did not fill the armed power buffer."
                        )
                    _, values, converted_unit, received = self._read_acquired_power(
                        settings, unit, io, fetch, quality, error
                    )
                    if count_query is not None:
                        return PowerBuffer(values, converted_unit, settings, received)
                    return PowerAcquisition(
                        values[0],
                        converted_unit,
                        channel,
                        settings.correction_frequency_hz,
                        settings,
                        received,
                    )
                except BaseException as exc:
                    io.recover_if_uncertain(exc)
                    raise

            capture = ArmedPowerCapture(settings, datetime.now(UTC), finish)
            # There is no outstanding query during caller work. This arm can
            # be cancelled with ABOR; an ambiguous transfer instead needs device clear.
            io.pending(False)
            self._power_arm_active = True
            failure: BaseException | None = None
            try:
                yield capture
            except BaseException as exc:
                failure = exc
                raise
            finally:
                capture._closed = True
                self._power_arm_active = False
                if capture._needs_abort:
                    try:
                        with self._power_io(500) as cleanup:
                            cleanup.pending(True)
                            cleanup.send(abort)
                            self._require_no_power_error(cleanup.query(error))
                            self._require_idle_sensor(
                                cleanup, continuous, operations, "Scoped abort"
                            )
                            cleanup.pending(False)
                    except (Exception, KeyboardInterrupt) as exc:
                        if failure is None:
                            raise
                        failure.add_note(f"Could not verify scoped power abort: {exc}")
                        for note in getattr(exc, "__notes__", ()):
                            failure.add_note(note)

    def configure_power_trace(
        self,
        channel: int = 1,
        *,
        frequency_hz: float,
        duration_s: float,
        offset_s: float = 0.0,
        trigger_source: TraceTrigger = "external",
        trigger_edge: PowerTriggerEdge = "rising",
        trigger_level_dbm: float | None = None,
        native_unit: Literal["dBm", "W"] = "dBm",
        timeout_ms: int = 5_000,
    ) -> PowerTraceSettings:
        """Configure an idle native RF envelope capture on supported sensors."""
        op = "configure_power_trace"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        source = self._resolve_operation_parameter(op, "trigger_source", trigger_source)
        edge = self._resolve_operation_parameter(op, "trigger_edge", trigger_edge)
        unit = self._resolve_operation_parameter(op, "native_unit", native_unit)
        if (source.value == "internal") != (trigger_level_dbm is not None):
            raise ValueError("Provide trigger_level_dbm only and always for an internal trigger.")
        parameters = {
            name: self._resolve_operation_parameter(op, name, val).value
            for name, val in (
                ("frequency_hz", frequency_hz),
                ("duration_s", duration_s),
                ("offset_s", offset_s),
            )
        }
        keys = ["setup_trace", "set_sensor_frequency"]
        if trigger_level_dbm is not None:
            parameters["trigger_level_dbm"] = self._resolve_operation_parameter(
                op, "trigger_level_dbm", trigger_level_dbm, context={"trigger_source": source.value}
            ).value
            keys.append("set_trigger_level")
        setup = self._power_commands(
            op,
            keys,
            channel=channel,
            source=source.transport_value,
            edge=edge.transport_value,
            units=unit.transport_value,
            frequency=parameters["frequency_hz"],
            **parameters,
        )
        readbacks = self._trace_readbacks(op, channel)
        error = self._power_commands(op, ["get_error"], channel=channel)[0]
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            for command in setup:
                io.send(command)
            self._require_no_power_error(io.query(error))
            settings = self._read_trace_settings(channel, readbacks, io.query)
            self._require_no_power_error(io.query(error))
            if (settings.trigger_source, settings.trigger_edge, settings.native_unit) != (
                source.value,
                edge.value,
                unit.value,
            ):
                raise InstrumentConfigurationError(
                    self.config.model, "Sensor rejected the requested trace source, edge, or unit."
                )
            for name, actual, requested, tolerance in (
                ("trace frequency", settings.correction_frequency_hz, frequency_hz, 0.0),
                ("trigger delay", settings.trigger_delay_s, 0.0, 0.0),
                ("trace offset", settings.offset_s, offset_s, 0.500001e-6),
                ("trace duration", settings.duration_s, duration_s, 0.500001e-6),
                ("trigger level", settings.trigger_level_dbm, trigger_level_dbm, 0.05000001),
            ):
                if requested is not None and (
                    actual is None
                    or not isclose(actual, requested, rel_tol=1e-9, abs_tol=tolerance)
                ):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Unexpected {name}: {actual!r}; requested {requested!r}.",
                    )
            return settings

    def acquire_power_trace(
        self,
        channel: int = 1,
        *,
        resolution: PowerTraceResolution = "high",
        unit: PowerUnit = "dBm",
        timeout_ms: int = 10_000,
    ) -> PowerTrace:
        """Arm a new trace and fetch its binary block only after confirmed completion."""
        op = "acquire_power_trace"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        selection = self._resolve_operation_parameter(op, "resolution", resolution)
        resolution = cast(PowerTraceResolution, selection.value)
        unit = cast(PowerUnit, self._resolve_operation_parameter(op, "unit", unit).value)
        readbacks = self._trace_readbacks(op, channel)
        start = self._power_commands(op, ["start"], channel=channel)
        completion, quality, error = self._power_commands(
            op, ["opc_query", "read_quality", "get_error"], channel=channel
        )
        fetch = self._power_commands(
            op, ["fetch_trace"], channel=channel, resolution=selection.transport_value
        )[0]
        if self._native_backend_method_available("query_raw") is False:
            raise InstrumentConfigurationError(
                self.config.model, "Power traces require a binary-query-capable backend."
            )
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            if not callable(getattr(self._backend, "query_raw", None)):
                raise InstrumentConfigurationError(
                    self.config.model, "Power traces require a binary-query-capable backend."
                )
            settings = self._read_trace_settings(channel, readbacks, io.query)
            self._require_no_power_error(io.query(error))
            for command in start:
                io.pending(True)
                io.send(command)
            if io.query(completion).strip() not in {"1", "+1"}:
                raise InstrumentDataError(self.config.model, "Power trace did not complete.")
            io.pending(False)
            self._require_no_power_error(io.query(error))
            io.pending(True)
            raw = io.query_raw(fetch)
            samples = self._decode_power_trace(raw, resolution, settings.native_unit)
            io.pending(False)
            received = datetime.now(UTC)
            if self._power_register(io.query(quality), "power condition"):
                raise InstrumentDataError(
                    self.config.model, "Sensor reports questionable trace data."
                )
            self._require_no_power_error(io.query(error))
            values = tuple(
                self._convert_power(value, settings.native_unit, unit) for value in samples
            )
            return PowerTrace(values, unit, resolution, settings, received)

    def _trace_readbacks(self, op: str, channel: int) -> dict[str, str]:
        return {
            key: self._power_commands(op, [key], channel=channel)[0]
            for key in (
                "read_continuous",
                "read_detector",
                "read_rate",
                "read_trigger_source",
                "read_gate_edge",
                "read_gate_delay",
                "read_gate_auto_delay",
                "read_trigger_count",
                "read_trigger_level",
                "read_trace_offset",
                "read_trace_duration",
                "read_trace_unit",
                "read_trace_enabled",
                "read_correction_frequency",
                "read_frequency_steps",
                "read_trace_buffer_count",
                "read_averaging_enabled",
            )
        }

    def _read_trace_settings(
        self, channel: int, commands: dict[str, str], io_query: Callable[[str], str]
    ) -> PowerTraceSettings:
        def query(key: str) -> str:
            return io_query(commands[key]).strip().strip('"').upper()

        for key, allowed in (
            ("read_continuous", _OFF),
            ("read_detector", {"NORM", "NORMAL"}),
            ("read_rate", {"NORM", "NORMAL"}),
            ("read_trace_enabled", _ON),
            ("read_gate_auto_delay", _OFF),
            ("read_averaging_enabled", _OFF),
        ):
            if query(key) not in allowed:
                raise InstrumentConfigurationError(
                    self.config.model,
                    f"Incompatible trace setting: {key.removeprefix('read_')}. "
                    "Configure the power trace first.",
                )
        for key, expected in (
            ("read_trigger_count", 1),
            ("read_frequency_steps", 0),
            ("read_trace_buffer_count", 1),
        ):
            if self._number(query(key), key) != expected:
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Power trace requires one acquisition and no frequency sweep "
                    "or average-measurement buffer.",
                )
        src = query("read_trigger_source")
        source: TraceTrigger
        if src in {"INT", "INTERNAL", "INT1", "INTERNAL1"}:
            source = "internal"
            threshold = self._number(query("read_trigger_level"), "trace trigger level")
        elif src in {"EXT", "EXTERNAL"}:
            source = "external"
            threshold = None
        else:
            raise InstrumentConfigurationError(
                self.config.model, "Expected an external or internal trace trigger."
            )
        delay = self._verified_capture_delay(query("read_gate_delay"))
        edge = _EDGE_TOKENS.get(query("read_gate_edge"))
        unit = _UNIT_TOKENS.get(query("read_trace_unit"))
        offset = self._number(query("read_trace_offset"), "trace offset")
        duration = self._number(query("read_trace_duration"), "trace duration")
        frequency = self._number(query("read_correction_frequency"), "trace correction frequency")
        if (
            edge is None
            or unit not in {"dBm", "W"}
            or not -0.15 <= offset <= 0.15
            or not 1e-4 <= duration <= 0.15
            or frequency <= 0
        ):
            raise InstrumentDataError(self.config.model, "Invalid live RF power trace metadata.")
        return PowerTraceSettings(
            self.config.model,
            channel,
            frequency,
            unit,
            source,
            edge,
            threshold,
            offset,
            duration,
            delay,
        )

    def _decode_power_trace(
        self, raw: bytes, resolution: PowerTraceResolution, unit: PowerUnit
    ) -> tuple[float, ...]:
        try:
            payload = strip_definite_length_block(raw)
            end = 2 + int(raw[1:2]) + len(payload)
            if raw[end:] != b"\n" or not payload or len(payload) % 4:
                raise ValueError("Expected a complete float32 block followed by LF.")
            samples = tuple(value for (value,) in iter_unpack(">f", payload))
        except (BinaryBlockParseError, ValueError) as exc:
            raise InstrumentDataError(
                self.config.model, f"Invalid power trace block: {exc}"
            ) from exc
        expected = {"low": 230, "medium": 1000}.get(resolution)
        if len(samples) < 2 or (expected is not None and len(samples) != expected):
            raise InstrumentDataError(self.config.model, "Unexpected power trace sample count.")
        if any(not isfinite(value) or abs(value) >= 9.9e37 for value in samples) or (
            unit != "dBm" and any(value < 0 for value in samples)
        ):
            raise InstrumentDataError(self.config.model, "Invalid power values in native trace.")
        return samples

    def read_power_corrections(
        self, channel: int = 1, *, timeout_ms: int = 2_000
    ) -> PowerCorrections:
        """Inspect active and programmed correction state without altering it."""
        op = "read_power_corrections"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        spec = self.config.operation_options.operation(op)
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Correction readback is unsupported."
            )
        keys = [
            "read_correction_frequency",
            "read_fixed_offset_enabled",
            "read_fixed_offset",
            "read_duty_cycle",
            "read_duty_cycle_percent",
        ]
        for vendor_keys in (
            ("read_frequency_table_enabled", "read_frequency_table_name"),
            ("read_s_parameter_enabled", "read_s_parameter_set"),
        ):
            if vendor_keys[0] in spec.transport:
                keys += vendor_keys
        commands = {key: self._power_commands(op, [key], channel=channel)[0] for key in keys}
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:

            def query(key: str) -> str:
                return io.query(commands[key])

            frequency = self._number(query("read_correction_frequency"), "correction frequency")
            fixed_enabled = self._power_boolean(query("read_fixed_offset_enabled"), "fixed offset")
            fixed = self._number(query("read_fixed_offset"), "fixed offset")
            duty_enabled = self._power_boolean(query("read_duty_cycle"), "duty cycle")
            duty = self._number(query("read_duty_cycle_percent"), "duty cycle")
            if frequency <= 0 or not 0.001 <= duty <= 100:
                raise InstrumentDataError(self.config.model, "Invalid correction settings.")
            fdo_enabled = None
            table = None
            if "read_frequency_table_enabled" in commands:
                fdo_enabled = self._power_boolean(
                    query("read_frequency_table_enabled"), "frequency-dependent offset"
                )
                raw_table = query("read_frequency_table_name").strip()
                if raw_table:
                    if len(raw_table) < 2 or not (
                        raw_table.startswith('"') and raw_table.endswith('"')
                    ):
                        raise InstrumentDataError(
                            self.config.model, "Invalid frequency-dependent offset table name."
                        )
                    table = raw_table[1:-1] or None
                if fdo_enabled and table is None:
                    raise InstrumentDataError(
                        self.config.model, "Active frequency-dependent offset has no table."
                    )
            s_parameter_enabled = None
            s_parameter_set = None
            if "read_s_parameter_enabled" in commands:
                s_parameter_enabled = self._power_boolean(
                    query("read_s_parameter_enabled"), "S-parameter correction"
                )
                s_parameter_set = self._s_parameter_index(query("read_s_parameter_set"))
            return PowerCorrections(
                frequency,
                fixed_enabled,
                fixed,
                duty_enabled,
                duty,
                fdo_enabled,
                table,
                s_parameter_enabled,
                s_parameter_set,
            )

    def configure_power_offset(
        self,
        channel: int = 1,
        *,
        enabled: bool,
        offset_db: float | None = None,
        timeout_ms: int = 5_000,
    ) -> PowerFixedOffset:
        """Apply an explicit fixed correction in dB, or disable it without changing its value.

        The signed value is passed through as documented by the sensor.
        Enter a negative loss on U2000A or a positive attenuation offset on
        NRP18AN. This neither changes another correction nor drives the RF source.
        """
        op = "configure_power_offset"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        state = self._resolve_operation_parameter(op, "enabled", enabled)
        if state.value != (offset_db is not None):
            raise ValueError("Provide offset_db when enabling; omit it when disabling.")
        keys = ["set_fixed_offset_enabled"]
        parameters: dict[str, Any] = {"channel": channel, "state": state.transport_value}
        if offset_db is not None:
            offset_db = self._resolve_operation_parameter(
                op, "offset_db", offset_db, context={"enabled": state.value}
            ).value
            parameters["offset_db"] = offset_db
            keys[:0] = ["set_fixed_offset"]
        commands = self._power_commands(op, keys, **parameters)
        state_query, offset_query = self._power_commands(
            op, ["read_fixed_offset_enabled", "read_fixed_offset"], channel=channel
        )
        spec = self.config.operation_options.operation(op)
        rate_query = (
            self._power_commands(op, ["read_rate"], channel=channel)[0]
            if spec is not None and "read_rate" in spec.transport
            else None
        )
        with self._power_verified_idle_update(op, channel, timeout_ms) as (io, error):
            # Keysight GAIN2 can change the saved value despite reporting
            # a settings conflict in FAST (legacy 110 readings/s).
            if rate_query is not None:
                rate = io.query(rate_query).strip().strip('"').upper()
                if rate not in {"NORM", "NORMAL", "DOUB", "DOUBLE"}:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Fixed offset requires Normal or Double rate, not {rate!r}.",
                    )
                self._require_no_power_error(io.query(error))
            for command in commands:
                io.send(command)
                self._require_no_power_error(io.query(error))
            actual = PowerFixedOffset(
                self._power_boolean(io.query(state_query), "fixed offset"),
                self._number(io.query(offset_query), "fixed offset"),
            )
            self._require_no_power_error(io.query(error))
            if actual.enabled != state.value or (
                offset_db is not None
                and not isclose(actual.offset_db, offset_db, rel_tol=1e-9, abs_tol=1e-9)
            ):
                raise InstrumentConfigurationError(
                    self.config.model, "Sensor did not apply the fixed offset."
                )
            return actual

    def configure_power_s_parameter(
        self,
        channel: int = 1,
        *,
        enabled: bool,
        data_set: int | None = None,
        timeout_ms: int = 5_000,
    ) -> PowerSParameterCorrection:
        """Select and verify an existing R&S data set before enabling its correction.

        No table is written or uploaded. Supply the installed index when enabling.
        Disabling leaves the selected data-set index alone.
        """
        op = "configure_power_s_parameter"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        state = self._resolve_operation_parameter(op, "enabled", enabled)
        if state.value != (data_set is not None):
            raise ValueError("Provide data_set when enabling; omit it when disabling.")
        off, on = (
            self._correction_state_command(op, "set_s_parameter_enabled", channel, value)
            for value in (False, True)
        )
        select = None
        if data_set is not None:
            data_set = self._resolve_operation_parameter(
                op, "data_set", data_set, context={"enabled": state.value}
            ).value
            select = self._power_commands(
                op, ["select_s_parameter_set"], channel=channel, data_set=data_set
            )[0]
        state_query, index_query = self._power_commands(
            op, ["read_s_parameter_enabled", "read_s_parameter_set"], channel=channel
        )
        with self._power_verified_idle_update(op, channel, timeout_ms) as (io, error):
            self._switch_correction(io, error, off, state_query, False, "S-parameter correction")
            if select is not None:
                io.send(select)
                self._require_no_power_error(io.query(error))
            actual_index = self._s_parameter_index(io.query(index_query))
            self._require_no_power_error(io.query(error))
            if data_set is not None and actual_index != data_set:
                raise InstrumentConfigurationError(
                    self.config.model, "Sensor did not select the requested S-parameter data set."
                )
            if state.value:
                self._switch_correction(io, error, on, state_query, True, "S-parameter correction")
                actual_index = self._s_parameter_index(io.query(index_query))
                self._require_no_power_error(io.query(error))
                if actual_index != data_set:
                    raise InstrumentConfigurationError(
                        self.config.model, "S-parameter data set changed during activation."
                    )
            return PowerSParameterCorrection(state.value, actual_index)

    def configure_power_source_reflection(
        self,
        channel: int = 1,
        *,
        enabled: bool,
        magnitude: float | None = None,
        phase_deg: float | None = None,
        timeout_ms: int = 5_000,
    ) -> PowerSourceReflectionCorrection:
        """Configure the known source reflection coefficient supplied by the operator.

        This is not a measurement of source return loss. Enabling requires
        both magnitude and phase; disabling retains the programmed values.
        """
        op = "configure_power_source_reflection"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        state = self._resolve_operation_parameter(op, "enabled", enabled)
        if (magnitude is None) != (phase_deg is None) or state.value != (magnitude is not None):
            raise ValueError(
                "Provide magnitude and phase_deg when enabling; omit both when disabling."
            )
        off, on = (
            self._correction_state_command(op, "set_source_reflection_enabled", channel, value)
            for value in (False, True)
        )
        setup: list[str] = []
        if magnitude is not None:
            magnitude = self._resolve_operation_parameter(
                op, "magnitude", magnitude, context={"enabled": state.value}
            ).value
            phase_deg = self._resolve_operation_parameter(
                op, "phase_deg", phase_deg, context={"enabled": state.value}
            ).value
            setup = self._power_commands(
                op,
                ["set_source_reflection"],
                channel=channel,
                magnitude=magnitude,
                phase_deg=phase_deg,
            )
        queries = self._source_reflection_queries(op, channel)
        with self._power_verified_idle_update(op, channel, timeout_ms) as (io, error):
            self._switch_correction(
                io, error, off, queries[0], False, "source reflection correction"
            )
            for command in setup:
                io.send(command)
            self._require_no_power_error(io.query(error))
            actual = self._read_source_reflection(io, queries)
            self._require_no_power_error(io.query(error))
            if actual.enabled or not self._matches_source_reflection(actual, magnitude, phase_deg):
                raise InstrumentConfigurationError(
                    self.config.model, "Sensor did not apply the source reflection coefficient."
                )
            if state.value:
                io.send(on)
                self._require_no_power_error(io.query(error))
                actual = self._read_source_reflection(io, queries)
                self._require_no_power_error(io.query(error))
                if not actual.enabled or not self._matches_source_reflection(
                    actual, magnitude, phase_deg
                ):
                    raise InstrumentConfigurationError(
                        self.config.model, "Source reflection settings changed during activation."
                    )
            return actual

    @staticmethod
    def _matches_source_reflection(
        actual: PowerSourceReflectionCorrection, magnitude: float | None, phase_deg: float | None
    ) -> bool:
        return (
            magnitude is None
            or phase_deg is None
            or (
                isclose(actual.magnitude, magnitude, rel_tol=1e-9, abs_tol=1e-9)
                and isclose(remainder(actual.phase_deg - phase_deg, 360), 0, abs_tol=1e-9)
            )
        )

    def read_power_source_reflection(
        self, channel: int = 1, *, timeout_ms: int = 2_000
    ) -> PowerSourceReflectionCorrection:
        """Read the programmed source reflection coefficient without changing it."""
        op = "read_power_source_reflection"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        queries = self._source_reflection_queries(op, channel)
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            return self._read_source_reflection(io, queries)

    def read_power_input_reflection(
        self, channel: int = 1, *, timeout_ms: int = 2_000
    ) -> PowerInputReflection:
        """Query the sensor's calibrated input-plane reflection at the live correction frequency.

        The sensor supplies an expanded uncertainty (k=2) of the magnitude
        only. The selected S-parameter correction can move the reference plane
        from the sensor connector to the front of the calibrated two-port.
        """
        op = "read_power_input_reflection"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        frequency, enabled, selected, mag, phase, uncertainty = self._power_commands(
            op,
            [
                "read_correction_frequency",
                "read_s_parameter_enabled",
                "read_s_parameter_set",
                "read_input_reflection_magnitude",
                "read_input_reflection_phase",
                "read_input_reflection_uncertainty",
            ],
            channel=channel,
        )
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            frequency_hz = self._number(io.query(frequency), "correction frequency")
            shift = self._power_boolean(io.query(enabled), "S-parameter correction")
            data_set = self._s_parameter_index(io.query(selected)) if shift else None
            magnitude = self._number(io.query(mag), "input reflection magnitude")
            phase_deg = self._number(io.query(phase), "input reflection phase")
            reply = io.query(uncertainty)
            received_at = datetime.now(UTC)
            expanded = self._number(reply, "input reflection uncertainty")
            same_shift = self._power_boolean(io.query(enabled), "S-parameter correction")
            same_frequency = self._number(io.query(frequency), "correction frequency")
            same_data_set = self._s_parameter_index(io.query(selected)) if same_shift else None
            if (same_shift, same_frequency, same_data_set) != (shift, frequency_hz, data_set):
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Reflection reference plane or frequency changed during readback.",
                )
            if frequency_hz <= 0 or magnitude < 0 or not -180 <= phase_deg <= 180 or expanded < 0:
                raise InstrumentDataError(
                    self.config.model, "Invalid native input reflection data."
                )
            return PowerInputReflection(
                frequency_hz,
                magnitude,
                phase_deg,
                expanded,
                "s_parameter_device_input" if shift else "sensor_input",
                data_set,
                _model=self.config.model,
                _receipt=received_at,
            )

    def _source_reflection_queries(self, op: str, channel: int) -> tuple[str, str, str]:
        state, magnitude, phase = self._power_commands(
            op,
            [
                "read_source_reflection_enabled",
                "read_source_reflection_magnitude",
                "read_source_reflection_phase",
            ],
            channel=channel,
        )
        return state, magnitude, phase

    def _read_source_reflection(
        self, io: _PowerIO, queries: tuple[str, str, str]
    ) -> PowerSourceReflectionCorrection:
        state, magnitude, phase = queries
        active = self._power_boolean(io.query(state), "source reflection correction")
        gamma = self._number(io.query(magnitude), "source reflection magnitude")
        phase_deg = self._number(io.query(phase), "source reflection phase")
        if not 0 <= gamma <= 1 or not -360 <= phase_deg <= 360:
            raise InstrumentDataError(self.config.model, "Invalid native source reflection data.")
        return PowerSourceReflectionCorrection(active, gamma, phase_deg)

    def _s_parameter_index(self, response: str) -> int:
        index = self._power_register(response, "S-parameter data set")
        if not 1 <= index <= 1999:
            raise InstrumentDataError(self.config.model, "Invalid S-parameter correction set.")
        return index

    def _correction_state_command(self, op: str, key: str, channel: int, value: bool) -> str:
        enabled = self._resolve_operation_parameter(op, "enabled", value)
        return self._power_commands(op, [key], channel=channel, state=enabled.transport_value)[0]

    def _switch_correction(
        self, io: _PowerIO, error: str, command: str, read: str, expected: bool, label: str
    ) -> None:
        io.send(command)
        self._require_no_power_error(io.query(error))
        actual = self._power_boolean(io.query(read), label)
        self._require_no_power_error(io.query(error))
        if actual != expected:
            raise InstrumentConfigurationError(
                self.config.model, f"Sensor did not apply the requested {label} state."
            )

    @contextmanager
    def _power_verified_idle_update(
        self, op: str, channel: int, timeout_ms: int, *, action: str = "Correction setup"
    ) -> Iterator[tuple[_PowerIO, str]]:
        identify, continuous, calibrating, measuring, triggering, error = self._power_commands(
            op,
            [
                "identify",
                "read_continuous",
                "read_calibrating",
                "read_measuring",
                "read_triggering",
                "get_error",
            ],
            channel=channel,
        )
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            self._verify_service_identity(io.query(identify), f"perform {action.lower()} on")
            self._require_idle_sensor(io, continuous, (calibrating, measuring, triggering), action)
            self._require_no_power_error(io.query(error))
            yield io, error

    def configure_power_trigger_timing(
        self,
        channel: int = 1,
        *,
        delay_s: float | None = None,
        holdoff_s: float | None = None,
        hysteresis_db: float | None = None,
        dropout_s: float | None = None,
        timeout_ms: int = 5_000,
    ) -> PowerTriggerTiming:
        """Adjust timing for an already-selected internal or external edge.

        Delay is in seconds and explicitly disables automatic delay. Hysteresis
        is in dB and, like supported dropout, applies only to an internal
        RF-envelope trigger. No source, slope, port, or sender is changed.
        """
        op = "configure_power_trigger_timing"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        values = {
            name: self._resolve_operation_parameter(op, name, value).value
            for name, value in (
                ("delay_s", delay_s),
                ("holdoff_s", holdoff_s),
                ("hysteresis_db", hysteresis_db),
                ("dropout_s", dropout_s),
            )
            if value is not None
        }
        if not values:
            raise ValueError("Provide at least one trigger timing setting.")
        setup = self._power_commands(
            op, [f"set_{name}" for name in values], channel=channel, **values
        )
        readbacks = self._trigger_timing_commands(op, channel)
        with self._power_verified_idle_update(
            op, channel, timeout_ms, action="Trigger timing setup"
        ) as (io, error):
            source = self._timing_source(io.query(readbacks["read_trigger_source"]), readbacks)
            self._require_no_power_error(io.query(error))
            if source in {"immediate", "bus", "hold"}:
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Configure an internal or external edge before adjusting timing.",
                )
            if source != "internal" and values.keys() & {"hysteresis_db", "dropout_s"}:
                raise InstrumentConfigurationError(
                    self.config.model, "Hysteresis and dropout require an internal RF trigger."
                )
            for command in setup:
                io.send(command)
                self._require_no_power_error(io.query(error))
            actual = self._read_trigger_timing(readbacks, io.query)
            self._require_no_power_error(io.query(error))
            if actual.source != source or ("delay_s" in values and actual.delay_auto is not False):
                raise InstrumentConfigurationError(
                    self.config.model, "Sensor trigger source or automatic delay changed."
                )
            spec = self.config.operation_options.operation(op)
            assert spec is not None
            for name, value in values.items():
                readback = getattr(actual, name)
                resolution = spec.parameters[name].constraints.get("resolution", 0.0)
                if readback is None or not isclose(
                    readback, value, rel_tol=1e-9, abs_tol=float(resolution) / 2 + 1e-12
                ):
                    raise InstrumentConfigurationError(
                        self.config.model, f"Sensor did not apply trigger {name}: {readback!r}."
                    )
            return actual

    def read_power_trigger_timing(
        self, channel: int = 1, *, timeout_ms: int = 2_000
    ) -> PowerTriggerTiming:
        """Read live trigger timing without arming or changing the sensor."""
        op = "read_power_trigger_timing"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        readbacks = self._trigger_timing_commands(op, channel)
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            return self._read_trigger_timing(readbacks, io.query)

    def _trigger_timing_commands(self, op: str, channel: int) -> dict[str, str]:
        keys = [
            "read_trigger_source",
            "read_gate_edge",
            "read_gate_delay",
            "read_gate_auto_delay",
            "read_trigger_holdoff",
            "read_trigger_hysteresis",
        ]
        spec = self.config.operation_options.operation(op)
        if spec is not None and "read_trigger_dropout" in spec.transport:
            keys.append("read_trigger_dropout")
        return {key: self._power_commands(op, [key], channel=channel)[0] for key in keys}

    def _timing_source(
        self, response: str, readbacks: dict[str, str]
    ) -> PowerTrigger | Literal["bus", "hold"]:
        token = response.strip().strip('"').upper()
        if token == "BUS":
            return "bus"
        if token == "HOLD":
            return "hold"
        source = _TRIGGER_TOKENS.get(token)
        if source is None:
            raise InstrumentDataError(self.config.model, f"Unknown trigger source: {token!r}.")
        if source == "external" and "read_trigger_dropout" in readbacks:
            return "external_1"
        return source

    def _read_trigger_timing(
        self, commands: dict[str, str], query: Callable[[str], str]
    ) -> PowerTriggerTiming:
        source = self._timing_source(query(commands["read_trigger_source"]), commands)
        if source in {"immediate", "bus", "hold"}:
            return PowerTriggerTiming(source)
        edge = None
        if source != "external_2":
            edge = _EDGE_TOKENS.get(query(commands["read_gate_edge"]).strip().strip('"').upper())
            if edge is None:
                raise InstrumentDataError(self.config.model, "Invalid live trigger slope.")
        delay = self._number(query(commands["read_gate_delay"]), "trigger delay")
        auto_delay = self._power_boolean(query(commands["read_gate_auto_delay"]), "automatic delay")
        holdoff = self._number(query(commands["read_trigger_holdoff"]), "trigger holdoff")
        hysteresis = dropout = None
        if source == "internal":
            hysteresis = self._number(
                query(commands["read_trigger_hysteresis"]), "trigger hysteresis"
            )
            if "read_trigger_dropout" in commands:
                dropout = self._number(query(commands["read_trigger_dropout"]), "trigger dropout")
        if any(value is not None and value < 0 for value in (holdoff, hysteresis, dropout)):
            raise InstrumentDataError(self.config.model, "Invalid live trigger timing.")
        return PowerTriggerTiming(source, edge, delay, auto_delay, holdoff, hysteresis, dropout)

    def _verified_capture_delay(self, response: str) -> float:
        delay = self._number(response, "trigger delay")
        if delay == 0:
            return delay  # Preserve zero-delay support for older third-party profiles.
        spec = self.config.operation_options.operation("configure_power_trigger_timing")
        parameter = spec.parameters.get("delay_s") if spec is not None else None
        if (
            parameter is None
            or not parameter.supported
            or parameter.min is None
            or parameter.max is None
            or not parameter.min <= delay <= parameter.max
        ):
            raise InstrumentConfigurationError(
                self.config.model,
                "This verified acquisition does not support the live trigger delay.",
            )
        return delay

    def read_power_trigger_state(
        self, channel: int = 1, *, timeout_ms: int = 2_000
    ) -> PowerTriggerState:
        """Read current trigger/measurement conditions without clearing event registers."""
        op = "read_power_trigger_state"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        continuous, triggering, measuring, calibrating = self._power_commands(
            op,
            ["read_continuous", "read_triggering", "read_measuring", "read_calibrating"],
            channel=channel,
        )
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            return PowerTriggerState(
                self._power_boolean(io.query(continuous), "continuous initiation"),
                bool(self._power_register(io.query(triggering), "trigger condition")),
                bool(self._power_register(io.query(measuring), "measurement condition")),
                bool(self._power_register(io.query(calibrating), "calibration condition")),
            )

    def _power_boolean(self, response: str, label: str) -> bool:
        token = response.strip().upper()
        if token in _ON:
            return True
        if token in _OFF:
            return False
        raise InstrumentDataError(self.config.model, f"Invalid {label} state: {response!r}.")

    def sensor_status(self, channel: int = 1, *, timeout_ms: int = 2_000) -> PowerSensorStatus:
        """Read identification and live condition registers without consuming events or errors."""
        operation = "sensor_status"
        channel = self._power_channel(operation, channel)
        timeout_ms = self._power_timeout(operation, timeout_ms)
        identify, power, calibration = self._power_commands(
            operation, ["identify", "read_quality", "read_calibration_condition"], channel=channel
        )
        self._ensure_backend_connected()
        with self._profile_transaction(), self._power_io(timeout_ms) as io:
            query = io.query
            manufacturer, model, serial, firmware = self._power_identity(query(identify))
            power_bits = self._power_register(query(power), "power condition")
            calibration_bits = self._power_register(query(calibration), "calibration condition")

        descriptions = (
            self.config.power_condition_bits,
            self.config.calibration_condition_bits,
        )
        active: list[str] = []
        for register, value, names in zip(
            ("power", "calibration"), (power_bits, calibration_bits), descriptions, strict=True
        ):
            for bit in range(15):
                if value & (1 << bit):
                    active.append(names.get(bit, f"unknown {register} condition bit {bit}"))
        return PowerSensorStatus(
            manufacturer,
            model,
            serial,
            firmware,
            channel,
            power_bits,
            calibration_bits,
            tuple(active),
        )

    def _power_identity(self, response: str) -> tuple[str, str, str, str]:
        try:
            fields = next(csv_reader([response], skipinitialspace=True, strict=True))
            manufacturer, model, serial, firmware = (field.strip() for field in fields)
            if not manufacturer or not model:
                raise ValueError
        except (CSVError, StopIteration, ValueError) as exc:
            raise InstrumentDataError(
                self.config.model, f"Invalid sensor identification: {response!r}."
            ) from exc
        return manufacturer, model, serial, firmware

    def _verify_service_identity(self, response: str, action: str) -> tuple[str, str]:
        manufacturer, model, serial, _ = self._power_identity(response)
        expected_vendor = " ".join(self.config.manufacturer.casefold().split())
        live_vendor = " ".join(manufacturer.casefold().split())
        if expected_vendor in _KEYSIGHT_IDENTITY_NAMES | {"keysight", "agilent"}:
            allowed_vendors = _KEYSIGHT_IDENTITY_NAMES
        elif expected_vendor in _RS_IDENTITY_NAMES:
            allowed_vendors = _RS_IDENTITY_NAMES
        else:
            allowed_vendors = frozenset({expected_vendor})
        configured_serial = self.config.serial_number
        if (
            live_vendor not in allowed_vendors
            or model.casefold() != self.config.model.strip().casefold()
            or not serial
            or (configured_serial is not None and serial != configured_serial.strip())
        ):
            raise InstrumentConfigurationError(
                self.config.model,
                f"Cannot {action} sensor: live identity ({manufacturer!r}, {model!r}, "
                f"serial {serial!r}) does not match the configured manufacturer, model, "
                "and optional serial. Check the bench binding.",
            )
        return model, serial

    def _require_idle_sensor(
        self, io: _PowerIO, continuous: str, operations: tuple[str, ...], action: str
    ) -> None:
        if self._power_boolean(io.query(continuous), "continuous initiation") or any(
            self._power_register(io.query(command), "operation condition") for command in operations
        ):
            raise InstrumentConfigurationError(
                self.config.model, f"{action} requires an idle sensor. Stop measurements first."
            )

    # The native sensor diagnostic has its own result and arguments; keep the legacy
    # Instrument self-test signature and text result for existing instrument classes.
    def run_self_test(  # ty: ignore[invalid-method-override]
        self, *, channel: int = 1, timeout_ms: int = 60_000
    ) -> InstrumentSelfTestResult:
        """Run the native self-test against a verified, idle sensor.

        Switch off or disconnect RF at the sensor input before calling. This
        method does not control the RF source. The test can take tens of
        seconds. A reported failure returns the native nonzero code; the
        driver does not retry the test or drain the error queue.
        """
        op = "run_self_test"
        channel = self._power_channel(op, channel)
        timeout_ms = self._power_timeout(op, timeout_ms)
        identify, continuous, calibrating, measuring, triggering, test = self._power_commands(
            op,
            [
                "identify",
                "read_continuous",
                "read_calibrating",
                "read_measuring",
                "read_triggering",
                "self_test",
            ],
            channel=channel,
        )
        self._ensure_backend_connected()
        with (
            self._profile_transaction(),
            self._power_io(timeout_ms, pending_maintenance="self-test") as io,
        ):
            model, serial = self._verify_service_identity(io.query(identify), "self-test")
            self._require_idle_sensor(
                io, continuous, (calibrating, measuring, triggering), "Self-test"
            )
            io.pending(True)
            result = io.query(test)
            try:
                code = int(result.strip())
            except ValueError as exc:
                raise InstrumentDataError(
                    self.config.model, f"Invalid sensor self-test result: {result!r}."
                ) from exc
            io.pending(False)
            return InstrumentSelfTestResult(
                model=model,
                serial_number=serial,
                code=code,
                completed_at_utc=datetime.now(UTC),
                raw_response=result,
                channel=channel,
            )

    def zero_sensor(
        self,
        channel: int = 1,
        *,
        mode: PowerZeroMode = "external",
        timeout_ms: int = 30_000,
    ) -> PowerZeroResult:
        """Deliberately zero an idle sensor; never drive or mute the RF source.

        For an external zero, switch off or disconnect RF at the sensor input
        before calling. Internal zero is available only on profiles with a
        documented isolation switch. The live manufacturer, model, and any
        configured serial must match. On U2000A the selected zero type persists.
        """
        operation = "zero_sensor"
        channel = self._power_channel(operation, channel)
        choice = self._resolve_operation_parameter(operation, "mode", mode)
        mode = cast(PowerZeroMode, choice.value)
        timeout_ms = self._power_timeout(operation, timeout_ms)
        identify, continuous, calibrating, measuring, triggering, error = self._power_commands(
            operation,
            [
                "identify",
                "read_continuous",
                "read_calibrating",
                "read_measuring",
                "read_triggering",
                "get_error",
            ],
            channel=channel,
        )
        zero = self._power_commands(operation, ["perform_zero"], channel=channel)[0]
        spec = self.config.operation_options.operation(operation)
        assert spec is not None
        select, verify = (
            self._power_commands(
                operation,
                ["set_zero_type", "read_zero_type"],
                channel=channel,
                mode=choice.transport_value,
            )
            if "set_zero_type" in spec.transport
            else (None, None)
        )
        static_error = (
            self._power_commands(operation, ["read_static_error"], channel=channel)[0]
            if "read_static_error" in spec.transport
            else None
        )
        completion = (
            self._power_commands(operation, ["opc_query"], channel=channel)[0]
            if static_error is None
            else None
        )
        self._ensure_backend_connected()
        with (
            self._profile_transaction(),
            self._power_io(timeout_ms, pending_maintenance="zero") as io,
        ):
            query, send, pending = io.query, io.send, io.pending

            def check_zero_error(response: str, *, complete: bool = False) -> None:
                code = self._power_error_code(response)
                if complete or code != 0:
                    pending(False)  # A well-formed sensor result is not ambiguous.
                if code != 0:
                    self._require_no_power_error(response)

            self._verify_service_identity(query(identify), "zero")
            self._require_idle_sensor(io, continuous, (calibrating, measuring, triggering), "Zero")
            self._require_no_power_error(query(error))
            if select is not None and verify is not None:
                pending(True)
                send(select)
                check_zero_error(query(error))
                reported = query(verify).strip().strip('"').upper()
                if reported not in {mode.upper(), str(choice.transport_value).upper()}:
                    raise InstrumentConfigurationError(
                        self.config.model, f"Unexpected zero type: {reported!r}."
                    )
            pending(True)
            send(zero)
            if static_error is not None:
                # R&S zero is synchronous; the static queue reports its result.
                check_zero_error(query(static_error))
            else:
                # Keysight zero is overlapped; the completion barrier only
                # confirms that it ended. The SCPI error query checks success.
                assert completion is not None
                if query(completion).strip() not in {"1", "+1"}:
                    raise InstrumentDataError(self.config.model, "Sensor zero did not complete.")
            check_zero_error(query(error), complete=True)
            return PowerZeroResult(channel, mode, datetime.now(UTC))

    def _power_channel(self, operation: str, channel: int) -> int:
        self._validate_channel(channel)
        return int(self._resolve_operation_parameter(operation, "channel", channel).value)

    def _power_timeout(self, operation: str, timeout_ms: int) -> int:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms < 1:
            raise ValueError("timeout_ms must be a positive integer.")
        return int(self._resolve_operation_parameter(operation, "timeout_ms", timeout_ms).value)

    def _power_register(self, response: str, field: str) -> int:
        try:
            result = int(response.strip())
            if not 0 <= result <= 32767:
                raise ValueError
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model, f"Invalid {field} register: {response!r}."
            ) from exc
        return result

    @contextmanager
    def _power_io(
        self, timeout_ms: int, *, pending_maintenance: Literal["zero", "self-test"] | None = None
    ) -> Iterator[_PowerIO]:
        """Share a deadline across I/O; clear or quarantine an ambiguous stream."""
        self._require_power_stream()
        deadline = monotonic() + timeout_ms / 1000
        armed = False
        transferring = False

        def pending(value: bool) -> None:
            nonlocal armed
            armed = value

        def remaining() -> int:
            ms = ceil((deadline - monotonic()) * 1000)
            if ms < 1:
                raise InstrumentCommunicationError(
                    self.config.model, message="Power workflow exceeded its SCPI I/O timeout."
                )
            return min(ms, timeout_ms)

        def query(command: str) -> str:
            nonlocal transferring
            budget = remaining()
            transferring = True
            result = self._query(command, skip_check=True, timeout_ms=budget)
            transferring = False
            remaining()
            return result

        def send(command: str) -> None:
            nonlocal transferring
            budget = remaining()
            transferring = True
            self._send_command(command, skip_check=True, timeout_ms=budget)
            transferring = False
            remaining()

        def query_raw(command: str) -> bytes:
            nonlocal transferring
            budget = remaining()
            transferring = True
            with self.temporary_communication_timeout(budget):
                try:
                    result = self._backend.query_raw(command)
                except Exception as exc:
                    raise InstrumentCommunicationError(
                        self.config.model, command=command, message=f"Failed to read trace: {exc}"
                    ) from exc
            if not isinstance(result, bytes):
                raise InstrumentDataError(
                    self.config.model, "Backend did not return a binary trace."
                )
            transferring = False
            remaining()
            return result

        def recover_if_uncertain(failure: BaseException) -> None:
            nonlocal armed, transferring
            if armed or transferring:
                self._recover_power_stream(failure)
                armed = transferring = False

        try:
            yield _PowerIO(query, send, pending, query_raw, remaining, recover_if_uncertain)
        except (
            InstrumentCommunicationError,
            InstrumentConfigurationError,
            InstrumentDataError,
            KeyboardInterrupt,
        ) as exc:
            if armed and pending_maintenance is not None:
                self._maintenance_outcome_uncertain = pending_maintenance
                action = (
                    "zero or zero-type change" if pending_maintenance == "zero" else "self-test"
                )
                exc.add_note(
                    f"Device Clear cannot establish whether the {action} completed. "
                    "Verify the sensor at the bench and reopen the bench before resuming. "
                    "Do not retry automatically."
                )
            recover_if_uncertain(exc)
            raise

    def _require_no_active_power_arm(self) -> None:
        if self._power_arm_active:
            raise InstrumentConfigurationError(
                self.config.model, "Use the active power arm handle until its context exits."
            )

    def _build_profile_alias(self, alias: str, **params: Any) -> list[str]:
        # Inherited SCPI paths (reset, error/status maintenance, and waits)
        # compile an alias before I/O. The armed handle uses prebuilt commands
        # and protected transport methods instead.
        self._require_no_active_power_arm()
        return super()._build_profile_alias(alias, **params)

    def write(self, cmd: str) -> None:
        self._require_no_active_power_arm()
        super().write(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        self._require_no_active_power_arm()
        return super().query(cmd, delay=delay)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        self._require_no_active_power_arm()
        return super().query_raw(cmd, delay=delay)

    def read(self) -> str:
        self._require_no_active_power_arm()
        return super().read()

    def read_raw(self) -> bytes:
        self._require_no_active_power_arm()
        return super().read_raw()

    def read_status_byte(self) -> int:
        self._require_no_active_power_arm()
        return super().read_status_byte()

    def close(self) -> None:
        self._require_no_active_power_arm()
        super().close()

    def attempt_error_recovery(self) -> bool:
        self._require_no_active_power_arm()
        return super().attempt_error_recovery()

    def _require_power_stream(self) -> None:
        self._require_no_active_power_arm()
        if self._maintenance_outcome_uncertain:
            raise InstrumentCommunicationError(
                self.config.model,
                message=f"The {self._maintenance_outcome_uncertain} outcome is uncertain. "
                "Verify the sensor at the bench and reopen the bench before resuming.",
            )
        if self._power_stream_uncertain:
            raise InstrumentCommunicationError(
                self.config.model,
                message="The sensor may still be armed or have an unread reply. "
                "Perform a device clear and reopen the bench before retrying.",
            )

    def _recover_power_stream(self, failure: BaseException) -> None:
        # An outstanding query can block SCPI ABOR and leave a late reply in
        # the stream. Use a native device clear, never *CLS or an automatic retry.
        self._power_stream_uncertain = True
        clear = getattr(self._backend, "device_clear", None)
        if callable(clear):
            try:
                with self.temporary_communication_timeout(250):
                    clear()
                self._power_stream_uncertain = False
            except (Exception, KeyboardInterrupt) as exc:
                self._logger.warning("Power meter device clear failed: %s", exc)
        if self._power_stream_uncertain:
            failure.add_note(
                "No working native Device Clear was available. The sensor may still be armed "
                "or have an unread reply. Perform a device clear and reopen the bench before retrying."
            )

    def _power_commands(self, operation: str, keys: list[str], **parameters: Any) -> list[str]:
        spec = self.config.operation_options.operation(operation)
        if spec is None or any(key not in spec.transport for key in keys):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not implement complete {operation} for this mode."
            )
        return [
            command
            for key in keys
            for command in self._build_profile_alias(spec.transport[key], **parameters)
        ]

    def _power_readback(self, operation: str, mode: PowerMode, channel: int) -> dict[str, str]:
        keys = [
            "read_format",
            "read_continuous",
            "read_unit",
            "read_correction_frequency",
            "read_detector",
            "read_feed",
            "read_trigger_source",
            "read_averaging_enabled",
            "read_auto_average",
            "read_averaging_count",
        ]
        if mode == "gated_average":
            keys += [
                "read_gate_offset",
                "read_gate_duration",
                "read_gate_edge",
                "read_gate_delay",
                "read_gate_auto_delay",
            ]
        if mode == "pulse_average":
            keys.append("read_duty_cycle_percent")
        spec = self.config.operation_options.operation(operation)
        assert spec is not None  # required by the preceding public-method preflight
        for key in (
            "read_buffered",
            "read_fast",
            "read_aux",
            "read_repetition",
            "read_trigger_count",
            "read_aperture",
            "read_buffer_size",
            "read_auto_trigger",
            "read_trigger_level",
            "read_trigger_level_unit",
            "read_trigger_sender",
            "read_trigger_sync",
            "read_duty_cycle",
            "read_rate",
        ):
            if key in spec.transport:
                keys.append(key)
        if "read_auto_trigger" in spec.transport:
            keys += ["read_gate_edge", "read_gate_delay", "read_gate_auto_delay"]
        return {key: self._power_commands(operation, [key], channel=channel)[0] for key in keys}

    def _read_power_settings(
        self,
        channel: int,
        mode: PowerMode,
        commands: dict[str, str],
        io_query: Callable[[str], str],
    ) -> PowerSettings:
        def query(key: str) -> str:
            return io_query(commands[key])

        def token(key: str) -> str:
            return " ".join(query(key).strip().strip('"').upper().split())

        def check(key: str, valid: set[str], setting: str) -> str:
            actual = token(key)
            if actual not in valid:
                raise InstrumentConfigurationError(
                    self.config.model, f"Unexpected {setting}: {actual!r}. Configure power first."
                )
            return actual

        check(
            "read_format", {"ASC", "ASCII", "ASC,0", "ASCII,0", "ASC, 0", "ASCII, 0"}, "data format"
        )
        check("read_continuous", _OFF, "continuous initiation")
        native_unit = _UNIT_TOKENS.get(token("read_unit"))
        if native_unit is None:
            raise InstrumentDataError(self.config.model, "Expected an absolute power unit.")
        correction_hz = self._number(query("read_correction_frequency"), "correction frequency")
        if correction_hz <= 0:
            raise InstrumentDataError(self.config.model, "Invalid compensation frequency.")

        averaged = {"POW:AVER", "POWER:AVERAGE", "POWER:AVER", "POW:AVERAGE"}
        if mode == "gated_average":
            detector = check("read_detector", {"NORM", "NORMAL"}, "detector")
            feed = check(
                "read_feed",
                {f"{prefix} ON SWEEP{suffix}" for prefix in averaged for suffix in ("", "1")},
                "swept average feed",
            )
            gate_offset = self._number(query("read_gate_offset"), "gate offset")
            gate_duration = self._number(query("read_gate_duration"), "gate duration")
            if not -0.15 <= gate_offset <= 0.15 or not 1e-4 <= gate_duration <= 0.15:
                raise InstrumentDataError(self.config.model, "Invalid time gate readback.")
            supported_triggers = {"external"}
            if "read_trigger_level" in commands:
                supported_triggers.add("internal")
        else:
            detector = check(
                "read_detector", {"AVER", "AVERAGE", "POW:AVG", "POWER:AVG"}, "detector"
            )
            expected_feeds = {
                "peak": {"POW:PEAK", "POWER:PEAK"},
                "random_sample": {"POW:RAND", "POWER:RAND", "POW:RANDOM", "POWER:RANDOM"},
            }
            feed = check("read_feed", expected_feeds.get(mode, averaged), f"{mode} feed")
            gate_offset = gate_duration = None
            supported_triggers = {"immediate"}
            if "read_auto_trigger" in commands:
                supported_triggers.update({"external_1", "external_2"})
                if "read_trigger_level" in commands:
                    supported_triggers.add("internal")
                check("read_auto_trigger", _OFF, "automatic trigger")
        source_token = token("read_trigger_source")
        trigger_source = _TRIGGER_TOKENS.get(source_token)
        # R&S documents EXT (with no port) as an alias for EXT1.
        if trigger_source == "external" and "read_auto_trigger" in commands:
            trigger_source = "external_1"
        if trigger_source is None or trigger_source not in supported_triggers:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Unexpected trigger source: {source_token!r}. Configure power first.",
            )
        edge = None
        delay = None
        threshold = None
        if trigger_source == "internal":
            if "read_trigger_level_unit" in commands:
                check("read_trigger_level_unit", {"DBM"}, "internal trigger level unit")
            threshold = self._number(query("read_trigger_level"), "trigger level")
        if trigger_source != "immediate":
            if trigger_source != "external_2":
                edge = _EDGE_TOKENS.get(token("read_gate_edge"))
                if edge is None:
                    raise InstrumentConfigurationError(
                        self.config.model, "Unexpected trigger edge."
                    )
            check("read_gate_auto_delay", _OFF, "automatic trigger delay")
            delay = self._verified_capture_delay(query("read_gate_delay"))

        enabled = check("read_averaging_enabled", _ON | _OFF, "averaging state") in _ON
        auto = check("read_auto_average", _ON | _OFF, "automatic averaging state") in _ON
        if not enabled and auto:
            raise InstrumentConfigurationError(
                self.config.model, "Automatic averaging is on while averaging is disabled."
            )
        averaging_mode: PowerAveraging = (
            "automatic" if auto else "manual" if enabled else "disabled"
        )
        count = self._number(query("read_averaging_count"), "averaging count")
        if count < 1 or count != int(count):
            raise InstrumentDataError(self.config.model, "Invalid averaging count.")
        n = 1
        if mode == "buffered_average":
            check("read_buffered", _ON, "buffering")
            n = self._power_register(query("read_buffer_size"), "buffer size")
            if not 2 <= n <= 8192:
                raise InstrumentDataError(self.config.model, "Invalid power buffer size.")
            if self._power_register(query("read_trigger_count"), "trigger count") != n:
                raise InstrumentConfigurationError(
                    self.config.model, "Power buffer size and trigger count disagree."
                )
        else:
            if "read_buffered" in commands:
                check("read_buffered", _OFF, "buffering")
            if "read_trigger_count" in commands:
                check("read_trigger_count", {"1", "+1"}, "trigger count")
        for key, valid, setting in (
            ("read_fast", _OFF, "fast mode"),
            ("read_aux", {"NONE"}, "auxiliary measurands"),
            ("read_repetition", {"REP", "REPEAT"}, "averaging termination"),
            ("read_rate", {"NORM", "NORMAL"}, "measurement rate"),
        ):
            if key in commands:
                check(key, valid, setting)
        duty_cycle = None
        if "read_duty_cycle" in commands:
            check(
                "read_duty_cycle", _ON if mode == "pulse_average" else _OFF, "duty-cycle correction"
            )
        if mode == "pulse_average":
            duty_cycle = self._number(query("read_duty_cycle_percent"), "duty cycle")
            if not 0.001 <= duty_cycle <= 100:
                raise InstrumentDataError(self.config.model, "Invalid duty cycle readback.")
        aperture = None
        if "read_aperture" in commands:
            aperture = self._number(query("read_aperture"), "aperture")
            if aperture <= 0:
                raise InstrumentDataError(self.config.model, "Invalid aperture.")
        return PowerSettings(
            self.config.model,
            channel,
            mode,
            correction_hz,
            int(count),
            native_unit,
            detector,
            feed,
            trigger_source,
            aperture,
            gate_offset,
            gate_duration,
            edge,
            averaging_mode,
            n,
            duty_cycle,
            threshold,
            delay,
        )

    def _power_error_code(self, response: str) -> int:
        try:
            return int(response.split(",", 1)[0].strip())
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model, f"Unexpected error status: {response!r}."
            ) from exc

    def _require_no_power_error(self, response: str) -> None:
        if self._power_error_code(response) != 0:
            raise InstrumentCommunicationError(
                self.config.model, message=f"Sensor rejected the power workflow: {response}."
            )

    def configure_sensor(
        self,
        channel: int = 1,
        freq: float | None = None,
        averaging_count: int | None = None,
        units: str | None = None,
    ) -> None:
        """Configures the settings for a specific power sensor channel.

        This method allows setting the frequency compensation, averaging count,
        and power units for the measurement.

        Args:
            channel: The sensor channel number to configure (default is 1).
            freq: The frequency compensation value in Hz.
            averaging_count: The number of measurements to average.
            units: The desired power units (e.g., "dBm", "W").
        """
        # Validate and compile all requested settings before any instrument I/O.
        self._validate_channel(channel)
        if freq is not None and (isinstance(freq, bool) or not isfinite(freq) or freq <= 0):
            raise ValueError("The correction frequency must be finite and positive.")
        if averaging_count is not None and (
            isinstance(averaging_count, bool) or not isinstance(averaging_count, int)
        ):
            raise ValueError("The averaging count must be an integer.")
        channel = int(
            self._resolve_operation_parameter("configure_sensor", "channel", channel).value
        )
        requested = {
            "freq": freq,
            "averaging_count": averaging_count,
            "units": units,
        }
        resolved: dict[str, Any] = {}
        resolved_units: Any = None
        for parameter, value in requested.items():
            if value is None:
                continue
            item = self._resolve_operation_parameter(
                "configure_sensor", parameter, value, context={"channel": channel}
            )
            if parameter == "units":
                resolved_units = item.value
            if item.alias is None or item.transport_parameter is None:
                raise InstrumentConfigurationError(
                    self.config.model, f"Missing power-meter transport for {parameter!r}."
                )
            resolved[item.alias] = {
                item.transport_parameter: item.transport_value,
                "channel": channel,
            }

        if units is not None and resolved_units not in _UNIT_TOKENS.values():
            raise InstrumentConfigurationError(self.config.model, "Invalid configured power unit.")
        commands = [
            command
            for alias, arguments in resolved.items()
            for command in self._build_profile_alias(alias, **arguments)
        ]
        if commands:
            self._ensure_backend_connected()
        with self._profile_transaction():
            self._require_power_stream()
            for command in commands:
                self._send_command(command)
            if freq is not None:
                self.config.frequency_compensation_value = freq
            if averaging_count is not None:
                self.config.averaging_count = averaging_count
            if units is not None:
                self.config.power_units = cast(PowerUnit, resolved_units)

        self._logger.info(f"Power meter sensor channel {channel} configured.")

    def read_power(self, channel: int = 1) -> float:
        """Reads the power from a specified sensor channel.

        This method queries the instrument for a power reading.

        Args:
            channel: The sensor channel number to read from (default is 1).

        Returns:
            The measured power as a float. The units depend on the current
            instrument configuration.
        """
        self._validate_channel(channel)
        channel = int(self._resolve_operation_parameter("read_power", "channel", channel).value)
        operation = self.config.operation_options.operation("read_power")
        alias = (
            operation.transport.get("fetch_power", "fetch_power") if operation else "fetch_power"
        )
        self._build_profile_alias(alias, channel=channel)
        self._ensure_backend_connected()
        with self._profile_transaction():
            self._require_power_stream()
            return self._number(self._query_profile_alias(alias, channel=channel), "power reading")

    def measure_power(self, channel: int, *, unit: PowerUnit = "dBm") -> PowerReading:
        """Acquire one new scalar average-power reading on the requested sensor.

        The profile describes the acquisition and unit/compensation readbacks.
        Conversion to the requested output unit does not change instrument
        units. No calibration, zeroing, or RF source control is performed.
        """
        self._validate_channel(channel)
        if unit not in _UNIT_TOKENS.values():
            raise ValueError("Power unit must be dBm, W, mW, or uW.")
        operation = self.config.operation_options.operation("measure_power")
        transport = {} if operation is None else operation.transport
        required = ("read_unit", "read_correction_frequency", "acquire_power")
        if not all(transport.get(name) for name in required):
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement complete fresh power acquisition."
            )
        channel = int(self._resolve_operation_parameter("measure_power", "channel", channel).value)
        active_aliases = {
            name: transport[name]
            for name in (
                *required,
                "read_format",
                "read_continuous",
                "read_quality",
                "read_buffered",
            )
            if name in transport
        }
        for alias in active_aliases.values():
            self._build_profile_alias(alias, channel=channel)

        def query(name: str) -> str:
            return self._query_profile_alias(active_aliases[name], channel=channel)

        def token(name: str) -> str:
            return query(name).strip().strip('"').upper()

        # Allocate the lazy backend only after static validation, so its resource
        # lock protects this whole workflow, including a bench's very first read.
        self._ensure_backend_connected()
        with self._profile_transaction():
            self._require_power_stream()
            reported_unit = _UNIT_TOKENS.get(token("read_unit"))
            if reported_unit is None:
                raise InstrumentDataError(self.config.model, "Expected an absolute power unit.")
            if "read_format" in active_aliases and token("read_format").split(",")[0] not in {
                "ASC",
                "ASCII",
            }:
                raise InstrumentConfigurationError(
                    self.config.model, "Select ASCII power data format."
                )
            if "read_continuous" in active_aliases and token("read_continuous") not in {"0", "OFF"}:
                raise InstrumentConfigurationError(
                    self.config.model, "Stop continuous measurement first."
                )
            if "read_buffered" in active_aliases and token("read_buffered") not in {"0", "OFF"}:
                raise InstrumentConfigurationError(
                    self.config.model, "Disable buffered power readings first."
                )
            correction_hz = self._number(query("read_correction_frequency"), "correction frequency")
            if correction_hz <= 0:
                raise InstrumentDataError(self.config.model, "Invalid compensation frequency.")
            reply = query("acquire_power")
            received_at = datetime.now(UTC)
            value = self._number(reply, "power reading")
            if "read_quality" in active_aliases and token("read_quality") not in {"0", "+0"}:
                raise InstrumentDataError(
                    self.config.model, "Sensor reports questionable power data."
                )
        return PowerReading(
            self._convert_power(value, reported_unit, unit),
            unit,
            channel,
            correction_hz,
            _model=self.config.model,
            _receipt=received_at,
        )

    @staticmethod
    def _validate_channel(channel: int) -> None:
        if isinstance(channel, bool) or not isinstance(channel, int) or channel < 1:
            raise ValueError("Sensor channel must be a positive integer.")

    def _number(self, response: str, quantity: str) -> float:
        try:
            value = float(response.strip())
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model, f"Invalid {quantity}: {response!r}."
            ) from exc
        # Sentinels (e.g. 9.9E37) are finite IEEE numbers, not RF measurements.
        if not isfinite(value) or abs(value) >= 9.9e37:
            raise InstrumentDataError(self.config.model, f"Invalid {quantity}: {response!r}.")
        return value

    def _convert_power(self, value: float, reported: PowerUnit, target: PowerUnit) -> float:
        if reported == target:
            return value
        try:
            if reported == "dBm":
                result = 10 ** ((value - 30) / 10 - log10(_WATT_SCALES[target]))
                if result == 0:
                    raise ValueError("Power magnitude underflows requested units.")
            elif target == "dBm":
                result = 10 * (log10(value) + log10(_WATT_SCALES[reported])) + 30
            else:
                result = value * (_WATT_SCALES[reported] / _WATT_SCALES[target])
        except (OverflowError, ValueError) as exc:
            raise InstrumentDataError(
                self.config.model, f"Cannot represent {value} {reported} in {target}."
            ) from exc
        if not isfinite(result):
            raise InstrumentDataError(self.config.model, f"Nonfinite power in {target}.")
        return result
