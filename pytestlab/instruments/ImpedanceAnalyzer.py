from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import Any
from typing import Literal

import polars as pl

from ..config.impedance_analyzer_config import ImpedanceAnalyzerConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ..errors import InstrumentParameterError
from ..experiments.results import MeasurementResult
from ..experiments.results import NativeMeasurementResult
from ..uncertainty import AtomRegistry
from ..uncertainty import ResultProvenance
from ..uncertainty import TraceabilityRef
from ..uncertainty import uq
from .instrument import Instrument
from .operation_contract import OperationDescriptor

_READ = "read_impedance"
_CURVE = "read_impedance_sweep"
_CONFIGURE = "configure_frequency_sweep"
_ACQUIRE = "acquire_impedance_sweep"
_MEASUREMENT = "read_measurement_sweep"
_SELECT = "configure_measurement_parameter"
_GET_SETTINGS = "get_measurement_settings"
_SET_SETTINGS = "configure_measurement_settings"
_GET_EXCITATION = "get_excitation"
_SET_EXCITATION = "configure_voltage_excitation"
_CORRECTION = "get_fixture_correction"
_FIXTURE_SETUP = "get_fixture_setup"
_READ_STANDARD = "read_fixture_standard"
_GET_LIMIT_TABLE = "get_trace_limit_table"
_GET_AREA_LIMITS = "get_area_comparator_limits"
_GET_PEAK_LIMITS = "get_peak_comparator_limits"
_GET_SEGMENTS = "get_segmented_sweep"
_SET_SEGMENT = "configure_frequency_segment"

_KEYSIGHT_SEGMENT = {
    "transfer_format": ("ASC",),
    "continuous_sweep": ("0",),
    "sweep_domain": ("SEGM",),
}


_HIOKI_PREPARED = {
    "measurement_mode": ("ANALYZER",),
    "sweep_domain": ("FREQ",),
    "sweep_trigger": ("SEQUENTIAL", "STEP"),
    "segment_mode": ("OFF",),
}
# E4990A programming help :SOUR<Ch>:VOLT lists 5 mV to 1 V.
_E4990A_SOURCE_VOLTAGE_RANGE = (0.005, 1.0)
_KEYSIGHT_HELD = {"continuous_sweep": ("0",), "sweep_domain": ("LIN", "LOG")}
_HIOKI_SEGMENT = _HIOKI_PREPARED | {"segment_mode": ("ON",)}
_HIOKI_CONTEXT_HEADERS = {
    "measurement_mode": ":MODE",
    "sweep_domain": ":SWEEP:MAIN:SOURCE",
    "sweep_trigger": ":SWEEP:TRIGGER",
    "automatic_output": ":MEASURE:OUTPUT:AUTO",
    "segment_mode": ":SEGMENT",
    "segment_count": ":SEGMENT:NUM",
    "segment_source": ":SEGMENT:SUB:SOURCE",
    "segment_limits": ":SEGMENT:START:STOP",
    "segment_level": ":SEGMENT:SUB:SOURCE:VALUE",
    "segment_range": ":SEGMENT:RANGE",
    "segment_speed": ":SEGMENT:SPEED",
    "segment_averages": ":SEGMENT:AVERAGING",
    "segment_delay": ":SEGMENT:PDELAY",
    "comparator_mode": ":COMPARATOR:ANALYZER",
    "comparator_slot": ":COMPARATOR:PARAMETER",
    "area_limits": ":COMPARATOR:AREA:LIMIT",
    "peak_limits": ":COMPARATOR:PEAK",
    "point_frequency": ":POINT",
}
_HIOKI_SEGMENT_ROW = (
    "segment_limits",
    "segment_level",
    "segment_range",
    "segment_speed",
    "segment_averages",
    "segment_delay",
)
_HIOKI_SPEED = ("FAST", "MEDIUM", "SLOW", "SLOW2")
_HIOKI_RANGE_OHM = (0.1, 1, 10, 300, 1e3, 3e3, 10e3, 30e3, 100e3, 1e6, 10e6, 100e6)
_HIOKI_RANGE = {value: index for index, value in enumerate(_HIOKI_RANGE_OHM, 1)}

_SINGLE_WRITE = re.compile(r":?[A-Za-z0-9:*]+(?: [A-Za-z0-9.,+ -]+)?")
_E4990A_CURVE = (
    "transfer_format",
    "sweep_domain",
    "continuous_sweep",
    "points",
    "segment_points",
    "trace",
    "parameter",
    "complex_format",
    "math_mode",
    "frequency_data",
    "formatted_data",
)
_IM3570_CURVE = (
    "measurement_mode",
    "sweep_domain",
    "sweep_trigger",
    "transfer_format",
    "response_fields",
    "response_header",
    "automatic_output",
    "segment_mode",
    "sweep_limits",
    "impedance_point",
)
_SCALAR_QUERY = re.compile(r":?[A-Za-z0-9:*]+\?(?: [0-9]+)?")
_HEADER = re.compile(r"\A:[A-Za-z0-9:]+[ \t]+")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")


class ImpedanceParameter(StrEnum):
    """Instrument-reported scalar measurements, not calculated from Z in Python."""

    MAGNITUDE = "magnitude"
    PHASE = "phase"
    RESISTANCE = "resistance"
    REACTANCE = "reactance"
    SERIES_INDUCTANCE = "series_inductance"
    PARALLEL_INDUCTANCE = "parallel_inductance"
    SERIES_CAPACITANCE = "series_capacitance"
    PARALLEL_CAPACITANCE = "parallel_capacitance"
    QUALITY_FACTOR = "quality_factor"
    DISSIPATION_FACTOR = "dissipation_factor"
    ADMITTANCE_MAGNITUDE = "admittance_magnitude"
    ADMITTANCE_PHASE = "admittance_phase"
    CONDUCTANCE = "conductance"
    SUSCEPTANCE = "susceptance"
    PARALLEL_RESISTANCE = "parallel_resistance"

    @property
    def unit(self) -> str:
        return _PARAMETER_CODES[self][2]


# Keysight trace selector, Hioki header label, engineering unit.
_PARAMETER_CODES = {
    ImpedanceParameter.MAGNITUDE: ("Z", "Z", "ohm"),
    ImpedanceParameter.PHASE: ("TZ", "PHASE", "deg"),
    ImpedanceParameter.RESISTANCE: ("R", "RS", "ohm"),
    ImpedanceParameter.REACTANCE: ("X", "X", "ohm"),
    ImpedanceParameter.SERIES_INDUCTANCE: ("LS", "LS", "H"),
    ImpedanceParameter.PARALLEL_INDUCTANCE: ("LP", "LP", "H"),
    ImpedanceParameter.SERIES_CAPACITANCE: ("CS", "CS", "F"),
    ImpedanceParameter.PARALLEL_CAPACITANCE: ("CP", "CP", "F"),
    ImpedanceParameter.QUALITY_FACTOR: ("Q", "Q", "1"),
    ImpedanceParameter.DISSIPATION_FACTOR: ("D", "D", "1"),
    ImpedanceParameter.ADMITTANCE_MAGNITUDE: ("Y", "Y", "S"),
    ImpedanceParameter.ADMITTANCE_PHASE: ("TY", None, "deg"),
    ImpedanceParameter.CONDUCTANCE: ("G", "G", "S"),
    ImpedanceParameter.SUSCEPTANCE: ("B", "B", "S"),
    ImpedanceParameter.PARALLEL_RESISTANCE: ("RP", "RP", "ohm"),
}
_PHASE_PARAMETERS = {ImpedanceParameter.PHASE, ImpedanceParameter.ADMITTANCE_PHASE}


def _write_sweep_csv(frame: pl.DataFrame, path: str | PathLike[str], *, overwrite: bool) -> None:
    with Path(path).open("w" if overwrite else "x", encoding="utf-8", newline="") as output:
        frame.write_csv(output)


@dataclass(frozen=True, kw_only=True)
class _ImpedanceResultMetadata:
    _model: str | None = dataclass_field(default=None, repr=False, compare=False)
    _receipt: datetime | None = dataclass_field(default=None, repr=False, compare=False)

    def _result(
        self,
        values: pl.DataFrame,
        *,
        instrument: str | None,
        kind: str,
        unit: str,
        envelope: dict[str, Any],
    ) -> MeasurementResult:
        result_type = NativeMeasurementResult if "accuracy" in envelope else MeasurementResult
        return result_type(
            values=values,
            instrument=instrument or self._model or "impedance_analyzer",
            units=unit,
            measurement_type=kind,
            timestamp=self._receipt.timestamp() if self._receipt is not None else None,
            envelope={
                "uncertainty_status": "not_evaluated",
                "timestamp_kind": "host_receipt" if self._receipt is not None else "conversion",
                **envelope,
            },
        )


@dataclass(frozen=True)
class ImpedanceMeasurementSweep(_ImpedanceResultMetadata):
    """Buffered values of one selected parameter on the native frequency axis."""

    parameter: ImpedanceParameter
    frequency_hz: tuple[float, ...]
    values: tuple[float, ...]
    channel: int
    status: tuple[int, ...] | None = None

    @property
    def unit(self) -> str:
        return self.parameter.unit

    @property
    def fresh(self) -> Literal[False]:
        """Scalar sweeps are read from the held buffer, never triggered."""
        return False

    def to_dataframe(self) -> pl.DataFrame:
        """Return one row per point in instrument order with native values and units."""
        count = len(self.frequency_hz)
        return pl.DataFrame(
            {
                "point": range(1, count + 1),
                "frequency_hz": self.frequency_hz,
                "value": self.values,
                "parameter": [self.parameter.value] * count,
                "unit": [self.unit] * count,
                "channel": [self.channel] * count,
                "status": self.status if self.status is not None else [None] * count,
                "fresh": [self.fresh] * count,
            },
            schema={
                "point": pl.Int64,
                "frequency_hz": pl.Float64,
                "value": pl.Float64,
                "parameter": pl.String,
                "unit": pl.String,
                "channel": pl.Int64,
                "status": pl.Int64,
                "fresh": pl.Boolean,
            },
        )

    def to_measurement_result(self, *, instrument: str | None = None) -> MeasurementResult:
        """Return the held native parameter trace without adding an uncertainty model."""
        return self._result(
            self.to_dataframe(),
            instrument=instrument,
            kind="impedance_parameter_sweep",
            unit=self.unit,
            envelope={
                "acquisition": "held",
                "channel": self.channel,
                "parameter": self.parameter.value,
                "column_units": {"frequency_hz": "Hz", "value": self.unit},
            },
        )

    def to_csv(self, path: str | PathLike[str], *, overwrite: bool = False) -> None:
        """Write the frame as a local CSV; existing files are not replaced by default."""
        _write_sweep_csv(self.to_dataframe(), path, overwrite=overwrite)


@dataclass(frozen=True)
class ImpedanceMeasurementSettings:
    """Verified measurement tuning; speed step 1 is fastest on either model."""

    channel: int
    speed_step: int
    averages: int
    auto_range: bool | None
    fixed_range_ohm: float | None


class ImpedanceSourceMode(StrEnum):
    """The programmed source mode, not a measurement of DUT voltage or current."""

    VOLTAGE = "voltage"
    OPEN_CIRCUIT_VOLTAGE = "open_circuit_voltage"
    CONSTANT_VOLTAGE = "constant_voltage"
    CURRENT = "current"


@dataclass(frozen=True)
class ImpedanceExcitation:
    """Programmed excitation and internal bias state, not terminal measurements."""

    channel: int
    mode: ImpedanceSourceMode
    level_v_rms: float | None
    level_a_rms: float | None
    dc_bias_enabled: bool
    level_control_enabled: bool | None


@dataclass(frozen=True)
class ImpedanceSegmentLevel:
    """One locally programmed source or bias level, not a terminal measurement."""

    mode: ImpedanceSourceMode
    value: float
    unit: Literal["V", "A", "Vrms", "Arms"]


@dataclass(frozen=True)
class ImpedanceFrequencySegment:
    """One frequency table row in instrument order (1-based)."""

    index: int
    start_hz: float
    stop_hz: float
    points: int
    spacing: Literal["linear", "log"]
    source: ImpedanceSegmentLevel | None = None
    bias: ImpedanceSegmentLevel | None = None
    speed_step: int | None = None
    averages: int | None = None
    sweep_time_s: float | None = None
    delay_s: float | None = None
    auto_range: bool | None = None
    fixed_range_ohm: float | None = None


@dataclass(frozen=True)
class ImpedanceSegmentedSweep:
    """Programmed segment table, not a measurement or calibration certificate."""

    segments: tuple[ImpedanceFrequencySegment, ...]
    channel: int

    @property
    def total_points(self) -> int:
        return sum(segment.points for segment in self.segments)


@dataclass(frozen=True)
class ImpedanceFixtureCorrection:
    """Enabled fixture corrections, not a certificate of their validity."""

    channel: int
    open_enabled: bool
    short_enabled: bool
    load_enabled: bool | None


@dataclass(frozen=True)
class ImpedanceFixtureSetup:
    """Passive fixture inspection, not evidence that a calibration is current."""

    correction: ImpedanceFixtureCorrection
    port_calibration_enabled: bool | None = None
    port_extension_enabled: bool | None = None
    port_extension_s: float | None = None
    cable_compensation_m: int | None = None
    scaling_enabled: bool | None = None
    open_mode: Literal["OFF", "ALL", "SPOT"] | None = None
    short_mode: Literal["OFF", "ALL", "SPOT"] | None = None
    ac_compensation_hz: tuple[float, float] | None = None


class ImpedanceStandardKind(StrEnum):
    """Physical calibration standard whose stored record is requested."""

    OPEN = "open"
    SHORT = "short"
    LOAD = "load"


class ImpedanceCalibrationLayer(StrEnum):
    """The distinct calibration datasets an analyzer may retain."""

    FIXTURE = "fixture"
    USER = "user"


class CompensationResult(StrEnum):
    """Last Hioki compensation flag, not provenance for retained data."""

    NORMAL = "normal"
    ABNORMAL = "abnormal"
    RANGE_UNDETERMINED = "range_undetermined"


@dataclass(frozen=True)
class ImpedanceStandardSample:
    """Stored complex standard value; 0 Hz denotes a Hioki DC record."""

    frequency_hz: float
    value: complex


@dataclass(frozen=True)
class ImpedanceFixtureStandard:
    """A retained calibration record, not proof that any correction is valid."""

    standard: ImpedanceStandardKind
    calibration_layer: ImpedanceCalibrationLayer
    channel: int
    quantity: Literal["impedance", "admittance"]
    samples: tuple[ImpedanceStandardSample, ...]
    correction_enabled: bool
    spot: int | None = None
    applied_mode: Literal["OFF", "ALL", "SPOT"] | None = None
    compensation_result_flag: CompensationResult | None = None
    zero_may_be_uncaptured: bool = False

    @property
    def unit(self) -> Literal["ohm", "S"]:
        return "S" if self.quantity == "admittance" else "ohm"

    @property
    def ac_span_hz(self) -> tuple[float, float] | None:
        """Bounds of AC records, not an interpolation or coverage guarantee."""
        ac = tuple(sample.frequency_hz for sample in self.samples if sample.frequency_hz > 0)
        return (min(ac), max(ac)) if ac else None


@dataclass(frozen=True)
class ImpedanceLimitLine:
    """One stored edge; horizontal values are in Hz before any offset."""

    kind: Literal["off", "upper", "lower"]
    start_hz: float
    stop_hz: float
    start_value: float
    stop_value: float


@dataclass(frozen=True)
class ImpedanceTraceLimitTable:
    """Stored scalar limit lines and offsets, not a pass/fail result."""

    parameter: ImpedanceParameter
    channel: int
    trace: int
    enabled: bool
    lines: tuple[ImpedanceLimitLine, ...]
    stimulus_offset_hz: float
    response_offset: float

    @property
    def unit(self) -> str:
        return self.parameter.unit


@dataclass(frozen=True)
class ImpedanceComparatorLimits:
    """One prepared Analyzer point or peak window; None marks an OFF limit."""

    parameter: ImpedanceParameter
    channel: int
    slot: int
    lower: float | None
    upper: float | None
    point: int | None = None
    frequency_hz: float | None = None
    segment: int | None = None
    peak: Literal["min", "max"] | None = None
    left_hz: float | None = None
    right_hz: float | None = None

    @property
    def unit(self) -> str:
        return self.parameter.unit


@dataclass(frozen=True, kw_only=True)
class E4990AAccuracyConditions:
    """Actual acquisition conditions for the calibrated direct front-panel 4TP plane.

    The setup reference identifies the calibration/fixture and operating conditions:
    the DUT at the calibrated plane without an extension, no applied AC magnetic
    field, and operation within the datasheet's environmental ratings.
    """

    setup_reference: str
    temperature_c: float
    warmup_minutes: float
    voltage_v_rms: float
    measurement_time: int
    dc_current_range_a: float
    dc_bias_enabled: bool


@dataclass(frozen=True, kw_only=True)
class IM3570AccuracyConditions:
    """Actual V-mode normal analyzer conditions and a fixed impedance range.

    The setup reference identifies the acquisition's calibration, valid open/short
    compensation, and noncondensing environment. It must be for the recorded data,
    not the analyzer's present-day settings.
    """

    setup_reference: str
    temperature_c: float
    relative_humidity_percent: float
    warmup_minutes: float
    voltage_v_rms: float
    range_ohm: float
    speed_step: int
    cable_length_m: float
    dc_bias_enabled: bool


ImpedanceAccuracyConditions = E4990AAccuracyConditions | IM3570AccuracyConditions

_KEYSIGHT_ACCURACY = "Keysight E4990A 5991-3890, Definitions and Equation 1"
_HIOKI_ACCURACY = "Hioki IM3570E15-62B, p. 7"
# IM3570 catalog p. 7: guaranteed ratio range and Z/phase A, B coefficients,
# 1–10 kHz column only (no interpolation into other catalog bands).
_HIOKI_ACCURACY_ROWS = {
    300: (8, 300, 0.08, 0.02, 0.05, 0.01),
    1_000: (240, 10_000, 0.1, 0.005, 0.08, 0.002),
    3_000: (800, 30_000, 0.12, 0.005, 0.08, 0.002),
    10_000: (2_400, 100_000, 0.12, 0.005, 0.08, 0.002),
    30_000: (8_000, 300_000, 0.12, 0.005, 0.08, 0.003),
}
_ACCURACY_COLUMNS = {
    "magnitude_accuracy_limit_ohm": "ohm",
    "phase_accuracy_limit_deg": "deg",
}


def _check_accuracy_setup(model: str | None, setup: ImpedanceAccuracyConditions) -> str:
    if isinstance(setup, E4990AAccuracyConditions):
        expected = "E4990A"
        reference = _KEYSIGHT_ACCURACY
    elif isinstance(setup, IM3570AccuracyConditions):
        expected = "IM3570"
        reference = _HIOKI_ACCURACY
    else:
        raise TypeError("Expected E4990AAccuracyConditions or IM3570AccuracyConditions.")
    if model != expected:
        raise ValueError("Accuracy conditions must match the model that produced this result.")
    if not isinstance(setup.setup_reference, str) or not setup.setup_reference.strip():
        raise ValueError("Provide the documented setup reference for the original acquisition.")
    # Validate source inputs rather than passing NaN/Infinity into a persisted envelope.
    fields = asdict(setup)
    if (
        any(
            type(value) not in (int, float) or not math.isfinite(value)
            for key, value in fields.items()
            if key not in {"setup_reference", "dc_bias_enabled"}
        )
        or type(setup.dc_bias_enabled) is not bool
    ):
        raise ValueError(
            "Accuracy conditions must contain finite numeric settings and actual bias state."
        )
    return reference


def _accuracy_limits(
    reading: ImpedanceReading, setup: ImpedanceAccuracyConditions
) -> tuple[float, float] | None:
    f, z = reading.frequency_hz, reading.magnitude_ohm
    if (
        not math.isfinite(f)
        or not math.isfinite(z)
        or setup.dc_bias_enabled
        or not 18 <= setup.temperature_c <= 28
    ):
        return None

    if isinstance(setup, E4990AAccuracyConditions):
        # Eq. 1, 0 m direct 4TP; the sheet marks >10 MHz typical, not guaranteed.
        # Limit this implementation to 1 Ω–1 MΩ and no more than 0.5 Vrms.
        voltage_mv = 1_000 * setup.voltage_v_rms
        dci = {0.001: 0.0, 0.01: 1e-6, 0.1: 10e-6}.get(setup.dc_current_range_a)
        speed = setup.measurement_time
        if (
            setup.warmup_minutes < 90  # Keysight 5991-3890, Definitions.
            or not 20 <= f <= 10e6
            or not 1 <= z <= 1e6
            or not 5 <= voltage_mv <= 500
            or not 1 <= speed <= 5
            or type(speed) is not int
            or dci is None
        ):
            return None
        epbw = (0.8, 0.4, 0.2, 0.06, 0.0)[speed - 1] * (1 if f < 50_000 else 0.5)
        if voltage_mv > 200:
            eposc, kzosc = 0.018 * (500 / voltage_mv - 1), 1.0
        elif voltage_mv > 100:
            eposc, kzosc = 0.018 * (200 / voltage_mv - 1), 200 / voltage_mv
        else:
            eposc = (100 / voltage_mv - 1) * (0.018 + epbw)
            kzosc = 100 / voltage_mv
        ep = 0.5 if f < 100 else 0.3 if f <= 800 else 0.075 if f <= 1e6 else 0.1 * f / 1e6
        yo = 10e-9 if f < 100 else 2.5e-9 if f <= 200_000 else 5e-9 if f <= 1e6 else 50e-9
        zs = 0.01 if f < 100 else 0.0025
        kbw = ((6, 4, 3, 1, 1) if f <= 1e6 else (10, 5, 4, 1, 1))[speed - 1]
        fraction = (ep + epbw + eposc) / 100 + kbw * (
            kzosc * zs / z + (500 / voltage_mv) * (dci + yo) * z
        )
        return z * fraction, math.degrees(fraction)

    # Hioki normal measurement, V mode; restrict the table to the covered
    # ranges and test levels with guaranteed limits in this frequency band.
    row = _HIOKI_ACCURACY_ROWS.get(setup.range_ohm)
    if (
        reading.status != 0
        or not 1_000 <= f <= 10_000
        or row is None
        or not row[0] <= z <= row[1]
        or not 0 <= setup.relative_humidity_percent <= 80
        or setup.warmup_minutes < 60
        or not (0.005 <= setup.voltage_v_rms <= 0.999 or 1 <= setup.voltage_v_rms <= 5)
        or type(setup.speed_step) is not int
        or not 1 <= setup.speed_step <= 4
        or setup.cable_length_m not in (0, 1, 2, 4)
    ):
        return None
    _, _, za, zb, pa, pb = row
    ratio = (
        abs(setup.range_ohm / z - 1)
        if setup.range_ohm <= 300
        else abs(10 * z / setup.range_ohm - 1)
    )
    c = 1 + 0.1 / setup.voltage_v_rms if setup.voltage_v_rms < 1 else 1.0
    d = (8, 4, 2, 1)[setup.speed_step - 1]
    e = {0: 1.0, 1: 1.5, 2: 2 * (1 + f / 100_000), 4: 4 * (1 + f / 100_000)}[
        int(setup.cable_length_m)
    ]
    factors = c * d * e  # F=G=1 for disabled bias and specified temperature.
    return z * (za + zb * ratio) * factors / 100, (pa + pb * ratio) * factors


def _with_accuracy(
    frame: pl.DataFrame,
    readings: tuple[ImpedanceReading, ...],
    setup: ImpedanceAccuracyConditions,
    model: str | None,
    envelope: dict[str, Any],
) -> pl.DataFrame:
    reference = _check_accuracy_setup(model, setup)
    limits = [_accuracy_limits(reading, setup) for reading in readings]
    envelope["accuracy"] = {
        "kind": "manufacturer_limit",
        "source": reference,
        "conditions_source": "caller_recorded_acquisition",
        "conditions": asdict(setup),
        "applicable_points": sum(limit is not None for limit in limits),
    }
    envelope["column_units"].update(_ACCURACY_COLUMNS)
    return frame.with_columns(
        [
            pl.Series(
                name,
                [limit[i] if limit is not None else None for limit in limits],
                dtype=pl.Float64,
            )
            for i, name in enumerate(_ACCURACY_COLUMNS)
        ]
    )


@dataclass(frozen=True)
class ImpedanceReading(_ImpedanceResultMetadata):
    """One buffered sweep point, with an instrument-reported frequency in Hz."""

    frequency_hz: float
    impedance_ohm: complex
    point: int
    channel: int
    status: int | None = None

    @property
    def magnitude_ohm(self) -> float:
        return abs(self.impedance_ohm)

    @property
    def phase_deg(self) -> float:
        return math.degrees(math.atan2(self.impedance_ohm.imag, self.impedance_ohm.real))

    def to_measurement_result(
        self,
        *,
        instrument: str | None = None,
        accuracy: ImpedanceAccuracyConditions | None = None,
        rectangular_type_b: Literal["magnitude", "phase"] | None = None,
    ) -> MeasurementResult:
        """Return complex Z and optionally one explicitly modeled Type B component."""
        envelope: dict[str, Any] = {
            "acquisition": "buffered_point",
            "channel": self.channel,
            "column_units": _IMPEDANCE_COLUMN_UNITS.copy(),
        }
        frame = _impedance_frame((self,), self.channel, fresh=None)
        if accuracy is not None:
            frame = _with_accuracy(frame, (self,), accuracy, self._model, envelope)
        if rectangular_type_b is not None:
            if rectangular_type_b not in ("magnitude", "phase") or accuracy is None:
                raise ValueError(
                    "Rectangular Type B evaluation needs a magnitude/phase choice and accuracy conditions."
                )
            if rectangular_type_b == "magnitude":
                nominal, unit, column = self.magnitude_ohm, "ohm", "magnitude_accuracy_limit_ohm"
            else:
                nominal, unit, column = self.phase_deg, "deg", "phase_accuracy_limit_deg"
            half_width = frame[column][0]
            if (
                half_width is None
                or (rectangular_type_b == "phase" and abs(nominal) + half_width >= 180)
                or (rectangular_type_b == "magnitude" and nominal <= half_width)
            ):
                raise ValueError(
                    "The point has no applicable rectangular bound in the selected coordinate."
                )
            source = envelope["accuracy"]["source"]
            quantity = uq.limit(
                nominal,
                half_width,
                unit,
                distribution="rectangular",
                label=f"Impedance {rectangular_type_b} manufacturer accuracy",
                source=source,
                traceability=TraceabilityRef(source="manufacturer_spec", reference_standard=source),
                registry=AtomRegistry(),
            )
            quantity.provenance = ResultProvenance(origin_detail=accuracy.setup_reference)
            envelope["uncertainty_status"] = "partial_type_b"
            envelope["uncertainty_component"] = rectangular_type_b
            envelope["uncertainty"] = {"kind": "quantity", "payload": quantity.to_dict()}
        return self._result(
            frame,
            instrument=instrument,
            kind="impedance_point",
            unit="ohm",
            envelope=envelope,
        )


_IMPEDANCE_COLUMN_UNITS = {
    "frequency_hz": "Hz",
    "impedance_real_ohm": "ohm",
    "impedance_imag_ohm": "ohm",
}


def _impedance_frame(
    readings: tuple[ImpedanceReading, ...], channel: int, *, fresh: bool | None
) -> pl.DataFrame:
    count = len(readings)
    return pl.DataFrame(
        {
            "point": [point.point for point in readings],
            "frequency_hz": [point.frequency_hz for point in readings],
            "impedance_real_ohm": [point.impedance_ohm.real for point in readings],
            "impedance_imag_ohm": [point.impedance_ohm.imag for point in readings],
            "channel": [channel] * count,
            "status": [point.status for point in readings],
            "fresh": [fresh] * count,
        },
        schema={
            "point": pl.Int64,
            "frequency_hz": pl.Float64,
            "impedance_real_ohm": pl.Float64,
            "impedance_imag_ohm": pl.Float64,
            "channel": pl.Int64,
            "status": pl.Int64,
            "fresh": pl.Boolean,
        },
    )


@dataclass(frozen=True)
class ImpedanceSweep(_ImpedanceResultMetadata):
    """Complete buffered frequency sweep in instrument order; no interpolation."""

    readings: tuple[ImpedanceReading, ...]
    channel: int
    fresh: bool = False

    @property
    def frequency_hz(self) -> tuple[float, ...]:
        return tuple(point.frequency_hz for point in self.readings)

    @property
    def impedance_ohm(self) -> tuple[complex, ...]:
        return tuple(point.impedance_ohm for point in self.readings)

    def to_dataframe(self) -> pl.DataFrame:
        """Return one row per point in instrument order, with complex Z split in ohms."""
        return _impedance_frame(self.readings, self.channel, fresh=self.fresh)

    def to_measurement_result(
        self, *, instrument: str | None = None, accuracy: ImpedanceAccuracyConditions | None = None
    ) -> MeasurementResult:
        """Return the native impedance table, optionally with pointwise accuracy limits."""
        envelope: dict[str, Any] = {
            "acquisition": "fresh" if self.fresh else "held",
            "channel": self.channel,
            "column_units": _IMPEDANCE_COLUMN_UNITS.copy(),
        }
        frame = self.to_dataframe()
        if accuracy is not None:
            frame = _with_accuracy(frame, self.readings, accuracy, self._model, envelope)
        return self._result(
            frame,
            instrument=instrument,
            kind="impedance_sweep",
            unit="ohm",
            envelope=envelope,
        )

    def to_csv(self, path: str | PathLike[str], *, overwrite: bool = False) -> None:
        """Write the frame as a local CSV; existing files are not replaced by default."""
        _write_sweep_csv(self.to_dataframe(), path, overwrite=overwrite)


@dataclass(frozen=True)
class ImpedanceSweepSettings:
    """Frequency sweep settings confirmed by instrument readback."""

    start_hz: float
    stop_hz: float
    points: int
    spacing: str
    channel: int


class _SweepBudget:
    """One wall-clock deadline across exchanges; late replies are not success."""

    def __init__(self, model: str, timeout_ms: int) -> None:
        self.model = model
        self.deadline = time.monotonic() + timeout_ms / 1000
        self.uncertain_stream = False

    def remaining_ms(self, command: str | None = None) -> int:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise InstrumentCommunicationError(
                self.model, command, "Impedance sweep deadline expired."
            )
        return math.ceil(remaining * 1000)

    def exchange(self, action, command: str):
        remaining_ms = self.remaining_ms(command)
        try:
            result = action(command, skip_check=True, timeout_ms=remaining_ms)
        except BaseException:
            # A transport error may leave a response pending, or the
            # instrument may still be processing a command.
            self.uncertain_stream = True
            raise
        self.remaining_ms(command)
        return result


_RECOVER_SWEEP = (
    "Stop/hold the sweep at the instrument, make the DUT safe, clear the interface "
    "and verify the front-panel state before opening a new session."
)


class ImpedanceAnalyzer(Instrument[ImpedanceAnalyzerConfig]):
    """Read, configure and, where explicitly supported, acquire impedance sweeps."""

    _sweep_io_quarantined = False

    OPERATION_CONTRACT = (
        OperationDescriptor(_READ, safety_class="read", group="measurements", scope="family"),
        OperationDescriptor(
            _CURVE, safety_class="read", required=False, group="measurements", scope="family"
        ),
        OperationDescriptor(
            _CONFIGURE,
            safety_class="state-changing",
            required=False,
            group="sweep",
            scope="family",
            direct_python_only=True,
        ),
        OperationDescriptor(
            _ACQUIRE,
            safety_class="state-changing",
            required=False,
            group="sweep",
            scope="model",
            direct_python_only=True,
        ),
        OperationDescriptor(
            _MEASUREMENT, safety_class="read", required=False, group="measurements", scope="family"
        ),
        OperationDescriptor(
            _SELECT,
            safety_class="state-changing",
            direct_python_only=True,
            required=False,
            group="measurements",
            scope="family",
        ),
        OperationDescriptor(
            _GET_SETTINGS, safety_class="read", required=False, group="setup", scope="family"
        ),
        OperationDescriptor(
            _SET_SETTINGS,
            safety_class="state-changing",
            direct_python_only=True,
            required=False,
            group="setup",
            scope="family",
        ),
        OperationDescriptor(
            _GET_EXCITATION, safety_class="read", required=False, group="excitation", scope="family"
        ),
        OperationDescriptor(
            _SET_EXCITATION,
            safety_class="state-changing",
            direct_python_only=True,
            required=False,
            group="excitation",
            scope="family",
        ),
        OperationDescriptor(
            _CORRECTION, safety_class="read", required=False, group="fixture", scope="family"
        ),
        OperationDescriptor(
            _FIXTURE_SETUP, safety_class="read", required=False, group="fixture", scope="family"
        ),
        OperationDescriptor(
            _READ_STANDARD, safety_class="read", required=False, group="fixture", scope="family"
        ),
        OperationDescriptor(
            _GET_SEGMENTS, safety_class="read", required=False, group="sweep", scope="family"
        ),
        OperationDescriptor(
            _SET_SEGMENT,
            safety_class="state-changing",
            direct_python_only=True,
            required=False,
            group="sweep",
            scope="family",
        ),
        OperationDescriptor(
            _GET_LIMIT_TABLE, safety_class="read", required=False, group="analysis", scope="model"
        ),
        OperationDescriptor(
            _GET_AREA_LIMITS, safety_class="read", required=False, group="analysis", scope="model"
        ),
        OperationDescriptor(
            _GET_PEAK_LIMITS, safety_class="read", required=False, group="analysis", scope="model"
        ),
    )

    def _readback_query(self, alias: str, point: int, channel: int, *, trace: int = 1) -> str:
        # Compile all requested aliases before any I/O. Unlike the general
        # profile-query helper, a read-only operation must never execute a
        # preparatory write or a compound SCPI program message.
        placeholders = self._scpi_engine.validate_placeholders(alias)["placeholders"]
        args = {
            key: value
            for key, value in {"point": point, "channel": channel, "trace": trace}.items()
            if key in placeholders
        }
        commands = self._build_profile_alias(alias, **args)
        response = self._scpi_engine.describe(alias).get("response") or {}
        if (
            len(commands) != 1
            or _SCALAR_QUERY.fullmatch(commands[0]) is None
            or response.get("transport", "query") != "query"
        ):
            raise InstrumentConfigurationError(
                self.config.model, "Impedance readback requires single, explicit SCPI queries."
            )
        return commands[0]

    def _number(self, text: str) -> float:
        if _NUMBER.fullmatch(text) is not None:
            value = float(text)
            if math.isfinite(value):
                return value
        raise InstrumentDataError(self.config.model, "Invalid numeric impedance response.")

    def _hioki_point_fields(self, response: str) -> tuple[float, dict[str, float], int]:
        fields = [part.strip() for part in response.split(",")]
        if len(fields) != 4:
            raise InstrumentDataError(
                self.config.model, "Expected status, frequency, impedance magnitude and phase."
            )
        status, frequency, first, second = fields
        if status != "0":
            raise InstrumentDataError(
                self.config.model, f"Impedance measurement status is not normal: {status!r}."
            )
        measurements: dict[str, float] = {}
        for field in (first, second):
            pair = field.split()
            if len(pair) != 2 or re.fullmatch(r"[A-Z]+", pair[0].upper()) is None:
                raise InstrumentDataError(
                    self.config.model, "Expected labelled impedance measurement values."
                )
            label, numeric = pair[0].upper(), pair[1]
            if label in measurements:
                raise InstrumentDataError(
                    self.config.model, "Duplicate impedance measurement label."
                )
            measurements[label] = self._number(numeric)
        return self._number(frequency), measurements, int(status)

    def _read_polar_point(self, response: str) -> tuple[float, complex, int]:
        frequency, measurements, status = self._hioki_point_fields(response)
        if tuple(measurements) != ("Z", "PHASE"):
            raise InstrumentDataError(
                self.config.model, "Expected labelled impedance magnitude (Z) and phase (PHASE)."
            )
        magnitude_value, phase_value = measurements.values()
        if magnitude_value < 0 or not -180 <= phase_value <= 180:
            raise InstrumentDataError(self.config.model, "Invalid impedance magnitude or phase.")
        radians = math.radians(phase_value)
        return (
            frequency,
            complex(magnitude_value * math.cos(radians), magnitude_value * math.sin(radians)),
            status,
        )

    def read_impedance(self, point: int = 1, *, channel: int = 1) -> ImpedanceReading:
        """Read a 1-based point from a completed frequency sweep.

        Does not trigger a sweep, alter the stimulus, wait for completion, or
        certify the age or calibration of the buffered measurement. Prepare
        the sweep on the instrument first and keep it stopped during readback.
        """
        for name, value in (("point", point), ("channel", channel)):
            if type(value) is not int or value < 1:
                raise InstrumentParameterError(
                    parameter=name, value=value, message="Expected a positive integer index."
                )
        operation = self.config.operation_options.operation(_READ)
        spec = self.config.readback
        data_keys = (
            ("frequency_data", "impedance_data")
            if spec.encoding == "complex_arrays"
            else ("impedance_point",)
        )
        required_keys = (*spec.checks, *data_keys)
        if (
            operation is None
            or not self.supports_operation(_READ)
            or not all(key in operation.transport for key in required_keys)
        ):
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement complete impedance readback."
            )
        for name, value in (("point", point), ("channel", channel)):
            self._resolve_operation_parameter(_READ, name, value)
        queries = {
            key: self._readback_query(operation.transport[key], point, channel)
            for key in required_keys
        }

        with self._impedance_transaction():
            for key, expected in spec.checks.items():
                observed = _HEADER.sub("", self._query(queries[key])).strip().upper()
                if observed not in expected:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Impedance readback requires {key} in {expected!r}; got {observed!r}.",
                    )

            if spec.encoding == "complex_arrays":
                axis = [
                    self._number(field.strip())
                    for field in self._query(queries["frequency_data"]).split(",")
                ]
                if point > len(axis):
                    raise InstrumentParameterError(
                        parameter="point", value=point, valid_range=(1, len(axis))
                    )
                reply = self._query(queries["impedance_data"])
                received_at = datetime.now(UTC)
                samples = [self._number(field.strip()) for field in reply.split(",")]
                if len(samples) != 2 * len(axis):
                    raise InstrumentDataError(
                        self.config.model,
                        "Impedance sample count does not match the frequency axis.",
                    )
                index = point - 1
                frequency = axis[index]
                impedance = complex(samples[2 * index], samples[2 * index + 1])
                status = None
            else:
                reply = self._query(queries["impedance_point"])
                received_at = datetime.now(UTC)
                frequency, impedance, status = self._read_polar_point(reply)

        return self._validated_reading(
            frequency, impedance, point, channel, status, received_at=received_at
        )

    def _sweep_profile(
        self,
        operation_name: str,
        channel: int,
        queries,
        writes=None,
        **params,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        if type(channel) is not int or channel < 1:
            raise InstrumentParameterError(
                "channel", channel, message="Expected a positive integer."
            )
        operation = self.config.operation_options.operation(operation_name)
        if (
            self.config.sweep is None
            or operation is None
            or not self.supports_operation(operation_name)
        ):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile does not support {operation_name}."
            )
        self._resolve_operation_parameter(operation_name, "channel", channel)
        if not all(key in operation.transport for key in (*queries, *(writes or ()))):
            raise InstrumentConfigurationError(
                self.config.model, f"Profile has incomplete transport for {operation_name}."
            )
        # Compile the query plan and write templates before connecting. Numeric
        # point/trace selectors are resolved to validated values at use time.
        query_plan = {
            key: self._readback_query(
                operation.transport[key], 1, channel, trace=params.get("trace", 1)
            )
            for key in queries
        }
        write_plan = {}
        for key in writes or ():
            alias = operation.transport[key]
            fields = self._scpi_engine.validate_placeholders(alias)["placeholders"]
            args = {
                name: value
                for name, value in (params | {"channel": channel}).items()
                if name in fields
            }
            commands = self._build_profile_alias(alias, **args)
            if len(commands) != 1 or _SINGLE_WRITE.fullmatch(commands[0]) is None:
                raise InstrumentConfigurationError(
                    self.config.model, "Impedance sweep requires single, explicit SCPI writes."
                )
            write_plan[key] = commands[0]
        return operation.transport, query_plan, write_plan

    def _require_sweep_session(self) -> None:
        if self._sweep_io_quarantined:
            raise InstrumentCommunicationError(
                self.config.model, message=f"Impedance session quarantined. {_RECOVER_SWEEP}"
            )

    @contextmanager
    def _impedance_transaction(self) -> Iterator[None]:
        self._require_sweep_session()
        # Connect after static validation, before taking the transaction so
        # locks on lazily built backends are visible.
        self._ensure_backend_connected()
        with self._profile_transaction():
            self._require_sweep_session()
            yield

    @staticmethod
    def _normalize_state(response: str) -> str:
        return _HEADER.sub("", response).strip().upper()

    def _state(self, command: str) -> str:
        return self._normalize_state(self._query(command, skip_check=True))

    def _require_state(
        self, query_plan, checks, *, state: Callable[[str], str] | None = None
    ) -> dict[str, str]:
        read = state or self._state
        observed = {}
        for key, allowed in checks.items():
            value = read(query_plan[key])
            if value not in allowed:
                raise InstrumentConfigurationError(
                    self.config.model,
                    f"Impedance sweep requires {key} in {allowed!r}; got {value!r}.",
                )
            observed[key] = value
        return observed

    def _integer(self, value: str, lo: int, hi: int) -> int:
        numeric = self._number(value)
        if lo <= numeric <= hi and numeric == int(numeric):
            return int(numeric)
        raise InstrumentDataError(self.config.model, f"Expected an integer in [{lo}, {hi}].")

    def _validated_reading(self, frequency, z, point, channel, status=None, *, received_at=None):
        if frequency <= 0 or abs(z) > self.config.readback.magnitude_limit_ohm:
            raise InstrumentDataError(
                self.config.model, "Nonpositive frequency or impedance beyond the profile limit."
            )
        return ImpedanceReading(
            frequency, z, point, channel, status, _model=self.config.model, _receipt=received_at
        )

    def _check_e4990a_curve_setup(self, transport, queries, channel, *, state=None) -> str:
        read = state or self._state
        observed = self._require_state(
            queries,
            {
                "transfer_format": ("ASC",),
                "sweep_domain": ("LIN", "LOG", "SEGM"),
                "continuous_sweep": ("0",),
                "complex_format": ("COMP",),
                "math_mode": ("NORM",),
            },
            state=read,
        )
        trace = self._integer(read(queries["trace"]), 1, 4)
        parameter_query = self._readback_query(transport["parameter"], 1, channel, trace=trace)
        self._require_state({"parameter": parameter_query}, {"parameter": ("IMP",)}, state=read)
        return observed["sweep_domain"]

    def _hioki_limits(
        self, query: str, channel: int, *, state: Callable[[str], str] | None = None
    ) -> ImpedanceSweepSettings:
        return self._parse_hioki_limits((state or self._state)(query), channel)

    def _parse_hioki_limits(self, reply: str, channel: int) -> ImpedanceSweepSettings:
        fields = [field.strip() for field in reply.split(",")]
        if len(fields) != 4 or fields[3] not in ("LINEAR", "LIN", "LOG"):
            raise InstrumentDataError(
                self.config.model, "Expected normal Hioki START-STOP settings."
            )
        start, stop = map(self._number, fields[:2])
        if not 0 < start < stop:
            raise InstrumentDataError(
                self.config.model, "Expected increasing START-STOP frequencies."
            )
        spec = self.config.sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Missing impedance sweep settings."
            )
        count = self._integer(fields[2], 2, spec.max_points)
        return ImpedanceSweepSettings(
            start, stop, count, "log" if fields[3] == "LOG" else "linear", channel
        )

    def _read_curve(self, transport, queries, channel, *, fresh=False, state=None):
        read = state or self._state
        spec = self.config.sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Missing impedance sweep settings."
            )
        received_at: datetime | None = None
        if spec.dialect == "e4990a":
            domain = self._check_e4990a_curve_setup(transport, queries, channel, state=read)
            count_key = "segment_points" if domain == "SEGM" else "points"
            count = self._integer(read(queries[count_key]), 1, spec.max_points)
            axis = [
                self._number(token.strip()) for token in read(queries["frequency_data"]).split(",")
            ]
            reply = read(queries["formatted_data"])
            received_at = datetime.now(UTC)
            values = [self._number(token.strip()) for token in reply.split(",")]
            if len(axis) != count or len(values) != 2 * count:
                raise InstrumentDataError(
                    self.config.model, "Impedance sample count does not match the frequency axis."
                )
            readings = tuple(
                self._validated_reading(
                    axis[i],
                    complex(values[2 * i], values[2 * i + 1]),
                    i + 1,
                    channel,
                    received_at=received_at,
                )
                for i in range(count)
            )
        else:
            self._require_state(
                queries, self.config.readback.checks | {"segment_mode": ("OFF",)}, state=read
            )
            limits = self._hioki_limits(queries["sweep_limits"], channel, state=read)
            data = []
            for point in range(1, limits.points + 1):
                command = self._readback_query(transport["impedance_point"], point, channel)
                reply = read(command)
                received_at = datetime.now(UTC)
                frequency, z, status = self._read_polar_point(reply)
                data.append(
                    self._validated_reading(
                        frequency, z, point, channel, status, received_at=received_at
                    )
                )
            readings = tuple(data)
            self._verify_hioki_axis(tuple(point.frequency_hz for point in readings), limits)
        return ImpedanceSweep(
            readings, channel, fresh, _model=self.config.model, _receipt=received_at
        )

    def _verify_hioki_axis(self, axis: tuple[float, ...], limits: ImpedanceSweepSettings) -> None:
        if not all(
            math.isclose(observed, expected, rel_tol=2e-4)
            for observed, expected in ((axis[0], limits.start_hz), (axis[-1], limits.stop_hz))
        ) or any(start > stop for start, stop in zip(axis, axis[1:], strict=False)):
            raise InstrumentDataError(
                self.config.model, "Buffered frequencies do not match START-STOP settings."
            )

    def _parameter(self, operation: str, parameter: ImpedanceParameter | str) -> ImpedanceParameter:
        resolved = self._resolve_operation_parameter(operation, "parameter", parameter)
        return ImpedanceParameter(resolved.value)

    def read_measurement_sweep(
        self, parameter: ImpedanceParameter | str, *, channel: int = 1
    ) -> ImpedanceMeasurementSweep:
        """Read a prepared, completed scalar trace in its native engineering units.

        On the E4990A the active trace must match; on the IM3570 either of the
        two labelled Analyzer parameters can match. Never selects a trace,
        triggers, or derives a scalar result from a differently labelled buffer.
        """
        parameter = self._parameter(_MEASUREMENT, parameter)
        keysight_code, hioki_code, _ = _PARAMETER_CODES[parameter]
        keysight = self.config.sweep is not None and self.config.sweep.dialect == "e4990a"
        phase_checks = (
            {"expanded_phase": ("0",), "phase_unit": ("DEG",)}
            if parameter in _PHASE_PARAMETERS
            else {}
        )
        keys = (
            (*tuple(key for key in _E4990A_CURVE if key != "complex_format"), *phase_checks)
            if keysight
            else _IM3570_CURVE
        )
        transport, queries, _ = self._sweep_profile(_MEASUREMENT, channel, keys)
        with self._impedance_transaction():
            statuses: tuple[int, ...] | None = None
            received_at: datetime | None = None
            if keysight:
                observed = self._require_state(
                    queries,
                    {
                        "transfer_format": ("ASC",),
                        "continuous_sweep": ("0",),
                        "sweep_domain": ("LIN", "LOG", "SEGM"),
                        "math_mode": ("NORM",),
                        **phase_checks,
                    },
                )
                trace = self._integer(self._state(queries["trace"]), 1, 4)
                query = self._readback_query(transport["parameter"], 1, channel, trace=trace)
                expected = (keysight_code, "RS") if keysight_code == "R" else (keysight_code,)
                self._require_state({"parameter": query}, {"parameter": expected})
                count_key = "segment_points" if observed["sweep_domain"] == "SEGM" else "points"
                count = self._integer(self._state(queries[count_key]), 1, 1601)
                axis = tuple(
                    self._number(field.strip())
                    for field in self._state(queries["frequency_data"]).split(",")
                )
                reply = self._state(queries["formatted_data"])
                received_at = datetime.now(UTC)
                values = tuple(self._number(field.strip()) for field in reply.split(","))
                if len(axis) != count or len(values) != count * 2:
                    raise InstrumentDataError(
                        self.config.model, "Scalar trace count does not match frequency axis."
                    )
                if any(values[1::2]):
                    raise InstrumentDataError(
                        self.config.model, "Expected scalar trace with zero secondary values."
                    )
                values = values[::2]
            else:
                self._require_state(queries, self.config.readback.checks | _HIOKI_PREPARED)
                limits = self._hioki_limits(queries["sweep_limits"], channel)
                points = []
                for point in range(1, limits.points + 1):
                    query = self._readback_query(transport["impedance_point"], point, channel)
                    reply = self._state(query)
                    received_at = datetime.now(UTC)
                    frequency, fields, status = self._hioki_point_fields(reply)
                    if hioki_code not in fields:
                        raise InstrumentDataError(
                            self.config.model,
                            f"Buffered point {point} does not report {hioki_code}.",
                        )
                    points.append((frequency, fields[hioki_code], status))
                axis = tuple(frequency for frequency, _, _ in points)
                self._verify_hioki_axis(axis, limits)
                values = tuple(value for _, value, _ in points)
                statuses = tuple(status for _, _, status in points)
            if (
                any(frequency <= 0 for frequency in axis)
                or any(abs(value) > 1e30 for value in values)
                or (
                    parameter is ImpedanceParameter.MAGNITUDE
                    and any(
                        not 0 <= value <= self.config.readback.magnitude_limit_ohm
                        for value in values
                    )
                )
                or (
                    parameter is ImpedanceParameter.ADMITTANCE_MAGNITUDE
                    and any(value < 0 for value in values)
                )
                or (parameter in _PHASE_PARAMETERS and any(abs(value) > 180 for value in values))
            ):
                raise InstrumentDataError(
                    self.config.model, "Scalar trace contains invalid frequencies or values."
                )
            return ImpedanceMeasurementSweep(
                parameter,
                axis,
                values,
                channel,
                statuses,
                _model=self.config.model,
                _receipt=received_at,
            )

    def configure_measurement_parameter(
        self,
        parameter: ImpedanceParameter | str,
        *,
        channel: int = 1,
        trace: int = 1,
    ) -> ImpedanceParameter | Literal["impedance"]:
        """Define and verify a trace or Analyzer display slot, without triggering.

        E4990A: defines an existing trace without activating it; use
        `parameter="impedance"` for complex IMP.
        IM3570: logical Analyzer slots 1/2 map to SCPI PARA1/PARA3.
        Set magnitude and phase in separate slots for complex readback.
        Physically disconnect the DUT before changing an IM3570 slot.
        """
        requested = self._resolve_operation_parameter(_SELECT, "parameter", parameter).value
        selected = "impedance" if requested == "impedance" else ImpedanceParameter(requested)
        self._resolve_operation_parameter(_SELECT, "trace", trace)
        if type(trace) is not int:
            raise InstrumentParameterError(
                "trace", trace, message="Expected an integer trace index."
            )
        hioki = self.config.sweep is not None and self.config.sweep.dialect == "im3570"
        if hioki:
            checks = _HIOKI_PREPARED | {"segment_mode": ("ON", "OFF")}
            code = None if selected == "impedance" else _PARAMETER_CODES[selected][1]
            if code is None:
                raise InstrumentParameterError(
                    "parameter",
                    parameter,
                    message="No IM3570 Analyzer display slot represents this parameter.",
                )
            physical_trace = 1 if trace == 1 else 3
            keys = (*checks, "dc_bias_enabled", "comparator_mode", "parameter")
        else:
            checks = _KEYSIGHT_HELD | {"sweep_domain": ("LIN", "LOG", "SEGM")}
            code = "IMP" if selected == "impedance" else _PARAMETER_CODES[selected][0]
            physical_trace = trace
            keys = (*checks, "trace_count", "parameter")
        _, queries, writes = self._sweep_profile(
            _SELECT,
            channel,
            keys,
            ("set_parameter",),
            trace=physical_trace,
            code=code,
        )
        with self._impedance_transaction():
            if hioki:
                self._require_hioki_context(queries, checks)
                self._check_hioki_configuration_guard(queries, operation="Analyzer slot setup")
                self._require_hioki_comparator_off(queries)
            else:
                self._require_state(queries, checks)
                count = self._integer(self._state(queries["trace_count"]), 1, 4)
                if not 1 <= trace <= count:
                    raise InstrumentParameterError("trace", trace, valid_range=(1, count))
            self._send_command(writes["set_parameter"])
            self._require_state(queries, {"parameter": (code,)})
            return selected

    def _settings_keys(self, *, setup: bool = False) -> tuple[str, ...]:
        if self.config.sweep is not None and self.config.sweep.dialect == "im3570":
            return (
                *_HIOKI_PREPARED,
                "speed",
                "averages",
                "range_auto",
                "range_number",
                *(("sweep_limits", "dc_bias_enabled") if setup else ()),
            )
        return (*_KEYSIGHT_HELD, "speed", "averaging", "averages")

    def _get_measurement_settings(
        self, queries: dict[str, str], channel: int, *, hioki: bool
    ) -> ImpedanceMeasurementSettings:
        state = self._state
        if hioki:
            self._require_state(queries, _HIOKI_PREPARED)
            speed = state(queries["speed"])
            if speed not in _HIOKI_SPEED:
                raise InstrumentDataError(
                    self.config.model, f"Unsupported measurement speed: {speed!r}."
                )
            raw = state(queries["averages"])
            averages = 1 if raw == "OFF" else self._integer(raw, 1, 256)
            auto = self._on_off(state(queries["range_auto"]))
            fixed = (
                None
                if auto
                else _HIOKI_RANGE_OHM[self._integer(state(queries["range_number"]), 1, 12) - 1]
            )
            return ImpedanceMeasurementSettings(
                channel, _HIOKI_SPEED.index(speed) + 1, averages, auto, fixed
            )
        self._require_state(queries, _KEYSIGHT_HELD)
        speed_step = self._integer(state(queries["speed"]), 1, 5)
        averages = (
            self._integer(state(queries["averages"]), 1, 999)
            if self._on_off(state(queries["averaging"]))
            else 1
        )
        return ImpedanceMeasurementSettings(channel, speed_step, averages, None, None)

    def _on_off(self, value: str) -> bool:
        if value in ("ON", "1"):
            return True
        if value in ("OFF", "0"):
            return False
        raise InstrumentDataError(self.config.model, f"Expected on/off readback, got {value!r}.")

    def get_measurement_settings(self, *, channel: int = 1) -> ImpedanceMeasurementSettings:
        """Read speed, effective averaging count and, on the IM3570, range."""
        keys = self._settings_keys()
        _, queries, _ = self._sweep_profile(_GET_SETTINGS, channel, keys)
        with self._impedance_transaction():
            return self._get_measurement_settings(queries, channel, hioki="range_auto" in queries)

    def configure_measurement_settings(
        self,
        *,
        speed_step: int | None = None,
        averages: int | None = None,
        range_mode: Literal["auto", "fixed"] | None = None,
        fixed_range_ohm: float | None = None,
        channel: int = 1,
    ) -> ImpedanceMeasurementSettings:
        """Apply and verify requested tuning on a held sweep with the DUT disconnected.

        Step 1 is fastest; steps are model-specific. One average means disabled.
        Only the IM3570 supports range selection here. Omitted settings are not written.
        """
        keys = self._settings_keys(setup=True)
        hioki = "range_auto" in keys
        aliases: list[str] = []
        params: dict[str, int | str] = {}
        for key, value in (("speed_step", speed_step), ("averages", averages)):
            if value is not None:
                if type(value) is not int:
                    raise InstrumentParameterError(key, value, message="Expected an integer.")
                self._resolve_operation_parameter(_SET_SETTINGS, key, value)
        if speed_step is not None:
            aliases.append("set_speed")
            params["speed"] = _HIOKI_SPEED[speed_step - 1] if hioki else speed_step
        if averages is not None:
            if hioki:
                aliases.append("set_averages")
                params["averages"] = "OFF" if averages == 1 else averages
            else:
                if averages > 1:
                    aliases.append("set_averages")
                    params["averages"] = averages
                aliases.append("set_averaging")
                params["averaging"] = "OFF" if averages == 1 else "ON"
        if range_mode is not None:
            self._resolve_operation_parameter(_SET_SETTINGS, "range_mode", range_mode)
        if range_mode == "fixed":
            if (
                fixed_range_ohm is None
                or type(fixed_range_ohm) not in (int, float)
                or fixed_range_ohm not in _HIOKI_RANGE
            ):
                raise InstrumentParameterError(
                    "fixed_range_ohm",
                    fixed_range_ohm,
                    message=f"Choose a documented fixed range: {_HIOKI_RANGE_OHM!r}.",
                )
            self._resolve_operation_parameter(_SET_SETTINGS, "fixed_range_ohm", fixed_range_ohm)
            aliases.append("set_fixed_range")
            params["range_number"] = _HIOKI_RANGE[fixed_range_ohm]
        elif fixed_range_ohm is not None:
            raise InstrumentParameterError(
                "fixed_range_ohm", fixed_range_ohm, message="Requires range_mode='fixed'."
            )
        elif range_mode == "auto":
            aliases.append("set_auto_range")
        if not aliases:
            raise InstrumentParameterError(
                "settings", None, message="Specify at least one measurement setting."
            )
        _, queries, writes = self._sweep_profile(_SET_SETTINGS, channel, keys, aliases, **params)
        with self._impedance_transaction():
            self._require_state(queries, _HIOKI_PREPARED if hioki else _KEYSIGHT_HELD)
            if hioki:
                self._check_hioki_configuration_guard(queries)
                if fixed_range_ohm is not None:
                    stop = self._hioki_limits(queries["sweep_limits"], channel).stop_hz
                    if fixed_range_ohm > self._hioki_max_fixed_range(stop):
                        raise InstrumentConfigurationError(
                            self.config.model,
                            "Fixed range exceeds the limit at the sweep stop frequency.",
                        )
            for alias in aliases:
                self._send_command(writes[alias])
            actual = self._get_measurement_settings(queries, channel, hioki=hioki)
            if (
                (speed_step is not None and speed_step != actual.speed_step)
                or (averages is not None and averages != actual.averages)
                or (range_mode == "auto" and actual.auto_range is not True)
                or (range_mode == "fixed" and fixed_range_ohm != actual.fixed_range_ohm)
            ):
                raise InstrumentConfigurationError(
                    self.config.model, f"Measurement settings did not verify: {actual!r}."
                )
            return actual

    def _excitation_keys(self, *, setup: bool = False) -> tuple[str, ...]:
        if self.config.sweep is not None and self.config.sweep.dialect == "im3570":
            return (
                *_HIOKI_PREPARED,
                "dc_bias_enabled",
                "source_level_mode",
                "source_voltage",
                "source_constant_voltage",
                "source_current",
                *(("sweep_limits",) if setup else ()),
            )
        return (
            *_KEYSIGHT_HELD,
            "bias",
            "source_mode",
            "source_alc",
            "source_voltage",
            "source_current",
        )

    def _get_excitation(
        self, queries: dict[str, str], channel: int, *, hioki: bool
    ) -> ImpedanceExcitation:
        if hioki:
            self._require_state(queries, _HIOKI_PREPARED)
            mode_response = self._state(queries["source_level_mode"])
            options = {
                "V": (ImpedanceSourceMode.OPEN_CIRCUIT_VOLTAGE, "source_voltage"),
                "CV": (ImpedanceSourceMode.CONSTANT_VOLTAGE, "source_constant_voltage"),
                "CC": (ImpedanceSourceMode.CURRENT, "source_current"),
            }
            bias = self._on_off(self._state(queries["dc_bias_enabled"]))
            alc = None
        else:
            self._require_state(queries, _KEYSIGHT_HELD)
            mode_response = self._state(queries["source_mode"])
            options = {
                "VOLT": (ImpedanceSourceMode.VOLTAGE, "source_voltage"),
                "CURR": (ImpedanceSourceMode.CURRENT, "source_current"),
            }
            bias = self._on_off(self._state(queries["bias"]))
            alc = self._on_off(self._state(queries["source_alc"]))
        if mode_response not in options:
            raise InstrumentDataError(
                self.config.model, f"Unexpected source mode: {mode_response!r}."
            )
        mode, alias = options[mode_response]
        level = self._number(self._state(queries[alias]))
        if level <= 0:
            raise InstrumentDataError(
                self.config.model, "Expected a positive programmed source level."
            )
        is_current = mode is ImpedanceSourceMode.CURRENT
        return ImpedanceExcitation(
            channel, mode, None if is_current else level, level if is_current else None, bias, alc
        )

    def get_excitation(self, *, channel: int = 1) -> ImpedanceExcitation:
        """Read the programmed AC mode/level and internal bias state on a held sweep."""
        _, queries, _ = self._sweep_profile(_GET_EXCITATION, channel, self._excitation_keys())
        with self._impedance_transaction():
            return self._get_excitation(queries, channel, hioki="source_level_mode" in queries)

    def configure_voltage_excitation(
        self,
        level_v_rms: float,
        *,
        channel: int = 1,
    ) -> ImpedanceExcitation:
        """Set and verify voltage in an already prepared, bias-off voltage mode.

        Never changes source mode or bias. Physically disconnect the DUT and
        external bias sources first; verify actual terminal output separately.
        """
        if type(level_v_rms) not in (int, float) or not 0.005 <= level_v_rms <= 1:
            raise InstrumentParameterError("level_v_rms", level_v_rms, valid_range=(0.005, 1))
        self._resolve_operation_parameter(_SET_EXCITATION, "level_v_rms", level_v_rms)
        keys = self._excitation_keys(setup=True)
        _, queries, writes = self._sweep_profile(
            _SET_EXCITATION, channel, keys, ("set_voltage",), level=f"{level_v_rms:.15g}"
        )
        hioki = "source_level_mode" in queries
        with self._impedance_transaction():
            if hioki:
                self._require_state(queries, _HIOKI_PREPARED)
                self._check_hioki_configuration_guard(queries, operation="voltage level setup")
                if (
                    self._hioki_limits(queries["sweep_limits"], channel).stop_hz > 1e6
                    and level_v_rms < 0.01
                ):
                    raise InstrumentParameterError(
                        "level_v_rms",
                        level_v_rms,
                        message="IM3570 requires at least 0.010 Vrms above 1 MHz.",
                    )
            else:
                self._require_state(
                    queries,
                    _KEYSIGHT_HELD
                    | {"source_mode": ("VOLT",), "source_alc": ("0",), "bias": ("0",)},
                )
            self._send_command(writes["set_voltage"])
            actual = self._get_excitation(queries, channel, hioki=hioki)
            if (
                actual.dc_bias_enabled
                or actual.level_control_enabled
                or actual.mode
                is not (
                    ImpedanceSourceMode.OPEN_CIRCUIT_VOLTAGE
                    if hioki
                    else ImpedanceSourceMode.VOLTAGE
                )
                or actual.level_v_rms is None
                or not 0.005 <= actual.level_v_rms <= 1
                or not math.isclose(actual.level_v_rms, level_v_rms, abs_tol=0.0005)
            ):
                raise InstrumentConfigurationError(
                    self.config.model, f"Voltage excitation did not verify: {actual!r}."
                )
            return actual

    @staticmethod
    def _hioki_max_fixed_range(stop_hz: float) -> float:
        return 100e3 if stop_hz > 1e6 else (10e6 if stop_hz > 100e3 else 100e6)

    def _headerless_state(self, command: str) -> str:
        return self._query(command, skip_check=True).strip().upper()

    def _hioki_context_state(self, key: str, command: str) -> str:
        raw = self._headerless_state(command)
        parts = raw.split(maxsplit=1)
        expected = _HIOKI_CONTEXT_HEADERS[key]
        if len(parts) == 2 and (
            parts[0] == expected or (key == "segment_count" and parts[0] == expected[1:])
        ):
            return parts[1]
        if raw.startswith(":"):
            raise InstrumentConfigurationError(
                self.config.model, f"Unexpected Hioki response header for {key}: {raw!r}."
            )
        return raw

    def _require_hioki_context(
        self, queries: dict[str, str], checks: dict[str, tuple[str, ...]]
    ) -> None:
        for key, allowed in checks.items():
            value = self._hioki_context_state(key, queries[key])
            if value not in allowed:
                raise InstrumentConfigurationError(
                    self.config.model, f"Hioki setup requires {key} in {allowed!r}; got {value!r}."
                )

    def _require_hioki_comparator_off(self, queries: dict[str, str]) -> None:
        mode = self._hioki_context_state("comparator_mode", queries["comparator_mode"])
        if mode != "OFF":
            raise InstrumentConfigurationError(
                self.config.model, f"Hioki setup requires Comparator OFF; got {mode!r}."
            )

    def _segment_query_keys(self) -> tuple[str, ...]:
        if self.config.sweep is not None and self.config.sweep.dialect == "im3570":
            return (*_HIOKI_SEGMENT, "segment_count", "segment_source", *_HIOKI_SEGMENT_ROW)
        return (*_KEYSIGHT_SEGMENT, "segment_table", "segment_points")

    def _validate_segment_table(
        self, table: ImpedanceSegmentedSweep, *, reported_total: int | None = None
    ) -> None:
        spec = self.config.sweep
        if spec is None or any(
            not spec.min_frequency_hz <= row.start_hz <= row.stop_hz <= spec.max_frequency_hz
            for row in table.segments
        ):
            raise InstrumentDataError(self.config.model, "Invalid segment frequency bounds.")
        if table.total_points > spec.max_points or (
            reported_total is not None and table.total_points != reported_total
        ):
            raise InstrumentDataError(self.config.model, "Invalid segmented sweep point total.")

    def _decode_e4990a_segments(
        self, raw: str, channel: int
    ) -> tuple[ImpedanceSegmentedSweep, list[str], int]:
        spec = self.config.sweep
        if spec is None or spec.max_segments is None:
            raise InstrumentConfigurationError(self.config.model, "Profile has no segment limits.")
        tokens = [value.strip() for value in raw.split(",")]
        if len(tokens) < 12 or self._integer(tokens[0], 7, 7) != 7:
            raise InstrumentDataError(self.config.model, "Invalid E4990A segment-table header.")
        center_span = self._integer(tokens[1], 0, 1) == 1
        osc, bias, speed, averages, sweep_time, delay = (
            self._integer(value, 0, 1) for value in tokens[2:8]
        )
        count = self._integer(tokens[8], 1, spec.max_segments)
        width = 3 + 2 * osc + 2 * bias + speed + averages + sweep_time + delay
        if len(tokens) != 9 + count * width:
            raise InstrumentDataError(
                self.config.model, "Invalid E4990A segment-table field count."
            )

        rows = []
        for index in range(count):
            row = tokens[9 + index * width : 9 + (index + 1) * width]
            start, stop = self._number(row[0]), self._number(row[1])
            if center_span:
                start, stop = start - stop / 2, start + stop / 2
            points = self._integer(row[2], 1, spec.max_points)
            extra = iter(row[3:])
            excitation = None
            dc = None
            if osc:
                current = self._integer(next(extra), 0, 1) == 1
                level = self._number(next(extra))
                if level <= 0:
                    raise InstrumentDataError(
                        self.config.model, "Invalid segment oscillator level."
                    )
                excitation = ImpedanceSegmentLevel(
                    ImpedanceSourceMode.CURRENT if current else ImpedanceSourceMode.VOLTAGE,
                    level,
                    "Arms" if current else "Vrms",
                )
            if bias:
                current = self._integer(next(extra), 0, 1) == 1
                dc = ImpedanceSegmentLevel(
                    ImpedanceSourceMode.CURRENT if current else ImpedanceSourceMode.VOLTAGE,
                    self._number(next(extra)),
                    "A" if current else "V",
                )
            step = self._integer(next(extra), 1, 5) if speed else None
            avg = self._integer(next(extra), 1, 999) if averages else None
            sweep = self._number(next(extra)) if sweep_time else None
            pause = self._number(next(extra)) if delay else None
            if (sweep is not None and sweep < 0) or (pause is not None and pause < 0):
                raise InstrumentDataError(self.config.model, "Segment time or delay is negative.")
            rows.append(
                ImpedanceFrequencySegment(
                    index + 1,
                    start,
                    stop,
                    points,
                    "linear",
                    excitation,
                    dc,
                    speed_step=step,
                    averages=avg,
                    sweep_time_s=sweep,
                    delay_s=pause,
                )
            )
        return ImpedanceSegmentedSweep(tuple(rows), channel), tokens, width

    def _read_hioki_segment_table(
        self, transport: dict[str, str], queries: dict[str, str], channel: int
    ) -> ImpedanceSegmentedSweep:
        spec = self.config.sweep
        if spec is None or spec.max_segments is None:
            raise InstrumentConfigurationError(self.config.model, "Profile has no segment limits.")
        count = self._integer(
            self._hioki_context_state("segment_count", queries["segment_count"]),
            1,
            spec.max_segments,
        )
        modes = {
            "V": ImpedanceSourceMode.OPEN_CIRCUIT_VOLTAGE,
            "CV": ImpedanceSourceMode.CONSTANT_VOLTAGE,
            "CC": ImpedanceSourceMode.CURRENT,
        }
        mode = modes.get(self._hioki_context_state("segment_source", queries["segment_source"]))
        if mode is None:
            raise InstrumentDataError(self.config.model, "Unknown Hioki segment source mode.")
        rows = []
        for index in range(1, count + 1):

            def state(key: str, index: int = index) -> str:
                command = self._readback_query(transport[key], index, channel)
                return self._hioki_context_state(key, command)

            limits = self._parse_hioki_limits(state("segment_limits"), channel)
            level = self._number(state("segment_level"))
            speed = state("segment_speed")
            auto_or_range = state("segment_range")
            avg = state("segment_averages")
            pause = self._number(state("segment_delay"))
            if level <= 0 or speed not in _HIOKI_SPEED or not 0 <= pause <= 10_000:
                raise InstrumentDataError(self.config.model, "Invalid Hioki segment settings.")
            auto = auto_or_range == "AUTO"
            rows.append(
                ImpedanceFrequencySegment(
                    index,
                    limits.start_hz,
                    limits.stop_hz,
                    limits.points,
                    "log" if limits.spacing == "log" else "linear",
                    source=ImpedanceSegmentLevel(
                        mode, level, "Arms" if mode is ImpedanceSourceMode.CURRENT else "Vrms"
                    ),
                    speed_step=_HIOKI_SPEED.index(speed) + 1,
                    averages=1 if avg == "OFF" else self._integer(avg, 1, 256),
                    delay_s=pause,
                    auto_range=auto,
                    fixed_range_ohm=None
                    if auto
                    else _HIOKI_RANGE_OHM[self._integer(auto_or_range, 1, 12) - 1],
                )
            )
        return ImpedanceSegmentedSweep(tuple(rows), channel)

    def _segment_snapshot(
        self, transport: dict[str, str], queries: dict[str, str], channel: int
    ) -> tuple[ImpedanceSegmentedSweep, list[str], int]:
        if "segment_count" in queries:
            self._require_hioki_context(queries, _HIOKI_SEGMENT)
            table = self._read_hioki_segment_table(transport, queries, channel)
            self._validate_segment_table(table)
            return table, [], 0
        self._require_state(queries, _KEYSIGHT_SEGMENT, state=self._headerless_state)
        table, tokens, width = self._decode_e4990a_segments(
            self._headerless_state(queries["segment_table"]), channel
        )
        total = self._integer(self._headerless_state(queries["segment_points"]), 1, 1601)
        self._validate_segment_table(table, reported_total=total)
        return table, tokens, width

    def get_segmented_sweep(self, *, channel: int = 1) -> ImpedanceSegmentedSweep:
        """Inspect the active, held frequency segment table without triggering."""
        transport, queries, _ = self._sweep_profile(
            _GET_SEGMENTS, channel, self._segment_query_keys()
        )
        with self._impedance_transaction():
            return self._segment_snapshot(transport, queries, channel)[0]

    def configure_frequency_segment(
        self,
        index: int,
        start_hz: float,
        stop_hz: float,
        points: int,
        *,
        spacing: Literal["linear", "log"] = "linear",
        channel: int = 1,
    ) -> ImpedanceFrequencySegment:
        """Edit one existing row in a held frequency segment table.

        Physically disconnect the DUT and isolate external bias first. Does not
        activate segmentation, insert/delete rows, change source fields, or
        trigger. IM3570 requires the instrument to be independently verified idle
        with external triggers isolated, bias and Comparator OFF, V source, and
        both the existing and proposed table wholly at or below 1 MHz.
        An edit can invalidate stored comparator limits even when OFF. E4990A
        requires both list oscillator and list bias disabled.
        """
        spec = self.config.sweep
        if spec is None or spec.max_segments is None:
            raise InstrumentConfigurationError(self.config.model, "Profile has no segment limits.")
        hioki = spec.dialect == "im3570"
        spacing = self._resolve_operation_parameter(_SET_SEGMENT, "spacing", spacing).value
        for key, value in (("index", index), ("points", points)):
            if type(value) is not int:
                raise InstrumentParameterError(key, value, message="Expected an integer.")
            self._resolve_operation_parameter(_SET_SEGMENT, key, value)
        for key, value in (("start_hz", start_hz), ("stop_hz", stop_hz)):
            if type(value) not in (int, float):
                raise InstrumentParameterError(key, value, message="Expected a frequency in Hz.")
            self._resolve_operation_parameter(_SET_SEGMENT, key, value)
        if start_hz >= stop_hz:
            raise InstrumentParameterError("stop_hz", stop_hz, message="Must exceed start_hz.")

        # The E4990A command consumes an entire table. Validate this alias with
        # a numeric placeholder before I/O, then recompile with the verified table.
        aliases = ("set_segment_row",) if hioki else ("set_segment_table",)
        options = {
            "point": index,
            "start": f"{start_hz:.15g}",
            "stop": f"{stop_hz:.15g}",
            "points": points,
            "spacing": "LOG" if spacing == "log" else "LIN",
            "table": "7",
        }
        guards = (
            ("dc_bias_enabled", "comparator_mode")
            if hioki
            else ("bias", "min_frequency", "max_frequency")
        )
        keys = (*self._segment_query_keys(), *guards)
        transport, queries, commands = self._sweep_profile(
            _SET_SEGMENT, channel, keys, aliases, **options
        )
        with self._impedance_transaction():
            table, tokens, width = self._segment_snapshot(transport, queries, channel)
            if not 1 <= index <= len(table.segments):
                raise InstrumentParameterError("index", index, valid_range=(1, len(table.segments)))
            old = table.segments[index - 1]
            if table.total_points - old.points + points > spec.max_points:
                raise InstrumentParameterError(
                    "points", points, message="Segment table would exceed its total point limit."
                )
            update = replace(
                old, start_hz=start_hz, stop_hz=stop_hz, points=points, spacing=spacing
            )
            expected_rows = table.segments[: index - 1] + (update,) + table.segments[index:]
            if hioki:
                self._check_hioki_configuration_guard(queries, operation="segment setup")
                self._require_hioki_comparator_off(queries)
                source = self._hioki_context_state("segment_source", queries["segment_source"])
                if source != "V":
                    raise InstrumentConfigurationError(
                        self.config.model, "IM3570 segment setup requires verified V source mode."
                    )
                if any(row.stop_hz > 1_000_000 for row in (*table.segments, *expected_rows)):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "IM3570 segment editing is limited to tables at or below 1 MHz.",
                    )
                if (
                    old.fixed_range_ohm is not None
                    and old.fixed_range_ohm > self._hioki_max_fixed_range(stop_hz)
                ):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "The fixed range is not supported at the new stop frequency.",
                    )
                self._send_command(commands["set_segment_row"])
            else:
                self._require_state(queries, {"bias": ("0",)}, state=self._headerless_state)
                if any(row.source is not None or row.bias is not None for row in table.segments):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Disable list oscillator and list bias before segment editing.",
                    )
                lower = self._number(self._headerless_state(queries["min_frequency"]))
                upper = self._number(self._headerless_state(queries["max_frequency"]))
                if not lower <= start_hz < stop_hz <= upper:
                    raise InstrumentParameterError(
                        "start_hz/stop_hz", (start_hz, stop_hz), valid_range=(lower, upper)
                    )
                offset = 9 + (index - 1) * width
                if self._integer(tokens[1], 0, 1) == 1:
                    coordinates = ((start_hz + stop_hz) / 2, stop_hz - start_hz)
                else:
                    coordinates = (start_hz, stop_hz)
                tokens[offset : offset + 3] = [f"{value:.15g}" for value in coordinates] + [
                    str(points)
                ]
                _, _, commands = self._sweep_profile(
                    _SET_SEGMENT, channel, (), aliases, table=",".join(tokens)
                )
                self._send_command(commands["set_segment_table"])

            actual_table, _, _ = self._segment_snapshot(transport, queries, channel)
            if len(actual_table.segments) != len(expected_rows):
                raise InstrumentConfigurationError(
                    self.config.model, "Segment count changed unexpectedly."
                )
            actual = actual_table.segments[index - 1]
            same_other_rows = actual_table.segments[: index - 1] + actual_table.segments[
                index:
            ] == (table.segments[: index - 1] + table.segments[index:])
            if (
                not same_other_rows
                or replace(actual, start_hz=start_hz, stop_hz=stop_hz) != update
                or not all(
                    math.isclose(value, requested, rel_tol=5e-5 if hioki else 1e-8, abs_tol=0.001)
                    for value, requested in ((actual.start_hz, start_hz), (actual.stop_hz, stop_hz))
                )
                or (hioki and actual.stop_hz > 1_000_000)
            ):
                raise InstrumentConfigurationError(
                    self.config.model, "Segment table did not verify after editing."
                )
            return actual

    def _fixture_keys(self, *, detailed: bool = False) -> tuple[str, ...]:
        if self.config.sweep is not None and self.config.sweep.dialect == "im3570":
            return (
                "measurement_mode",
                "correction_open",
                "correction_short",
                *(
                    ("correction_cable", "correction_scaling", "correction_band")
                    if detailed
                    else ()
                ),
            )
        return (
            "correction_open",
            "correction_short",
            "correction_load",
            *(("port_calibration", "port_extension", "port_extension_time") if detailed else ()),
        )

    def _read_fixture(
        self, queries: dict[str, str], channel: int, *, detailed: bool
    ) -> ImpedanceFixtureSetup:
        if "measurement_mode" not in queries:
            correction = ImpedanceFixtureCorrection(
                channel,
                self._on_off(self._state(queries["correction_open"])),
                self._on_off(self._state(queries["correction_short"])),
                self._on_off(self._state(queries["correction_load"])),
            )
            if not detailed:
                return ImpedanceFixtureSetup(correction)
            port_cal = self._on_off(self._state(queries["port_calibration"]))
            delay_on = self._on_off(self._state(queries["port_extension"]))
            delay_s = (
                self._number(self._state(queries["port_extension_time"])) if delay_on else None
            )
            return ImpedanceFixtureSetup(
                correction,
                port_calibration_enabled=port_cal,
                port_extension_enabled=delay_on,
                port_extension_s=delay_s,
            )

        self._require_state(queries, {"measurement_mode": ("ANALYZER",)})
        open_mode = self._state(queries["correction_open"])
        short_mode = self._state(queries["correction_short"])
        if open_mode not in ("OFF", "ALL", "SPOT") or short_mode not in ("OFF", "ALL", "SPOT"):
            raise InstrumentDataError(self.config.model, "Unexpected IM3570 correction mode.")
        # LOAD:RETurn? is documented only for LCR, not ANALYZER.
        correction = ImpedanceFixtureCorrection(
            channel, open_mode != "OFF", short_mode != "OFF", None
        )
        if not detailed:
            return ImpedanceFixtureSetup(correction)
        cable_m = self._integer(self._state(queries["correction_cable"]), 0, 1)
        scaling = self._on_off(self._state(queries["correction_scaling"]))
        band = [
            self._number(value.strip())
            for value in self._state(queries["correction_band"]).split(",")
        ]
        if len(band) != 2 or not 4 <= band[0] <= band[1] <= 5_000_000:
            raise InstrumentDataError(self.config.model, "Invalid IM3570 AC compensation range.")
        return ImpedanceFixtureSetup(
            correction,
            cable_compensation_m=cable_m,
            scaling_enabled=scaling,
            open_mode=open_mode,
            short_mode=short_mode,
            ac_compensation_hz=(band[0], band[1]),
        )

    def get_fixture_correction(self, *, channel: int = 1) -> ImpedanceFixtureCorrection:
        """Read fixture correction flags; IM3570 Analyzer load state is unavailable."""
        _, queries, _ = self._sweep_profile(_CORRECTION, channel, self._fixture_keys())
        with self._impedance_transaction():
            return self._read_fixture(queries, channel, detailed=False).correction

    def get_fixture_setup(self, *, channel: int = 1) -> ImpedanceFixtureSetup:
        """Read prepared fixture settings without measuring or collecting any standards."""
        _, queries, _ = self._sweep_profile(
            _FIXTURE_SETUP, channel, self._fixture_keys(detailed=True)
        )
        with self._impedance_transaction():
            return self._read_fixture(queries, channel, detailed=True)

    def _fixture_standard_sample(
        self, frequency: float, real: float, imag: float, *, allow_dc: bool
    ) -> ImpedanceStandardSample:
        spec = self.config.sweep
        if (
            spec is None
            or not (
                (allow_dc and frequency == 0)
                or spec.min_frequency_hz <= frequency <= spec.max_frequency_hz
            )
            or abs(real) > 1e30
            or abs(imag) > 1e30
        ):
            raise InstrumentDataError(self.config.model, "Invalid retained calibration sample.")
        return ImpedanceStandardSample(frequency, complex(real, imag))

    def _read_e4990a_standard(
        self, standard: ImpedanceStandardKind, layer: ImpedanceCalibrationLayer, channel: int
    ) -> ImpedanceFixtureStandard:
        spec = self.config.sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile has no calibration bounds."
            )
        fixture = layer is ImpedanceCalibrationLayer.FIXTURE
        prefix = f"fixture_{standard}" if fixture else "user"
        count_key = f"{prefix}_count"
        axis_key = f"{prefix}_frequency"
        data_key = f"{layer}_{standard}_values"
        enabled_key = f"correction_{standard}" if fixture else "port_calibration"
        checks = {"transfer_format": ("ASC",), "continuous_sweep": ("0",)}
        _, queries, _ = self._sweep_profile(
            _READ_STANDARD,
            channel,
            (*checks, count_key, axis_key, data_key, enabled_key),
        )
        with self._impedance_transaction():
            self._require_state(queries, checks, state=self._headerless_state)
            count = self._integer(self._headerless_state(queries[count_key]), 0, spec.max_points)
            enabled = self._on_off(self._headerless_state(queries[enabled_key]))
            if count == 0:
                samples: tuple[ImpedanceStandardSample, ...] = ()
            else:
                frequency = self._headerless_state(queries[axis_key]).split(",")
                values = self._headerless_state(queries[data_key]).split(",")
                if len(frequency) != count or len(values) != count * 2:
                    raise InstrumentDataError(
                        self.config.model, "Calibration axis and stored standard counts disagree."
                    )
                samples = tuple(
                    self._fixture_standard_sample(
                        self._number(frequency[index].strip()),
                        self._number(values[2 * index].strip()),
                        self._number(values[2 * index + 1].strip()),
                        allow_dc=False,
                    )
                    for index in range(count)
                )
            return ImpedanceFixtureStandard(standard, layer, channel, "impedance", samples, enabled)

    def _read_hioki_standard(
        self, standard: ImpedanceStandardKind, channel: int, slot: int | None
    ) -> ImpedanceFixtureStandard:
        spec = self.config.sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile has no calibration bounds."
            )
        kind = "OPEN" if standard is ImpedanceStandardKind.OPEN else "SHORT"
        correction = f"correction_{standard}"
        flag = f"fixture_{standard}_result"
        data = f"fixture_{standard}_all" if slot is None else f"fixture_{standard}_spot"
        checks = {
            "measurement_mode": ("ANALYZER",),
            "sweep_trigger": ("SEQUENTIAL", "STEP"),
            "automatic_output": ("OFF",),
        }
        transport, queries, _ = self._sweep_profile(
            _READ_STANDARD, channel, (*checks, correction, flag, data)
        )
        if slot is not None:
            queries[data] = self._readback_query(transport[data], slot, channel)
        with self._impedance_transaction():
            self._require_hioki_context(queries, checks)
            # The mode and failure flag have command headers when HEAD is ON.
            # The sample records expressly do not.
            raw = self._headerless_state(queries[correction])
            raw = re.sub(rf"^:CORRECTION:{kind}:RETURN[ 	]+", "", raw)
            if raw not in ("OFF", "ALL", "SPOT"):
                raise InstrumentDataError(
                    self.config.model, "Invalid Hioki standard correction mode."
                )
            status = self._headerless_state(queries[flag])
            code = self._integer(re.sub(rf"^:CORRECTION:{kind}:ERROR[ 	]+", "", status), 0, 2)
            result = (
                CompensationResult.NORMAL,
                CompensationResult.ABNORMAL,
                CompensationResult.RANGE_UNDETERMINED,
            )[code]
            tokens = tuple(
                field.strip() for field in self._headerless_state(queries[data]).split(",")
            )
            if slot is not None:
                if len(tokens) != 3:
                    raise InstrumentDataError(self.config.model, "Expected one Hioki SPOT record.")
                if tokens[0] == "OFF":
                    # Disabled slots can retain old numeric values; do not attach
                    # them to a fictitious DC or AC frequency.
                    self._number(tokens[1])
                    self._number(tokens[2])
                    tokens = ()
            elif not (0 < len(tokens) <= 3 * spec.max_points and len(tokens) % 3 == 0):
                raise InstrumentDataError(
                    self.config.model, "Malformed Hioki ALL calibration records."
                )
            samples = tuple(
                self._fixture_standard_sample(
                    self._number(tokens[index]),
                    self._number(tokens[index + 1]),
                    self._number(tokens[index + 2]),
                    allow_dc=True,
                )
                for index in range(0, len(tokens), 3)
            )
            return ImpedanceFixtureStandard(
                standard,
                ImpedanceCalibrationLayer.FIXTURE,
                channel,
                "admittance" if standard is ImpedanceStandardKind.OPEN else "impedance",
                samples,
                raw != "OFF",
                spot=slot,
                applied_mode=raw,
                compensation_result_flag=result,
                zero_may_be_uncaptured=True,
            )

    def read_fixture_standard(
        self,
        standard: ImpedanceStandardKind | str,
        *,
        calibration_layer: ImpedanceCalibrationLayer | str = ImpedanceCalibrationLayer.FIXTURE,
        spot: int | None = None,
        channel: int = 1,
    ) -> ImpedanceFixtureStandard:
        """Select and inspect a previously stored standard without collecting it.

        Stop the sweep and complete any physical calibration on the instrument
        first. On E4990A, inspect fixture or user-calibration impedance arrays
        (OPEN, SHORT or LOAD). On IM3570 Analyzer, inspect retained ALL or one
        SPOT (1–5) for OPEN or SHORT; OPEN is conductance + j*susceptance,
        not impedance. 0 Hz marks DC. A disabled SPOT has no stored samples
        exposed by this API. A stored zero may be uncaptured on the IM3570.
        This does not change what is applied, establish age, or validate standards.
        """
        selected = ImpedanceStandardKind(
            self._resolve_operation_parameter(_READ_STANDARD, "standard", standard).value
        )
        layer = ImpedanceCalibrationLayer(
            self._resolve_operation_parameter(
                _READ_STANDARD, "calibration_layer", calibration_layer
            ).value
        )
        if spot is not None:
            if type(spot) is not int:
                raise InstrumentParameterError("spot", spot, message="Expected a 1-based integer.")
            self._resolve_operation_parameter(_READ_STANDARD, "spot", spot)
        if self.config.sweep is not None and self.config.sweep.dialect == "im3570":
            if (
                layer is not ImpedanceCalibrationLayer.FIXTURE
                or selected is ImpedanceStandardKind.LOAD
            ):
                raise InstrumentParameterError(
                    "standard/calibration_layer",
                    (selected, layer),
                    message="IM3570 Analyzer supports only fixture OPEN and SHORT records.",
                )
            return self._read_hioki_standard(selected, channel, spot)
        if spot is not None:
            raise InstrumentParameterError(
                "spot", spot, message="E4990A calibration data has no SPOT index."
            )
        return self._read_e4990a_standard(selected, layer, channel)

    def get_trace_limit_table(
        self,
        parameter: ImpedanceParameter | str,
        *,
        channel: int = 1,
    ) -> ImpedanceTraceLimitTable:
        """Read the held E4990A scalar trace's stored frequency limit table and offsets."""
        parameter = self._parameter(_GET_LIMIT_TABLE, parameter)
        phase_checks = (
            {"expanded_phase": ("0",), "phase_unit": ("DEG",)}
            if parameter in _PHASE_PARAMETERS
            else {}
        )
        checks = {
            "transfer_format": ("ASC",),
            "continuous_sweep": ("0",),
            "sweep_domain": ("LIN", "LOG", "SEGM"),
            "math_mode": ("NORM",),
            **phase_checks,
        }
        transport, queries, _ = self._sweep_profile(
            _GET_LIMIT_TABLE,
            channel,
            (
                *checks,
                "trace",
                "parameter",
                "limit_enabled",
                "limit_table",
                "limit_stim_offset",
                "limit_response_offset",
            ),
        )
        read = self._headerless_state
        expected = _PARAMETER_CODES[parameter][0]
        allowed = (expected, "RS") if expected == "R" else (expected,)

        def context() -> tuple[dict[str, str], int, str]:
            states = self._require_state(queries, checks, state=read)
            trace = self._integer(read(queries["trace"]), 1, 4)
            definition = self._readback_query(transport["parameter"], 1, channel, trace=trace)
            parameter_state = self._require_state(
                {"parameter": definition}, {"parameter": allowed}, state=read
            )["parameter"]
            return states, trace, parameter_state

        with self._impedance_transaction():
            initial = context()
            _, trace, _ = initial
            enabled = self._on_off(read(queries["limit_enabled"]))
            fields = [item.strip() for item in read(queries["limit_table"]).split(",")]
            length = self._integer(fields[0], 0, 100)
            if len(fields) != 1 + 5 * length:
                raise InstrumentDataError(
                    self.config.model, "Invalid E4990A limit table field count."
                )
            lines = []
            for index in range(length):
                tag, left, right, start, stop = fields[1 + 5 * index : 6 + 5 * index]
                kind = ("off", "upper", "lower")[self._integer(tag, 0, 2)]
                left_hz, right_hz = self._number(left), self._number(right)
                start_value, stop_value = self._number(start), self._number(stop)
                # Stored breakpoint limits are larger than the installed
                # measurement band; changing sweep range leaves them intact.
                if any(abs(value) > 500e9 for value in (left_hz, right_hz)) or any(
                    abs(value) > 500e6 for value in (start_value, stop_value)
                ):
                    raise InstrumentDataError(
                        self.config.model, "Invalid E4990A limit-line bounds."
                    )
                lines.append(ImpedanceLimitLine(kind, left_hz, right_hz, start_value, stop_value))
            stimulus_offset = self._number(read(queries["limit_stim_offset"]))
            response_offset = self._number(read(queries["limit_response_offset"]))
            if context() != initial:
                raise InstrumentConfigurationError(
                    self.config.model, "E4990A trace context changed during limit-table readback."
                )
            return ImpedanceTraceLimitTable(
                parameter, channel, trace, enabled, tuple(lines), stimulus_offset, response_offset
            )

    def _comparator_query(
        self,
        transport: dict[str, str],
        key: str,
        index: int,
        slot: int,
        *,
        extremum: Literal["MIN", "MAX"] | None = None,
    ) -> str:
        alias = transport.get(key)
        if alias is None:
            raise InstrumentConfigurationError(self.config.model, f"Profile lacks {key} query.")
        tail = f"{index},{slot}" if extremum is None else f"{index},{slot},{extremum}"
        args: dict[str, int | str] = {"point": index, "slot": slot}
        if extremum is not None:
            args["extremum"] = extremum
        commands = self._build_profile_alias(alias, **args)
        response = self._scpi_engine.describe(alias).get("response") or {}
        if (
            len(commands) != 1
            or re.fullmatch(r":?[A-Za-z0-9:*]+\? " + re.escape(tail), commands[0]) is None
            or response.get("transport", "query") != "query"
        ):
            raise InstrumentConfigurationError(
                self.config.model, "Comparator readback requires one explicit indexed SCPI query."
            )
        return commands[0]

    def _read_comparator_parameter(self, queries: dict[str, str], slot: int) -> ImpedanceParameter:
        selected = self._hioki_context_state("comparator_slot", queries["comparator_slot"])
        if selected not in (str(slot), "ALL"):
            raise InstrumentConfigurationError(
                self.config.model, f"Analyzer slot {slot} is not selected for comparator judgment."
            )
        raw = self._headerless_state(queries["parameter"])
        tag = 1 if slot == 1 else 3
        token = re.sub(rf"^:PARAMETER{tag}[ 	]+", "", raw)
        for parameter, (_, code, _) in _PARAMETER_CODES.items():
            if code == token:
                return parameter
        raise InstrumentDataError(
            self.config.model, f"Unrecognized analyzer display parameter {raw!r}."
        )

    def _optional_limit_number(self, value: str) -> float | None:
        return None if value == "OFF" else self._number(value)

    def _validate_limit_order(self, lower: float | None, upper: float | None) -> None:
        if lower is not None and upper is not None and lower > upper:
            raise InstrumentDataError(self.config.model, "Comparator limit order is inverted.")

    def get_area_comparator_limits(
        self,
        point: int,
        *,
        slot: int = 1,
        channel: int = 1,
    ) -> ImpedanceComparatorLimits:
        """Read the Hioki normal frequency sweep's configured AREA limits at one point."""
        for name, index in (("point", point), ("slot", slot)):
            if type(index) is not int:
                raise InstrumentParameterError(name, index, message="Expected a 1-based integer.")
            self._resolve_operation_parameter(_GET_AREA_LIMITS, name, index)
        checks = _HIOKI_PREPARED | {"comparator_mode": ("AREA",), "automatic_output": ("OFF",)}
        transport, queries, _ = self._sweep_profile(
            _GET_AREA_LIMITS,
            channel,
            (*checks, "sweep_limits", "comparator_slot", "parameter", "point_frequency"),
            trace=1 if slot == 1 else 3,
        )
        point_query = self._readback_query(transport["point_frequency"], point, channel)
        limit_query = self._comparator_query(transport, "area_limits", point, slot)
        with self._impedance_transaction():
            self._require_hioki_context(queries, checks)
            settings = self._hioki_limits(queries["sweep_limits"], channel)
            if point > settings.points:
                raise InstrumentParameterError("point", point, valid_range=(1, settings.points))
            parameter = self._read_comparator_parameter(queries, slot)
            frequency = self._number(self._hioki_context_state("point_frequency", point_query))
            if not 4 <= frequency <= 5_000_000:
                raise InstrumentDataError(
                    self.config.model, "Invalid Hioki comparator point frequency."
                )
            fields = [
                item.strip()
                for item in self._hioki_context_state("area_limits", limit_query).split(",")
            ]
            if len(fields) != 2:
                raise InstrumentDataError(
                    self.config.model, "Expected Hioki AREA lower and upper limits."
                )
            lower, upper = map(self._optional_limit_number, fields)
            self._validate_limit_order(lower, upper)
            return ImpedanceComparatorLimits(
                parameter, channel, slot, lower, upper, point=point, frequency_hz=frequency
            )

    def get_peak_comparator_limits(
        self,
        *,
        segment: int = 1,
        slot: int = 1,
        peak: Literal["min", "max"] = "max",
        channel: int = 1,
    ) -> ImpedanceComparatorLimits:
        """Read the Hioki configured PEAK frequency window and scalar limits; does not find a peak."""
        for name, index in (("segment", segment), ("slot", slot)):
            if type(index) is not int:
                raise InstrumentParameterError(name, index, message="Expected a 1-based integer.")
            self._resolve_operation_parameter(_GET_PEAK_LIMITS, name, index)
        peak = self._resolve_operation_parameter(_GET_PEAK_LIMITS, "peak", peak).value
        checks = _HIOKI_PREPARED | {
            "segment_mode": ("OFF", "ON"),
            "comparator_mode": ("PEAK",),
            "automatic_output": ("OFF",),
        }
        transport, queries, _ = self._sweep_profile(
            _GET_PEAK_LIMITS,
            channel,
            (*checks, "segment_count", "comparator_slot", "parameter"),
            trace=1 if slot == 1 else 3,
        )
        command = self._comparator_query(
            transport, "peak_limits", segment, slot, extremum="MIN" if peak == "min" else "MAX"
        )
        with self._impedance_transaction():
            self._require_hioki_context(queries, checks)
            segments = 1
            if self._hioki_context_state("segment_mode", queries["segment_mode"]) == "ON":
                segments = self._integer(
                    self._hioki_context_state("segment_count", queries["segment_count"]), 1, 20
                )
            if segment > segments:
                raise InstrumentParameterError("segment", segment, valid_range=(1, segments))
            parameter = self._read_comparator_parameter(queries, slot)
            fields = [
                item.strip()
                for item in self._hioki_context_state("peak_limits", command).split(",")
            ]
            if len(fields) != 4:
                raise InstrumentDataError(
                    self.config.model, "Expected four Hioki PEAK limit fields."
                )
            left, right, lower, upper = map(self._optional_limit_number, fields)
            if any(value is not None and not 4 <= value <= 5_000_000 for value in (left, right)):
                raise InstrumentDataError(
                    self.config.model, "Invalid Hioki peak comparison frequency window."
                )
            self._validate_limit_order(left, right)
            self._validate_limit_order(lower, upper)
            return ImpedanceComparatorLimits(
                parameter,
                channel,
                slot,
                lower,
                upper,
                segment=segment,
                peak=peak,
                left_hz=left,
                right_hz=right,
            )

    def read_impedance_sweep(self, *, channel: int = 1) -> ImpedanceSweep:
        """Read a completed frequency sweep without writing or triggering.

        Hold the instrument and keep the front panel unchanged. This does not
        establish buffer age or certify fixture compensation.
        """
        spec = self.config.sweep
        keys = _E4990A_CURVE if spec and spec.dialect == "e4990a" else _IM3570_CURVE
        transport, queries, _ = self._sweep_profile(_CURVE, channel, keys)
        with self._impedance_transaction():
            return self._read_curve(transport, queries, channel)

    def configure_frequency_sweep(
        self,
        start_hz: float,
        stop_hz: float,
        points: int,
        *,
        spacing: str = "log",
        channel: int = 1,
    ) -> ImpedanceSweepSettings:
        """Set and verify a normal frequency sweep with the DUT physically disconnected.

        This does not write source or bias settings, arm or trigger a sweep, or
        erase calibration. A frequency change can alter instrument drive or
        cause output; it does not make the test terminals safe to touch.
        """
        spec = self.config.sweep
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model, "No frequency sweep configuration."
            )
        for name, value in (("start_hz", start_hz), ("stop_hz", stop_hz)):
            if (
                type(value) not in (int, float)
                or not spec.min_frequency_hz <= value <= spec.max_frequency_hz
            ):
                raise InstrumentParameterError(
                    name, value, valid_range=(spec.min_frequency_hz, spec.max_frequency_hz)
                )
        if start_hz >= stop_hz:
            raise InstrumentParameterError(
                "stop_hz", stop_hz, message="Must be greater than start_hz."
            )
        if type(points) is not int or not 2 <= points <= spec.max_points:
            raise InstrumentParameterError("points", points, valid_range=(2, spec.max_points))
        if spacing not in ("linear", "log"):
            raise InstrumentParameterError(
                "spacing", spacing, message="Expected 'linear' or 'log'."
            )

        keysight = spec.dialect == "e4990a"
        hioki_high_band = not keysight and stop_hz > 1_000_000
        code = "LOG" if spacing == "log" else "LIN"
        keys = (
            (
                "sweep_domain",
                "continuous_sweep",
                "min_frequency",
                "max_frequency",
                "start",
                "stop",
                "points",
            )
            if keysight
            else (
                "measurement_mode",
                "sweep_domain",
                "sweep_trigger",
                "segment_mode",
                "sweep_limits",
                "dc_bias_enabled",
                "comparator_mode",
                *(("source_level_mode",) if hioki_high_band else ()),
            )
        )
        writes = (
            ("set_sweep_type", "set_start", "set_stop", "set_points")
            if keysight
            else ("set_sweep_limits",)
        )
        _, queries, commands = self._sweep_profile(
            _CONFIGURE,
            channel,
            keys,
            writes,
            spacing=code,
            start=f"{start_hz:.15g}",
            stop=f"{stop_hz:.15g}",
            points=points,
        )
        with self._impedance_transaction():
            if keysight:
                self._require_state(
                    queries, {"continuous_sweep": ("0",), "sweep_domain": ("LIN", "LOG")}
                )
                minimum = self._number(self._state(queries["min_frequency"]))
                maximum = self._number(self._state(queries["max_frequency"]))
                if not minimum <= start_hz < stop_hz <= maximum:
                    raise InstrumentParameterError(
                        "start_hz/stop_hz", (start_hz, stop_hz), valid_range=(minimum, maximum)
                    )
                old_stop = self._number(self._state(queries["stop"]))
                order = (
                    ("set_stop", "set_start") if start_hz >= old_stop else ("set_start", "set_stop")
                )
                for key in ("set_sweep_type", *order, "set_points"):
                    self._send_command(commands[key])
                self._require_state(queries, {"sweep_domain": (code,), "continuous_sweep": ("0",)})
                actual = ImpedanceSweepSettings(
                    self._number(self._state(queries["start"])),
                    self._number(self._state(queries["stop"])),
                    self._integer(self._state(queries["points"]), 2, spec.max_points),
                    spacing,
                    channel,
                )
            else:
                self._require_hioki_context(queries, _HIOKI_PREPARED)
                self._check_hioki_configuration_guard(queries)
                self._require_hioki_comparator_off(queries)
                self._send_command(commands["set_sweep_limits"])
                actual = self._hioki_limits(queries["sweep_limits"], channel)
                if not hioki_high_band and actual.stop_hz > 1_000_000:
                    raise InstrumentConfigurationError(
                        self.config.model, "IM3570 readback unexpectedly extends above 1 MHz."
                    )

            # Vendor quantization is visible in the returned values. Reject
            # gross clamps, a wrong sweep type, or a different number of points.
            if (
                actual.points != points
                or actual.spacing != spacing
                or not all(
                    math.isclose(value, requested, rel_tol=5e-5, abs_tol=0.001)
                    for value, requested in ((actual.start_hz, start_hz), (actual.stop_hz, stop_hz))
                )
            ):
                raise InstrumentConfigurationError(
                    self.config.model, f"Frequency sweep settings did not verify: {actual!r}."
                )
            return actual

    def _check_hioki_configuration_guard(
        self,
        queries: dict[str, str],
        *,
        operation: str = "frequency configuration above 1 MHz",
    ) -> None:
        # Accept the documented field with or without its optional header.
        # Unlike generic state normalization, do not strip unrelated headers.
        bias = self._query(queries["dc_bias_enabled"], skip_check=True).upper()
        if not re.fullmatch(r"(?::DCBIAS[ \t]+)?OFF", bias):
            raise InstrumentConfigurationError(
                self.config.model,
                f"IM3570 frequency configuration requires verified DC bias OFF; got {bias!r}.",
            )
        if "source_level_mode" in queries:
            mode = self._query(queries["source_level_mode"], skip_check=True).upper()
            if not re.fullmatch(r"(?::LEVEL[ \t]+)?V", mode):
                raise InstrumentConfigurationError(
                    self.config.model,
                    f"IM3570 {operation} requires verified open-circuit voltage mode (V); "
                    f"got {mode!r}.",
                )

    def acquire_impedance_sweep(
        self,
        *,
        max_excitation_v_rms: float | None = None,
        channel: int = 1,
        timeout_ms: int = 30_000,
    ) -> ImpedanceSweep:
        """Trigger one prepared, bias-off E4990A sweep with bounded voltage.

        Only call after checking the DUT, source impedance, fixture and external
        circuitry. This does not enable DC bias or change the AC source level.
        The optional `max_excitation_v_rms` can lower the profile setpoint
        ceiling; neither limit measures or guarantees the DUT terminal voltage.
        The timeout is one budget for all acquisition exchanges. It is not a
        hardware interlock; a failed or blocked transport may leave the DUT active.
        The IM3570 supports buffered readback only: its status event register
        does not establish that the whole newly triggered sweep is complete.
        """
        spec = self.config.sweep
        if (
            not self.supports_operation(_ACQUIRE)
            or spec is None
            or spec.dialect != "e4990a"
            or spec.max_excitation_v_rms is None
        ):
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not support fresh impedance sweeps."
            )
        native_minimum, native_maximum = _E4990A_SOURCE_VOLTAGE_RANGE
        ceiling = min(spec.max_excitation_v_rms, native_maximum)
        if max_excitation_v_rms is not None:
            if (
                type(max_excitation_v_rms) not in (int, float)
                or not 0 < max_excitation_v_rms <= ceiling
            ):
                raise InstrumentParameterError(
                    "max_excitation_v_rms",
                    max_excitation_v_rms,
                    message=f"Use a positive voltage ceiling no greater than {ceiling} Vrms.",
                )
            ceiling = max_excitation_v_rms
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 120_000:
            raise InstrumentParameterError("timeout_ms", timeout_ms, valid_range=(1, 120_000))

        checks = {
            "active_channel": (str(channel),),
            "trigger_source": ("BUS",),
            "trigger_scope": ("ACT",),
            "point_trigger": ("0",),
            "averaging": ("0",),
            "sweep_averaging": ("0",),
            "bias": ("0",),
            "source_mode": ("VOLT",),
            "source_alc": ("0",),
            "sweep_domain": ("LIN", "LOG"),
        }
        transport, queries, writes = self._sweep_profile(
            _ACQUIRE,
            channel,
            (*_E4990A_CURVE, *checks, "source_voltage", "operation_complete", "get_error"),
            ("arm_sweep", "trigger_sweep", "hold_sweep", "abort_sweep"),
        )
        with self._impedance_transaction():
            budget = _SweepBudget(self.config.model, timeout_ms)

            def state(command: str) -> str:
                return self._normalize_state(budget.exchange(self._query, command))

            may_be_armed = False
            try:
                self._check_e4990a_curve_setup(transport, queries, channel, state=state)
                self._require_state(queries, checks, state=state)
                voltage = self._number(state(queries["source_voltage"]))
                if not native_minimum <= voltage <= ceiling:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Existing source voltage {voltage} Vrms exceeds the permitted excitation or is invalid.",
                    )
                self._require_no_sweep_error(state(queries["get_error"]))
                budget.remaining_ms()
                may_be_armed = True
                budget.exchange(self._send_command, writes["arm_sweep"])
                self._require_state(
                    queries,
                    {
                        "continuous_sweep": ("1",),
                        "active_channel": (str(channel),),
                        "trigger_source": ("BUS",),
                        "trigger_scope": ("ACT",),
                    },
                    state=state,
                )
                self._require_no_sweep_error(state(queries["get_error"]))
                budget.exchange(self._send_command, writes["trigger_sweep"])
                if state(queries["operation_complete"]) not in ("1", "+1"):
                    raise InstrumentDataError(
                        self.config.model, "Sweep completion was not confirmed."
                    )
                self._require_no_sweep_error(state(queries["get_error"]))
                budget.exchange(self._send_command, writes["hold_sweep"])
                self._require_state(queries, {"continuous_sweep": ("0",)}, state=state)
                self._require_no_sweep_error(state(queries["get_error"]))
                may_be_armed = False
                result = self._read_curve(transport, queries, channel, fresh=True, state=state)
                budget.remaining_ms()
                return result
            except BaseException as error:
                if may_be_armed or budget.uncertain_stream:
                    self._recover_failed_sweep(
                        error,
                        queries,
                        writes,
                        may_be_armed=may_be_armed,
                        uncertain_stream=budget.uncertain_stream,
                    )
                raise

    def _recover_failed_sweep(
        self,
        error: BaseException,
        queries,
        writes,
        *,
        may_be_armed,
        uncertain_stream,
    ) -> None:
        # Use an independent, short best-effort cleanup budget. A SCPI write or
        # query is not a synchronization barrier for an ambiguous *OPC? reply.
        self._sweep_io_quarantined = True
        cleanup = _SweepBudget(self.config.model, 1000)
        try:
            if uncertain_stream:
                backend = self._backend
                # A backend must explicitly implement native interface clear.
                # Never substitute *CLS or read/drain an unknown reply.
                native_clear = getattr(backend, "device_clear", None)
                if not callable(getattr(type(backend), "device_clear", None)) or not callable(
                    native_clear
                ):
                    error.add_note(
                        f"Analyzer session quarantined; native interface clear unavailable. {_RECOVER_SWEEP}"
                    )
                    return
                with self.temporary_communication_timeout(cleanup.remaining_ms()):
                    native_clear()
                cleanup.remaining_ms()
            if may_be_armed:
                cleanup.exchange(self._send_command, writes["abort_sweep"])
                cleanup.exchange(self._send_command, writes["hold_sweep"])
                hold = self._normalize_state(
                    cleanup.exchange(self._query, queries["continuous_sweep"])
                )
                if hold != "0":
                    raise InstrumentDataError(self.config.model, "Could not verify analyzer hold.")
                reply = self._normalize_state(cleanup.exchange(self._query, queries["get_error"]))
                self._require_no_sweep_error(reply)
        except BaseException as cleanup_error:
            error.add_note(
                f"Analyzer session quarantined; cleanup failed: {cleanup_error}. {_RECOVER_SWEEP}"
            )
        else:
            self._sweep_io_quarantined = False
            if may_be_armed:
                error.add_note(
                    "The driver sent ABORt and verified analyzer hold; verify DUT state before retrying."
                )

    def _require_no_sweep_error(self, reply: str) -> None:
        if re.fullmatch(r'[+]?0\s*,\s*".*"', reply) is None:
            raise InstrumentDataError(self.config.model, f"Analyzer reported an error: {reply!r}.")
