import csv
import json
import math
import re
import time
from bisect import bisect_left
from bisect import bisect_right
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Sequence
from contextlib import contextmanager
from contextlib import nullcontext
from contextlib import suppress
from copy import copy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from numbers import Real
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from ..config.vna_config import CMT_READBACK_QUERIES
from ..config.vna_config import VNA_READBACK_QUERIES
from ..config.vna_config import CMTHeldReadbackConfig
from ..config.vna_config import VNAConfig
from ..config.vna_config import VNAReadbackConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ._e5071c_sweep import _RECOVER
from ._e5071c_sweep import acquire
from ._vna_context import ContextPlan
from ._vna_context import VNAChannelContext as VNAChannelContext
from ._vna_context import VNAFrequencyMarker as VNAFrequencyMarker
from ._vna_context import VNATraceContext as VNATraceContext
from ._vna_context import build_context_plan
from ._vna_context import build_marker_plan
from ._vna_context import observe_context
from ._vna_context import observe_marker
from ._vna_inventory import VNAFrequencyLimits as VNAFrequencyLimits
from ._vna_inventory import VNAInstrumentInventory as VNAInstrumentInventory
from ._vna_inventory import build_inventory_plan
from ._vna_inventory import observe_inventory
from ._vna_segments import VNASegmentTable as VNASegmentTable
from ._vna_segments import VNASweepSegment as VNASweepSegment
from ._vna_segments import build_segment_plan
from ._vna_segments import observe_segment_table
from ._vna_segments import segment_table_line_limit
from ._vna_uncertainty import snapshot_components
from .instrument import Instrument
from .operation_contract import OperationDescriptor

if TYPE_CHECKING:
    from numpy.typing import ArrayLike

    from ..experiments.results import MeasurementResult
    from ..uncertainty import QuantityArray

_SCPI_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


@dataclass(frozen=True)
class VNASweepSettings:
    """Live settings for one frequency-domain VNA channel, not trace provenance."""

    channel: int
    sweep_type: Literal["linear", "log"]
    start_freq: float
    stop_freq: float
    num_points: int
    if_bandwidth: float
    power_level: float | None  # dBm setpoint, only when port powers are coupled.
    s_params: tuple[str, ...]  # Every configured trace, in instrument slot order.
    rf_output_enabled: bool
    continuous: bool
    active_trace_correction_enabled: bool
    frequency_offset_enabled: bool
    fixture_simulator_enabled: bool


@dataclass(frozen=True)
class SParameterBin:
    """A complex sample and its actual instrument-reported frequency in Hz."""

    parameter: str
    frequency_hz: float
    value: complex

    @property
    def magnitude_db(self) -> float:
        """20 log10 of the S-parameter magnitude; zero is negative infinity."""
        return _magnitude_db(self.value)

    @property
    def phase_deg(self) -> float | None:
        """Principal phase in degrees, or None for a zero-magnitude sample."""
        if self.value == 0:
            return None
        return math.degrees(math.atan2(self.value.imag, self.value.real))


def _magnitude_db(sample: complex) -> float:
    large = max(abs(sample.real), abs(sample.imag))
    if large == 0:
        return -math.inf
    small = min(abs(sample.real), abs(sample.imag))
    return 20 * (math.log10(large) + math.log10(1 + (small / large) ** 2) / 2)


@dataclass(frozen=True)
class SParameterBandExtrema:
    """Lowest and highest magnitudes at actually measured bins within a band."""

    minimum: SParameterBin
    maximum: SParameterBin


@dataclass(frozen=True)
class SParameterTrace:
    """A named complex trace with its frequency axis and acquisition provenance."""

    parameter: str
    frequencies: tuple[float, ...]
    values: tuple[complex, ...]
    axis_source: Literal["profile_nominal", "instrument"]
    trace_identity_verified: bool
    fresh: bool
    context: VNATraceContext | None = None

    def at_frequency(self, frequency_hz: float) -> SParameterBin:
        """Return the nearest measured bin; ties prefer the lower frequency.

        Does not interpolate or extrapolate. A nominal profile axis or an
        unverified trace identity cannot identify a measured bin.
        """
        if self.axis_source != "instrument" or not self.trace_identity_verified:
            raise ValueError("Measured-bin lookup requires an instrument axis and verified trace.")
        if (
            not self.frequencies
            or not isinstance(frequency_hz, Real)
            or isinstance(frequency_hz, bool)
            or not self.frequencies[0] <= frequency_hz <= self.frequencies[-1]
        ):
            raise ValueError("Requested frequency must be finite and within the measured span.")
        target = float(frequency_hz)
        index = bisect_left(self.frequencies, target)
        if index and target - self.frequencies[index - 1] <= (self.frequencies[index] - target):
            index -= 1
        return SParameterBin(self.parameter, self.frequencies[index], self.values[index])

    def magnitude_extrema(
        self, *, start_hz: float | None = None, stop_hz: float | None = None
    ) -> SParameterBandExtrema:
        """Find measured-bin minimum and maximum magnitude in an inclusive band.

        Defaults to the full measured span. Ties favor the lower frequency.
        No interpolation, instrument markers, or extrapolation is involved.
        """
        if (
            self.axis_source != "instrument"
            or not self.trace_identity_verified
            or not self.frequencies
        ):
            raise ValueError("Magnitude extrema require an instrument axis and verified trace.")
        start = self.frequencies[0] if start_hz is None else start_hz
        stop = self.frequencies[-1] if stop_hz is None else stop_hz
        if any(
            isinstance(value, bool) or not isinstance(value, Real) for value in (start, stop)
        ) or not (self.frequencies[0] <= start <= stop <= self.frequencies[-1]):
            raise ValueError("Magnitude extrema require an ordered band within the measured span.")
        first = bisect_left(self.frequencies, float(start))
        end = bisect_right(self.frequencies, float(stop))
        if first == end:
            raise ValueError("No measured frequency bins lie within the requested band.")
        indexed_magnitudes = tuple(_magnitude_db(self.values[i]) for i in range(first, end))
        lo = first + indexed_magnitudes.index(min(indexed_magnitudes))
        hi = first + indexed_magnitudes.index(max(indexed_magnitudes))
        return SParameterBandExtrema(
            SParameterBin(self.parameter, self.frequencies[lo], self.values[lo]),
            SParameterBin(self.parameter, self.frequencies[hi], self.values[hi]),
        )


class SParameterData:
    """S-parameters and their axis with explicit readback provenance."""

    def __init__(
        self,
        frequencies: list[float],
        s_params: list[list[complex]],
        param_names: list[str],
        *,
        axis_source: Literal["profile_nominal", "instrument"] = "profile_nominal",
        trace_identity_verified: bool = False,
    ):
        self.frequencies = frequencies
        self.s_params = s_params
        self.param_names = param_names
        self.axis_source = axis_source
        self.trace_identity_verified = trace_identity_verified
        self.fresh = False
        self._fresh_sweep_type: Literal["linear", "log"] | None = None
        self.context: VNAChannelContext | None = None
        self._result_received_at = time.time()
        self._capture_model: str | None = None
        self._capture_identity: dict[str, str] | None = None
        self._capture_channel: int | None = None
        self._capture_trace_slots: dict[str, int] | None = None
        self._capture_sweep_type: Literal["linear", "log"] | None = None
        self._capture_context: VNAChannelContext | None = None
        self._capture_payload: (
            tuple[tuple[float, ...], tuple[str, ...], tuple[tuple[complex, ...], ...]] | None
        ) = None
        self._capture_axis_source: Literal["profile_nominal", "instrument"] = "profile_nominal"
        self._capture_trace_identity_verified = False
        self._uncertainty_payload: str | None = None
        self._uncertainty_evidence: tuple[str, str] | None = None
        self._verified_payload: (
            tuple[
                VNAChannelContext,
                tuple[float, ...],
                tuple[str, ...],
                tuple[tuple[complex, ...], ...],
            ]
            | None
        ) = None

    @property
    def sweep_type(self) -> Literal["linear", "log"] | None:
        """Observed frequency sweep type, when verified during readout or acquisition."""
        if self._fresh_sweep_type is not None:
            return self._fresh_sweep_type
        return self.context.sweep_type if self.context is not None else None

    def _record_capture(
        self,
        model: str,
        *,
        identity: list[str] | None = None,
        channel: int | None = None,
        mode: str | None = None,
        trace_slots: dict[str, int] | None = None,
    ) -> None:
        self._capture_model = model
        if identity is not None:
            self._capture_identity = {
                key: field.strip()
                for key, field in zip(
                    ("manufacturer", "model", "serial_number", "firmware_reply"),
                    identity,
                    strict=True,
                )
                if field.strip()
            }
        self._capture_channel = channel
        self._capture_trace_slots = dict(trace_slots) if trace_slots is not None else None
        if mode == "LIN":
            self._capture_sweep_type = "linear"
        elif mode == "LOG":
            self._capture_sweep_type = "log"
        self._capture_context = self.context
        self._capture_payload = self._current_payload()
        self._capture_axis_source = self.axis_source
        self._capture_trace_identity_verified = self.trace_identity_verified

    def _current_payload(
        self,
    ) -> tuple[tuple[float, ...], tuple[str, ...], tuple[tuple[complex, ...], ...]]:
        return (
            tuple(self.frequencies),
            tuple(self.param_names),
            tuple(tuple(samples) for samples in self.s_params),
        )

    def _record_fresh_context(self, context: VNAChannelContext) -> None:
        self.context = context
        self._capture_context = context
        axis, names = self._layout()
        self._verified_payload = (
            context,
            axis,
            names,
            tuple(self._samples(row) for row in self.s_params),
        )

    def _layout(self) -> tuple[tuple[float, ...], tuple[str, ...]]:
        axis = tuple(self.frequencies)
        names = tuple(name.strip().upper() for name in self.param_names)
        if not axis or any(not math.isfinite(value) or value < 0 for value in axis):
            raise ValueError("S-parameter data must have a finite, nonnegative frequency axis.")
        if any(right <= left for left, right in zip(axis[:-1], axis[1:], strict=True)):
            raise ValueError("S-parameter frequency axis must be strictly increasing.")
        if (
            not names
            or any(not re.fullmatch(r"S[1-4][1-4]", name) for name in names)
            or len(names) != len(set(names))
            or len(names) != len(self.s_params)
            or any(len(samples) != len(axis) for samples in self.s_params)
        ):
            raise ValueError(
                "S-parameter names and trace dimensions must match the frequency axis."
            )
        return axis, names

    @staticmethod
    def _samples(samples: list[complex]) -> tuple[complex, ...]:
        if any(not math.isfinite(value.real) or not math.isfinite(value.imag) for value in samples):
            raise ValueError("S-parameter traces must contain finite complex samples.")
        return tuple(samples)

    def trace(self, name: str) -> SParameterTrace:
        """Return a trace by S-parameter name, regardless of catalogue order.

        Names are case-insensitive. An absent name raises `KeyError`.
        The legacy `frequencies`, `param_names`, and `s_params` lists are unchanged.
        """
        axis, names = self._layout()
        parameter = name.strip().upper()
        if parameter not in names:
            raise KeyError(f"S-parameter {name!r} is not in this result.")
        return SParameterTrace(
            parameter,
            axis,
            self._samples(self.s_params[names.index(parameter)]),
            self.axis_source,
            self.trace_identity_verified,
            self.fresh,
            next((t for t in self.context.traces if t.parameter == parameter), None)
            if self.context is not None
            else None,
        )

    def with_uncertainty(
        self,
        components: "QuantityArray",
        *,
        frequencies_hz: "ArrayLike",
        trace_order: Sequence[str],
        source: str,
        setup: str,
    ) -> "SParameterData":
        """Return this observed capture with an externally evaluated RI uncertainty budget.

        Use the exact frequency grid and trace order covered by the evidence.
        Components are dimensionless, in frequency-major order, with adjacent
        real/imaginary entries for each trace. The nominal values must match this
        capture exactly. Retain a reference to the actual budget in `source`
        and identify its applicable setup/reference planes in `setup`. Capture
        with `include_context=True`; this does not certify the external budget.
        """
        import numpy as np

        if (
            self._capture_payload is None
            or self._capture_axis_source != "instrument"
            or not self._capture_trace_identity_verified
            or self._capture_context is None
        ):
            raise ValueError(
                "VNA uncertainty needs verified instrument data captured with context."
            )
        if self._current_payload() != self._capture_payload:
            raise ValueError("Cannot attach uncertainty to a modified VNA payload.")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("VNA uncertainty needs the source of the evaluated budget.")
        if not isinstance(setup, str) or not setup.strip():
            raise ValueError(
                "VNA uncertainty needs the applicable calibration and setup reference."
            )

        axis, names = self._layout()
        grid = np.asarray(frequencies_hz)
        if grid.dtype.kind not in "iuf" or not np.array_equal(grid, np.asarray(axis)):
            raise ValueError("VNA uncertainty frequency grid must match the observed axis exactly.")
        if tuple(trace_order) != names:
            raise ValueError("VNA uncertainty trace order must match the captured traces exactly.")
        samples = np.asarray(tuple(self._samples(row) for row in self.s_params))
        paired = np.stack((samples.real, samples.imag), axis=-1).transpose(1, 0, 2)
        payload = snapshot_components(components, paired.ravel())

        result = copy(self)
        result.frequencies = list(self.frequencies)
        result.param_names = list(self.param_names)
        result.s_params = [list(trace) for trace in self.s_params]
        result._uncertainty_payload = payload
        result._uncertainty_evidence = (source.strip(), setup.strip())
        return result

    @property
    def uncertainty(self) -> "QuantityArray | None":
        """Return the native correlated RI budget, or `None` when not evaluated."""
        if self._uncertainty_payload is None:
            return None
        if self._current_payload() != self._capture_payload:
            raise ValueError("Cannot use uncertainty on a modified VNA payload.")

        from ..uncertainty import QuantityArray

        return QuantityArray.from_dict(json.loads(self._uncertainty_payload))

    def to_measurement_result(self) -> "MeasurementResult":
        """Keep S-parameters as signed Float64 pairs on their original frequency axis.

        Use this result directly in a session or database. Conversion does not
        query the instrument, interpolate the axis, or invent uncertainty.
        """
        import polars as pl

        from ..experiments.results import MeasurementResult
        from ..experiments.results import NativeMeasurementResult

        axis, names = self._layout()
        if any(isinstance(frequency, bool) for frequency in axis):
            raise ValueError("A VNA frequency cannot be a Boolean.")
        samples = tuple(self._samples(row) for row in self.s_params)
        captured = self._capture_payload is not None
        if captured and self._current_payload() != self._capture_payload:
            raise ValueError("Cannot store a modified VNA payload as a native capture.")

        columns = {"frequency_hz": pl.Series("frequency_hz", axis, dtype=pl.Float64)}
        for name, values in zip(names, samples, strict=True):
            for component, values_part in (
                ("real", [value.real for value in values]),
                ("imag", [value.imag for value in values]),
            ):
                label = f"{name}_{component}"
                columns[label] = pl.Series(label, values_part, dtype=pl.Float64)

        context = self._capture_context
        context_data = None
        if context is not None:
            context_data = asdict(context)
            context_data["port_reference_ohms"] = list(context.port_reference_ohms)
            context_data["traces"] = [
                {**asdict(trace), "correction_ports": list(trace.correction_ports)}
                for trace in context.traces
            ]
        identity = self._capture_identity
        result_type = NativeMeasurementResult if self._uncertainty_payload else MeasurementResult
        result = result_type(
            values=pl.DataFrame(columns),
            instrument=self._capture_model or "unspecified",
            units="1",
            measurement_type="s_parameters",
            timestamp=self._result_received_at,
            envelope={
                "timestamp_kind": "host_receipt" if captured else "host_construction",
                "uncertainty_status": "not_evaluated",
                "vna": {
                    "schema_version": 1,
                    "capture_origin": "driver" if captured else "caller",
                    "axis_source": self._capture_axis_source if captured else "caller_supplied",
                    "frequency_unit": "Hz",
                    "trace_identity_verified": captured and self._capture_trace_identity_verified,
                    "fresh": captured and self._fresh_sweep_type is not None and self.fresh,
                    "sweep_type": self._fresh_sweep_type or self._capture_sweep_type,
                    "trace_order": list(names),
                    "trace_slots": (
                        dict(self._capture_trace_slots)
                        if self._capture_trace_slots is not None
                        else None
                    ),
                    "channel": self._capture_channel,
                    "identity": dict(identity) if identity is not None else None,
                    "context": context_data,
                },
            },
        )

        if self._uncertainty_payload is not None and self._uncertainty_evidence is not None:
            source, setup = self._uncertainty_evidence
            result.envelope["uncertainty_status"] = "externally_evaluated"
            result.envelope["uncertainty"] = {
                "kind": "quantity_array",
                "payload": json.loads(self._uncertainty_payload),
            }
            result.envelope["vna"]["uncertainty_evidence"] = {
                "source": source,
                "setup": setup,
                "component_order": "frequency_major_trace_ri",
            }
        return result

    def to_touchstone(self, path: str | PathLike[str], *, overwrite: bool = False) -> None:
        """Write Touchstone 1.0 RI for an unchanged characterized fresh two-port sweep.

        Uses the measured system reference impedance without renormalizing.
        It does not certify calibration.
        """
        axis, names = self._layout()
        traces = tuple(self._samples(row) for row in self.s_params)
        context = self.context
        if (
            not self.fresh
            or self.axis_source != "instrument"
            or not self.trace_identity_verified
            or context is None
            or context.evidence != "fresh_sweep"
            or self._verified_payload != (context, axis, names, traces)
        ):
            raise ValueError("Touchstone requires an unchanged characterized fresh sweep.")
        order = ("S11", "S21", "S12", "S22")
        if set(names) != set(order):
            raise ValueError("A two-port Touchstone file requires S11, S21, S12, and S22.")
        if context.port_extension_enabled:
            raise ValueError("Touchstone export requires port extension off during acquisition.")
        refs = context.port_reference_ohms
        if len(refs) != 2 or refs[0] != refs[1] or not 0.001 <= refs[0] <= 1000:
            raise ValueError("Touchstone 1.0 requires a shared real reference impedance.")
        destination = Path(path)
        if destination.suffix.lower() != ".s2p":
            raise ValueError("Use an .s2p extension for a two-port Touchstone file.")
        ordered = [traces[names.index(name)] for name in order]
        with destination.open("w" if overwrite else "x", encoding="ascii", newline="\n") as out:
            out.write("! Fresh PyTestLab VNA sweep; calibration validity not certified.\n")
            out.write("! Frequency, S11, S21, S12, S22 (real, imaginary).\n")
            out.write(f"# Hz S RI R {refs[0]:.17g}\n")
            for frequency, *samples in zip(axis, *ordered, strict=True):
                fields = [f"{frequency:.17g}"]
                for sample in samples:
                    fields.extend((f"{sample.real:.17g}", f"{sample.imag:.17g}"))
                out.write(" ".join(fields) + "\n")

    def to_csv(self, path: str | PathLike[str], *, overwrite: bool = False) -> None:
        """Write complex data by frequency with axis and acquisition provenance.

        Each trace contributes real and imaginary columns in result order.
        By default an existing file is not replaced. CSV does not encode a
        reference impedance, calibration validity, or Touchstone port order.
        """
        axis, names = self._layout()
        traces = [self._samples(samples) for samples in self.s_params]
        provenance = (
            self.axis_source,
            str(self.trace_identity_verified).lower(),
            str(self.fresh).lower(),
        )
        with Path(path).open("w" if overwrite else "x", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            headers = ["frequency_hz", "axis_source", "trace_identity_verified", "fresh"]
            for name in names:
                headers.extend((f"{name}_real", f"{name}_imag"))
            writer.writerow(headers)
            for frequency, *samples in zip(axis, *traces, strict=True):
                row = [frequency, *provenance]
                for sample in samples:
                    row.extend((sample.real, sample.imag))
                writer.writerow(row)


class VectorNetworkAnalyser(Instrument[VNAConfig]):
    model_config = {"arbitrary_types_allowed": True}
    _fresh_session_quarantined = False

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "sparameter_sweep_setup",
            capability="supports_sweep_setup",
            public_method="configure_s_parameter_sweep",
            group="sweep",
            scope="model",
        ),
        OperationDescriptor(
            "sparameter_sweep_acquire",
            public_method="acquire_s_parameter_sweep",
            required=False,
            group="sweep",
            scope="model",
            direct_python_only=True,
        ),
        OperationDescriptor(
            "sparameter_data",
            public_method="get_s_parameter_data",
            safety_class="read",
            group="trace",
            scope="family",
        ),
        OperationDescriptor(
            "sparameter_channel_context",
            public_method="get_s_parameter_channel_context",
            safety_class="read",
            required=False,
            group="context",
            scope="family",
        ),
        OperationDescriptor(
            "sparameter_frequency_marker",
            public_method="get_s_parameter_frequency_marker",
            safety_class="read",
            required=False,
            group="markers",
            scope="family",
        ),
        OperationDescriptor(
            "vna_inventory",
            public_method="get_vna_inventory",
            safety_class="read",
            required=False,
            group="context",
            scope="family",
        ),
        OperationDescriptor(
            "sparameter_segment_table",
            public_method="get_s_parameter_segment_table",
            safety_class="read",
            required=False,
            group="sweep",
            scope="family",
        ),
        OperationDescriptor(
            "sparameter_sweep_settings",
            public_method="get_s_parameter_sweep_settings",
            safety_class="read",
            required=False,
            group="sweep",
            scope="model",
        ),
    )

    def _require_fresh_session(self) -> None:
        if self._fresh_session_quarantined:
            raise InstrumentCommunicationError(self.config.model, message=_RECOVER)

    def _ensure_backend_connected(self) -> None:
        # An ambiguous reply can poison every later operation on this stream.
        self._require_fresh_session()
        super()._ensure_backend_connected()

    def acquire_s_parameter_sweep(
        self,
        *,
        timeout_ms: int = 15_000,
        include_context: bool = False,
    ) -> SParameterData:
        """Acquire one verified E5071C sweep without switching RF on.

        Verify that the bench is safe before calling this method. It checks live
        analyzer state and native limits, not RF power at the DUT or bench wiring.
        Result `fresh` is true only
        after synchronization and complete held-data verification. When including
        context, reference impedance and correction are checked across acquisition.
        """
        plan = self._context_plan(include_context)
        return acquire(self, timeout_ms=timeout_ms, context_plan=plan)

    def configure_s_parameter_sweep(
        self,
        s_params: list[str] | str | None = None,  # e.g. ["S11", "S21"] or "s11"
        start_freq: float | None = None,
        stop_freq: float | None = None,
        num_points: int | None = None,
        if_bandwidth: float | None = None,
        power_level: float | None = None,
        *,
        sweep_type: Literal["linear", "log"] | None = None,
    ) -> VNASweepSettings | None:
        """Configure an existing LIN/LOG sweep without starting it.

        The E5071C verifies settings and returns the observed state. It requires
        Hold and RF output already off. Supplying `s_params` replaces the
        channel's configured trace list. Optionally select linear or log;
        omitting `sweep_type` preserves the current type. Legacy custom profiles keep their
        original write-only behavior and return None.
        """
        if not self.config.supports_sweep_setup:
            raise self._configuration_error("This profile supports held trace readback only.")
        verified = self.config.operation_options.operation("sparameter_sweep_settings") is not None
        # Resolve every requested setting before sending anything.  A bad
        # later argument must not leave a partially configured sweep.
        resolved_settings: dict[str, Any] = {}
        alias_by_key = {
            "start_freq": ("set_start_frequency", "frequency"),
            "stop_freq": ("set_stop_frequency", "frequency"),
            "num_points": ("set_points", "points"),
            "if_bandwidth": ("set_if_bandwidth", "bandwidth"),
            "power_level": ("set_power_level", "power"),
        }
        if sweep_type is not None:
            if not verified:
                raise self._configuration_error(
                    "This profile does not support sweep type selection."
                )
            if sweep_type not in ("linear", "log"):
                raise self._configuration_error("Select sweep_type='linear' or 'log'.")
            resolved = self._resolve_operation_parameter(
                "sparameter_sweep_setup", "sweep_type", sweep_type
            )
            if (resolved.value, resolved.transport_value) != (
                sweep_type,
                {"linear": "LIN", "log": "LOG"}[sweep_type],
            ):
                raise self._configuration_error("Unverified VNA sweep type selection.")
            resolved_settings["sweep_type"] = resolved
            alias_by_key["sweep_type"] = ("set_sweep_type", "mode")
        resolved_s_params: list[str] = []
        if s_params is not None:
            # A discovered scalar option is accepted directly; callers may
            # still provide the historical list form for multi-trace sweeps.
            selected_s_params = [s_params] if isinstance(s_params, str) else s_params
            # Resolve each semantic selection before any command is sent.
            if verified and (
                not selected_s_params
                or any(not isinstance(name, str) for name in selected_s_params)
            ):
                raise self._configuration_error("Supply a nonempty list of S-parameters.")
            for index, s_parameter in enumerate(selected_s_params, start=1):
                resolved = self._resolve_operation_parameter(
                    "sparameter_sweep_setup", "s_params", s_parameter
                )
                resolved_settings[f"s_parameter_{index}"] = resolved
                resolved_s_params.append(str(resolved.value))
        for parameter, value in (
            (start_freq, "start_freq"),
            (stop_freq, "stop_freq"),
            (num_points, "num_points"),
            (if_bandwidth, "if_bandwidth"),
            (power_level, "power_level"),
        ):
            if parameter is not None:
                if verified and (
                    isinstance(parameter, bool)
                    or not isinstance(parameter, int if value == "num_points" else (int, float))
                    or not math.isfinite(parameter)
                ):
                    raise self._configuration_error(f"Invalid {value}: {parameter!r}.")
                resolved_settings[value] = self._resolve_operation_parameter(
                    "sparameter_sweep_setup", value, parameter
                )

        if verified:
            if len({name.upper() for name in resolved_s_params}) != len(resolved_s_params):
                raise self._configuration_error("Supply distinct S-parameters.")
            return self._configure_verified_sweep(
                resolved_settings,
                alias_by_key,
                tuple(name.upper() for name in resolved_s_params) if s_params is not None else None,
            )

        for key, resolved in resolved_settings.items():
            if key.startswith("s_parameter_"):
                index = int(key.rsplit("_", 1)[1])
                self._send_profile_alias(
                    "define_sparameter", index=index, s_parameter=resolved.transport_value
                )
            else:
                alias, placeholder = alias_by_key[key]
                self._send_profile_alias(alias, **{placeholder: resolved.transport_value})

        if s_params is not None:
            self.config.s_parameters = resolved_s_params
        if start_freq is not None:
            self.config.start_frequency = resolved_settings["start_freq"].value
        if stop_freq is not None:
            self.config.stop_frequency = resolved_settings["stop_freq"].value
        if num_points is not None:
            self.config.num_points = resolved_settings["num_points"].value
        if if_bandwidth is not None:
            self.config.if_bandwidth = resolved_settings["if_bandwidth"].value
        if power_level is not None:
            self.config.power_level = resolved_settings["power_level"].value
        self._logger.info("VNA measurement configured.")
        return None

    def _indexed_settings_profile(self) -> VNAReadbackConfig:
        spec = self.config.readback
        if (
            not isinstance(spec, VNAReadbackConfig)
            or self.config.model.casefold() != "e5071c"
            or self.config.operation_options.operation("sparameter_sweep_settings") is None
        ):
            raise self._configuration_error("Profile does not implement verified VNA settings.")
        return spec

    def _settings_commands(self, spec: VNAReadbackConfig) -> dict[tuple[str, int | None], str]:
        groups = {
            "sparameter_data": {
                "identify": "*IDN?",
                "status_byte": "*STB?",
                "condition": ":STAT:OPER:COND?",
                "continuous": ":INIT{channel}:CONT?",
                "sweep_type": ":SENS{channel}:SWE:TYPE?",
                "frequency_offset": ":SENS{channel}:OFFS:STAT?",
                "fixture_simulator": ":CALC{channel}:FSIM:STAT?",
                "points": ":SENS{channel}:SWE:POIN?",
                "trace_count": ":CALC{channel}:PAR:COUN?",
                "trace_identity": ":CALC{channel}:PAR{trace}:DEF?",
            },
            "sparameter_sweep_settings": {
                "start_freq": ":SENS{channel}:FREQ:STAR?",
                "stop_freq": ":SENS{channel}:FREQ:STOP?",
                "if_bandwidth": ":SENS{channel}:BWID?",
                "power_coupled": ":SOUR{channel}:POW:PORT:COUP?",
                "power_level": ":SOUR{channel}:POW?",
                "rf_output": ":OUTP?",
                "correction": ":SENS{channel}:CORR:STAT?",
            },
        }
        commands = {}
        queries = (self.config.scpi.queries or {}) if self.config.scpi else {}
        for operation_id, names in groups.items():
            operation = self.config.operation_options.operation(operation_id)
            for name, template in names.items():
                alias = operation.transport.get(name) if operation else None
                if alias is None or alias not in queries:
                    raise self._configuration_error(f"Missing VNA settings query {name!r}.")
                traces = range(1, spec.max_traces + 1) if name == "trace_identity" else (None,)
                for trace in traces:
                    built = self._build_profile_alias(alias, channel=spec.channel, trace=trace)
                    if built != [template.format(channel=spec.channel, trace=trace)]:
                        raise self._configuration_error(f"Invalid VNA settings query {name!r}.")
                    commands[name, trace] = built[0]
        if len(set(commands.values())) != len(commands):
            raise self._configuration_error("VNA settings queries must address distinct fields.")
        return commands

    def _observe_sweep(
        self,
        spec: VNAReadbackConfig,
        commands: dict[tuple[str, int | None], str],
        *,
        for_write: bool = False,
    ) -> VNASweepSettings:
        def query(name: str, trace: int | None = None) -> str:
            return self._query(commands[name, trace], skip_check=True)

        def boolean(name: str) -> bool:
            raw = query(name)
            if raw not in {"0", "1"}:
                raise self._data_error(f"Invalid {name} response: {raw!r}.")
            return raw == "1"

        def numeric(name: str) -> float:
            return self._csv_values(query(name), 1, name)[0]

        def check_status() -> None:
            status = self._readback_count(query("status_byte"), "status byte", 0, 255)
            if status & 16:
                raise self._configuration_error("The VNA reported an unexpected pending reply.")
            if status & 4:
                raise self._configuration_error(
                    "The VNA error queue is not empty; inspect it locally."
                )

        identity = [part.strip() for part in query("identify").split(",")]
        if len(identity) != 4 or identity[1].casefold() != self.config.model.casefold():
            raise self._configuration_error(f"VNA did not identify as {self.config.model}.")
        firmware = self._firmware_tuple(identity[3].upper())
        minimum = self._firmware_tuple(spec.minimum_firmware)
        if firmware is None or minimum is None or firmware[0] != minimum[0] or firmware < minimum:
            raise self._configuration_error(
                f"Verified VNA settings require firmware {spec.minimum_firmware} or later "
                "in the same revision series."
            )
        check_status()
        rf_output = boolean("rf_output")
        continuous = boolean("continuous")
        if for_write and (
            rf_output
            or continuous
            or self._readback_count(query("condition"), "operation condition", 0, 65535) != 0
        ):
            raise self._configuration_error(
                "Sweep configuration requires RF output OFF and idle Hold."
            )

        raw_mode = query("sweep_type").upper()
        if raw_mode not in {"LIN", "LOG"}:
            raise self._configuration_error(
                "VNA settings support LIN and LOG frequency sweeps only."
            )
        frequency_offset = boolean("frequency_offset")
        fixture_simulator = boolean("fixture_simulator")
        if for_write and (frequency_offset or fixture_simulator):
            raise self._configuration_error(
                "Configure with frequency offset and fixture simulation off."
            )
        start = numeric("start_freq")
        stop = numeric("stop_freq")
        bandwidth = numeric("if_bandwidth")
        if not (0 < start < stop and bandwidth > 0):
            raise self._data_error("VNA returned an invalid frequency range or IF bandwidth.")
        points = self._readback_count(query("points"), "sweep points", 2, spec.max_points)
        count = self._readback_count(query("trace_count"), "trace count", 1, spec.max_traces)
        catalogue = tuple(query("trace_identity", trace).upper() for trace in range(1, count + 1))
        if any(not name for name in catalogue):
            raise self._data_error("VNA returned an empty trace identity.")
        observed = VNASweepSettings(
            spec.channel,
            "linear" if raw_mode == "LIN" else "log",
            start,
            stop,
            points,
            bandwidth,
            numeric("power_level") if boolean("power_coupled") else None,
            catalogue,
            rf_output,
            continuous,
            boolean("correction"),
            frequency_offset,
            fixture_simulator,
        )
        check_status()
        return observed

    def get_s_parameter_sweep_settings(self) -> VNASweepSettings:
        """Read the E5071C's current LIN/LOG configuration; never start a sweep."""
        spec = self._indexed_settings_profile()
        commands = self._settings_commands(spec)
        with self._operation_lock:
            self._ensure_backend_connected()
            with self._profile_transaction():
                before = self._observe_sweep(spec, commands)
                if self._observe_sweep(spec, commands) != before:
                    raise self._data_error("VNA settings changed during readback.")
                return before

    def _configure_verified_sweep(
        self,
        requested: dict[str, Any],
        alias_by_key: dict[str, tuple[str, str]],
        s_params: tuple[str, ...] | None,
    ) -> VNASweepSettings:
        spec = self._indexed_settings_profile()
        queries = self._settings_commands(spec)
        operation = self.config.operation_options.operation("sparameter_sweep_setup")

        native = {
            "set_sweep_type": ":SENS{channel}:SWE:TYPE {mode}",
            "set_start_frequency": ":SENS{channel}:FREQ:STAR {frequency}",
            "set_stop_frequency": ":SENS{channel}:FREQ:STOP {frequency}",
            "set_points": ":SENS{channel}:SWE:POIN {points}",
            "set_if_bandwidth": ":SENS{channel}:BWID {bandwidth}",
            "set_power_level": ":SOUR{channel}:POW {power}",
            "trace_count": ":CALC{channel}:PAR:COUN {count}",
            "define_sparameter": ":CALC{channel}:PAR{index}:DEF {s_parameter}",
        }

        def command(name: str, **values: Any) -> str:
            alias = operation.transport.get(name) if operation else None
            if (
                alias is None
                or not self.config.scpi
                or alias not in (self.config.scpi.commands or {})
            ):
                raise self._configuration_error(f"Missing VNA setup command {name!r}.")
            built = self._build_profile_alias(alias, channel=spec.channel, **values)
            if (
                built != [native[name].format(channel=spec.channel, **values)]
                or re.fullmatch(r"[^?;\r\n]+", built[0]) is None
            ):
                raise self._configuration_error(f"Invalid VNA setup command {name!r}.")
            return built[0]

        # Compile every user-supplied setting before any I/O, even if unchanged.
        setup = {
            key: command(alias, **{parameter: requested[key].transport_value})
            for key, (alias, parameter) in alias_by_key.items()
            if key in requested
        }
        trace_commands: list[str] = []
        if s_params is not None:
            if len(s_params) > spec.max_traces:
                raise self._configuration_error(f"At most {spec.max_traces} traces are supported.")
            trace_commands = [command("trace_count", count=len(s_params))] + [
                command(
                    "define_sparameter",
                    index=index,
                    s_parameter=requested[f"s_parameter_{index}"].transport_value,
                )
                for index in range(1, len(s_params) + 1)
            ]

        with self._operation_lock:
            self._ensure_backend_connected()
            with self._profile_transaction():
                before = self._observe_sweep(spec, queries, for_write=True)
                values = {key: requested[key].value for key in setup}
                if s_params is not None:
                    values["s_params"] = s_params
                expected = replace(before, **values)
                if not expected.start_freq < expected.stop_freq:
                    raise self._configuration_error("Start frequency must be below stop frequency.")
                if expected.num_points > spec.max_points:
                    raise self._configuration_error(
                        "Point count exceeds the profile-supported maximum."
                    )
                if "power_level" in setup and before.power_level is None:
                    raise self._configuration_error("Power setup requires coupled port powers.")

                def checked_write(write: str) -> None:
                    self._send_command(write, skip_check=True)
                    status = self._query(queries["status_byte", None], skip_check=True)
                    if self._readback_count(status, "status byte", 0, 255) & 20:
                        raise self._configuration_error(
                            "VNA rejected a setup command or reported a pending reply; "
                            "settings may be partially applied. Inspect the instrument."
                        )

                current = before
                if "sweep_type" in setup and expected.sweep_type != before.sweep_type:
                    checked_write(setup["sweep_type"])
                    current = self._observe_sweep(spec, queries, for_write=True)
                    if current.sweep_type != expected.sweep_type:
                        raise self._data_error(
                            "VNA setup readback mismatch: sweep type was not applied."
                        )
                    if (
                        current.power_level != before.power_level
                        or current.start_freq != before.start_freq
                        or current.stop_freq != before.stop_freq
                    ):
                        raise self._data_error(
                            "VNA range or power state changed while switching sweep type; "
                            "inspect the instrument before applying further settings."
                        )

                order = ["start_freq", "stop_freq", "num_points", "if_bandwidth", "power_level"]
                # Moving the whole band above the old one requires extending its high
                # end first. Otherwise use start first to avoid crossing the old start.
                if expected.start_freq >= current.stop_freq:
                    order[0], order[1] = order[1], order[0]
                writes = [setup[key] for key in order if key in setup]
                if s_params is not None and s_params != current.s_params:
                    writes.extend(
                        trace_commands[1:]
                        if len(s_params) == len(current.s_params)
                        else trace_commands
                    )
                for write in writes:
                    checked_write(write)

                after = self._observe_sweep(spec, queries, for_write=True)
                # Setpoint comparisons allow only ASCII representation noise, not
                # rounding to another IF bandwidth or frequency/point limit.
                tolerances = {
                    "start_freq": 1e-6,
                    "stop_freq": 1e-6,
                    "if_bandwidth": 1e-9,
                    "power_level": 1e-9,
                }
                mismatches = []
                for key in (
                    "start_freq",
                    "stop_freq",
                    "num_points",
                    "if_bandwidth",
                    "power_level",
                    "s_params",
                    "sweep_type",
                ):
                    actual, target = getattr(after, key), getattr(expected, key)
                    equal = actual == target
                    if (
                        not equal
                        and key in tolerances
                        and actual is not None
                        and target is not None
                    ):
                        equal = math.isclose(actual, target, rel_tol=0, abs_tol=tolerances[key])
                    if not equal:
                        mismatches.append(f"{key}: expected {target!r}, observed {actual!r}")
                if mismatches:
                    raise self._data_error("VNA setup readback mismatch: " + "; ".join(mismatches))
                if s_params is not None:
                    self.config.s_parameters = list(after.s_params)
                if "start_freq" in setup:
                    self.config.start_frequency = after.start_freq
                if "stop_freq" in setup:
                    self.config.stop_frequency = after.stop_freq
                if "num_points" in setup:
                    self.config.num_points = after.num_points
                if "if_bandwidth" in setup:
                    self.config.if_bandwidth = after.if_bandwidth
                if "power_level" in setup:
                    self.config.power_level = after.power_level
                return after

    def get_s_parameter_data(self, *, include_context: bool = False) -> SParameterData:
        """Read the S-parameters requested by the profile.

        Indexed readback reads held data without triggering a sweep and
        reports instrument-read axes and trace identities. The legacy path
        follows the custom profile's query and reports a profile-nominal axis
        and unverified trace identities. Optional context describes settings
        observed around the read, not how or when the buffer was acquired.
        """
        plan = self._context_plan(include_context)
        readback = self.config.readback
        if isinstance(readback, CMTHeldReadbackConfig):
            return self._read_cmt_held_s_parameters(readback, context_plan=plan)
        if readback is not None:
            return self._read_indexed_s_parameters(readback, context_plan=plan)
        return self._read_legacy_s_parameters()

    def _context_plan(self, enabled: bool) -> ContextPlan | None:
        if type(enabled) is not bool:
            raise ValueError("include_context must be a boolean.")
        return build_context_plan(self) if enabled else None

    def _query_ena_context(self, command: str) -> str:
        try:
            return self._query(command, skip_check=True)
        except (InstrumentCommunicationError, KeyboardInterrupt) as error:
            self._fresh_session_quarantined = True
            error.add_note(_RECOVER)
            raise

    def _cmt_query_backend(self) -> Callable[..., str]:
        exchange = getattr(self._backend, "query_ascii_socket_line", None)
        if not callable(exchange):
            raise self._configuration_error(
                "CMT held readback requires the bounded VISA TCPIP SOCKET transport."
            )
        return exchange

    def _make_cmt_exchange(self, exchange: Callable[..., str]) -> Callable[[str, int], str]:
        deadline = time.monotonic() + self.get_communication_timeout() / 1000

        def bounded(command: str, limit: int) -> str:
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                raise self._data_error("CMT held readback exceeded its communication timeout.")
            return exchange(command, limit=limit, timeout_ms=remaining)

        return bounded

    @contextmanager
    def _context_query_transaction(
        self, *, response_limits: dict[str, int] | None = None
    ) -> Iterator[Callable[[str], str]]:
        limits = response_limits or {}
        cmt = isinstance(self.config.readback, CMTHeldReadbackConfig)
        with self._operation_lock:
            exchange = self._cmt_query_backend() if cmt else None
            self._ensure_backend_connected()
            with self._profile_transaction():
                bounded = None if exchange is None else self._make_cmt_exchange(exchange)

                def query(command: str) -> str:
                    if bounded is None:
                        return self._query_ena_context(command)
                    return bounded(command, limits.get(command, 256))

                try:
                    yield query
                except BaseException:
                    if cmt:
                        with suppress(Exception):
                            self.close()
                    raise

    def get_vna_inventory(self) -> VNAInstrumentInventory:
        """Read analyzer capacity in Hold without changing the setup.

        The active display channel is distinct from the profile channel.
        Service limits and nominal option ranges do not enable more driver
        workflows or establish a safe RF envelope.
        """
        plan = build_inventory_plan(self)
        with self._context_query_transaction() as query:
            before = observe_inventory(self, plan, query)
            if observe_inventory(self, plan, query) != before:
                raise self._data_error("VNA inventory changed during inspection.")
            return before

    def get_s_parameter_segment_table(self) -> VNASegmentTable:
        """Inspect both profiles' stored segment settings without changing the sweep.

        Reads the profile channel in idle Hold, even when Segment is not the
        selected sweep type. Reports configured rows, not an acquisition
        axis, effective RF power, or a trace buffer.
        """
        plan = build_segment_plan(self)
        spec = self.config.readback
        assert isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
        with self._context_query_transaction(
            response_limits={plan["table"]: segment_table_line_limit(spec)}
        ) as query:
            before = observe_segment_table(self, plan, query)
            if observe_segment_table(self, plan, query) != before:
                raise self._data_error("VNA segment table changed during inspection.")
            return before

    def get_s_parameter_channel_context(self) -> VNAChannelContext:
        """Read the selected held channel's settings and indexed trace correction.

        Never selects a trace, consumes the error queue, or reads the trace buffer.
        """
        plan = build_context_plan(self)
        with self._context_query_transaction() as query:
            before = observe_context(self, plan, query, "live_configuration")
            if observe_context(self, plan, query, "live_configuration") != before:
                raise self._data_error("VNA channel context changed during inspection.")
        return before

    def get_s_parameter_frequency_marker(self, trace: int, marker: int = 1) -> VNAFrequencyMarker:
        """Read one already enabled log-magnitude display marker on a held trace.

        Returns the instrument's displayed marker in hertz and dB. It can
        be interpolated by the instrument; use trace().at_frequency() for
        a verified measured bin. The driver does not move or enable markers.
        """
        context_plan = build_context_plan(self)
        marker_plan = build_marker_plan(self, trace, marker)
        with self._context_query_transaction() as query:
            before = observe_context(self, context_plan, query, "live_configuration")
            observed = observe_marker(self, before, marker_plan, query, trace, marker)
            if (
                observe_marker(self, before, marker_plan, query, trace, marker) != observed
                or observe_context(self, context_plan, query, "live_configuration") != before
            ):
                raise self._data_error("VNA marker or channel context changed during readback.")
        return observed

    def _verify_context_traces(self, context: VNAChannelContext, selected: dict[str, int]) -> None:
        for name, slot in selected.items():
            if (
                slot > len(context.traces)
                or context.trace(slot).parameter != name
                or sum(trace.parameter == name for trace in context.traces) != 1
            ):
                raise self._data_error("Selected traces disagree with the VNA channel context.")

    def _verify_context_axis(self, context: VNAChannelContext, axis: list[float] | None) -> None:
        if (
            axis is None
            or len(axis) != context.point_count
            or not math.isclose(axis[0], context.start_hz, rel_tol=1e-6, abs_tol=1e-6)
            or not math.isclose(axis[-1], context.stop_hz, rel_tol=1e-6, abs_tol=1e-6)
        ):
            raise self._data_error("The measured axis disagrees with the observed VNA context.")

    def _data_error(self, message: str) -> InstrumentDataError:
        return InstrumentDataError(self.config.model, message)

    def _configuration_error(self, message: str) -> InstrumentConfigurationError:
        return InstrumentConfigurationError(self.config.model, message)

    def _csv_values(self, raw: str, expected: int, description: str) -> list[float]:
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != expected:
            raise self._data_error(f"Expected {expected} {description} values, got {len(parts)}.")
        try:
            if any(not part for part in parts):
                raise ValueError("empty field")
            if any(_SCPI_FLOAT.fullmatch(part) is None for part in parts):
                raise ValueError("field is not a finite ASCII number")
            values = [float(part) for part in parts]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("non-finite value")
        except ValueError as exc:
            raise self._data_error(f"Invalid {description} response: {exc}.") from exc
        return values

    def _readback_count(self, raw: str, label: str, low: int, high: int) -> int:
        if re.fullmatch(r"[+]?[0-9]{1,8}", raw) is None:
            raise self._data_error(f"Invalid {label} response: {raw!r}.")
        count = int(raw)
        if not low <= count <= high:
            raise self._configuration_error(f"{label} {count} outside supported {low}–{high}.")
        return count

    @staticmethod
    def _firmware_tuple(value: str) -> tuple[str, int, int] | None:
        match = re.fullmatch(r"([A-Z])\.([0-9]+)\.([0-9]+)", value)
        if match is None:
            return None
        return match[1], int(match[2]), int(match[3])

    def _read_indexed_s_parameters(
        self,
        spec: VNAReadbackConfig,
        *,
        synchronized_query: Callable[[str], str] | None = None,
        context_plan: ContextPlan | None = None,
    ) -> SParameterData:
        requested = [name.strip().upper() for name in self.config.s_parameters]
        if (
            not requested
            or len(requested) != len(set(requested))
            or any(re.fullmatch(r"S[1-4][1-4]", name) is None for name in requested)
        ):
            raise self._configuration_error("Request distinct S-parameters such as S11 and S21.")

        operation = self.config.operation_options.operation("sparameter_data")
        if operation is None:
            raise self._configuration_error("Profile does not implement indexed S-parameter data.")

        def build(name: str, trace: int | None = None) -> str:
            alias = operation.transport.get(name)
            if (
                alias is None
                or self.config.scpi is None
                or alias not in (self.config.scpi.queries or {})
            ):
                raise self._configuration_error(
                    f"Profile does not declare readback query {name!r}."
                )
            commands = self._build_profile_alias(alias, channel=spec.channel, trace=trace)
            if len(commands) != 1 or re.fullmatch(r"[^?;\r\n]+\?", commands[0]) is None:
                raise self._configuration_error(f"VNA readback {name!r} is not a single query.")
            return commands[0]

        trace_queries = {
            "trace_identity",
            "trace_equation",
            "trace_time_transform",
            "trace_axis",
            "trace_data",
        }
        commands = {
            (name, trace): build(name, trace)
            for name in VNA_READBACK_QUERIES
            for trace in (range(1, spec.max_traces + 1) if name in trace_queries else (None,))
        }
        if len(set(commands.values())) != len(commands):
            raise self._configuration_error(
                "VNA readback queries must address each field distinctly."
            )

        def raw_query(command: str) -> str:
            if synchronized_query is not None:
                return synchronized_query(command)
            if context_plan is not None:
                return self._query_ena_context(command)
            return self._query(command, skip_check=True)

        def query(name: str, trace: int | None = None) -> str:
            return raw_query(commands[name, trace]).strip()

        def check_idle() -> None:
            status = self._readback_count(query("status_byte"), "status byte", 0, 255)
            if status & 4:
                raise self._configuration_error(
                    "The VNA error queue is not empty; inspect it before reading traces."
                )
            condition = self._readback_count(query("condition"), "operation condition", 0, 65535)
            if condition != 0 or query("continuous") != "0":
                raise self._configuration_error(
                    "Readout requires the existing sweep on Hold with no measurement, "
                    "pending trigger, macro, or other active operation."
                )

        def snapshot() -> tuple[str, float, int, int]:
            check_idle()
            if query("data_format").upper() != "ASC":
                raise self._configuration_error("VNA readout requires ASCII transfer format.")
            mode = query("sweep_type").upper()
            if mode not in {"LIN", "LOG"}:
                raise self._configuration_error(
                    "Readout supports only LIN and LOG frequency sweeps."
                )
            span = self._csv_values(query("frequency_span"), 1, "frequency span")[0]
            if span <= 0 or query("frequency_offset") != "0":
                raise self._configuration_error(
                    "VNA readout requires nonzero frequency span and frequency offset off."
                )
            if query("fixture_simulator") != "0":
                raise self._configuration_error("VNA readout requires the fixture simulator off.")
            points = self._readback_count(query("points"), "sweep points", 2, spec.max_points)
            count = self._readback_count(query("trace_count"), "trace count", 1, spec.max_traces)
            return mode, span, points, count

        def check_trace(trace: int, name: str) -> None:
            if query("trace_identity", trace).upper() != name:
                raise self._data_error(f"Trace {trace} no longer identifies as {name}.")
            if query("trace_equation", trace) != "0" or query("trace_time_transform", trace) != "0":
                raise self._configuration_error(
                    f"VNA trace {trace} requires equation and time-domain transforms off."
                )

        with self._operation_lock if synchronized_query is None else nullcontext():
            # Fresh acquisition already holds the resource lock.
            if synchronized_query is None:
                self._ensure_backend_connected()
            with self._profile_transaction() if synchronized_query is None else nullcontext():
                identity = query("identify").split(",")
                if (
                    len(identity) != 4
                    or identity[1].strip().casefold() != self.config.model.casefold()
                ):
                    raise self._configuration_error(f"VNA did not identify as {self.config.model}.")
                firmware = self._firmware_tuple(identity[3].strip().upper())
                minimum = self._firmware_tuple(spec.minimum_firmware)
                if (
                    minimum is None
                    or firmware is None
                    or firmware[0] != minimum[0]
                    or firmware < minimum
                ):
                    raise self._configuration_error(
                        f"Indexed VNA readout requires firmware {spec.minimum_firmware} or later "
                        "in the same revision series."
                    )

                before = snapshot()
                mode, _, points, trace_count = before
                catalogue = {
                    trace: query("trace_identity", trace).upper()
                    for trace in range(1, trace_count + 1)
                }
                selected: dict[str, int] = {}
                for name in requested:
                    candidates = [
                        trace for trace, observed in catalogue.items() if observed == name
                    ]
                    if len(candidates) != 1:
                        raise self._data_error(
                            f"Expected one configured {name} trace, found {len(candidates)} "
                            f"on channel {spec.channel}."
                        )
                    selected[name] = candidates[0]

                context = (
                    observe_context(self, context_plan, raw_query, "held_readback")
                    if context_plan is not None
                    else None
                )
                if context is not None:
                    self._verify_context_traces(context, selected)
                for name, trace in selected.items():
                    check_trace(trace, name)
                check_idle()

                frequencies = None
                s_params: list[list[complex]] = []
                for trace in selected.values():
                    axis = self._csv_values(query("trace_axis", trace), points, "frequency axis")
                    if (
                        axis[0] < 0
                        or (mode == "LOG" and axis[0] == 0)
                        or any(
                            right <= left for left, right in zip(axis[:-1], axis[1:], strict=True)
                        )
                    ):
                        raise self._data_error(
                            "The observed frequency axis is not strictly increasing."
                        )
                    if frequencies is not None and axis != frequencies:
                        raise self._data_error(
                            "Selected traces do not share the same frequency axis."
                        )
                    frequencies = axis
                    values = self._csv_values(query("trace_data", trace), 2 * points, "S-parameter")
                    s_params.append(
                        [complex(i, q) for i, q in zip(values[::2], values[1::2], strict=True)]
                    )

                if snapshot() != before:
                    raise self._data_error("VNA sweep settings changed during readout.")
                for name, trace in selected.items():
                    check_trace(trace, name)
                    if (
                        self._csv_values(query("trace_axis", trace), points, "frequency axis")
                        != frequencies
                    ):
                        raise self._data_error("VNA frequency axis changed during readout.")
                check_idle()
                if context_plan is not None and context is not None:
                    self._verify_context_axis(context, frequencies)
                    if observe_context(self, context_plan, raw_query, "held_readback") != context:
                        raise self._data_error("VNA context changed during held readback.")

        assert frequencies is not None
        result = SParameterData(
            frequencies=frequencies,
            s_params=s_params,
            param_names=requested,
            axis_source="instrument",
            trace_identity_verified=True,
        )
        result.context = context
        result._record_capture(
            self.config.model,
            identity=identity,
            channel=spec.channel,
            mode=mode,
            trace_slots=selected,
        )
        return result

    def _read_cmt_held_s_parameters(
        self, spec: CMTHeldReadbackConfig, *, context_plan: ContextPlan | None = None
    ) -> SParameterData:
        requested = [name.strip().upper() for name in self.config.s_parameters]
        if (
            not requested
            or len(requested) != len(set(requested))
            or any(re.fullmatch(r"S[12][12]", name) is None for name in requested)
        ):
            raise self._configuration_error("Request distinct two-port S-parameters.")

        operation = self.config.operation_options.operation("sparameter_data")
        queries = (self.config.scpi.queries or {}) if self.config.scpi else {}
        if operation is None:
            raise self._configuration_error("Profile does not implement indexed S-parameter data.")

        commands = {}
        for key in CMT_READBACK_QUERIES:
            alias = operation.transport.get(key)
            if alias is None or alias not in queries:
                raise self._configuration_error(f"Missing CMT readback query {key!r}.")
            traces = (
                range(1, spec.max_traces + 1)
                if key.startswith("trace_") and key != "trace_count"
                else (None,)
            )
            for trace in traces:
                rendered = self._build_profile_alias(alias, channel=spec.channel, trace=trace)
                if len(rendered) != 1 or re.fullmatch(r"[A-Za-z0-9:*]+\?", rendered[0]) is None:
                    raise self._configuration_error(f"CMT {key!r} is not a single SCPI query.")
                commands[key, trace] = rendered[0]
        if len(set(commands.values())) != len(commands):
            raise self._configuration_error(
                "CMT readback queries must address distinct fields and traces."
            )

        with self._operation_lock:
            exchange = self._cmt_query_backend()
            self._ensure_backend_connected()
            with self._profile_transaction():
                bounded = self._make_cmt_exchange(exchange)

                def raw_query(command: str) -> str:
                    return bounded(command, 256)

                def query(key: str, trace: int | None = None, limit: int = 256) -> str:
                    return bounded(commands[key, trace], limit)

                def check_idle() -> None:
                    if query("trigger_state") != "HOLD" or query("continuous") != "0":
                        raise self._configuration_error(
                            "CMT readback requires HOLD and continuous initiation off."
                        )

                def snapshot() -> tuple[str, float, int, tuple[str, ...]]:
                    check_idle()
                    mode = query("sweep_type")
                    if mode not in {"LIN", "LOG"}:
                        raise self._configuration_error(
                            "CMT requires a LIN or LOG frequency sweep."
                        )
                    span = self._csv_values(query("frequency_span"), 1, "frequency span")[0]
                    if (
                        span <= 0
                        or query("frequency_offset") != "0"
                        or query("fixture_simulator") != "0"
                    ):
                        raise self._configuration_error(
                            "CMT requires positive span, frequency offset off and fixture simulator off."
                        )
                    points = self._readback_count(
                        query("points"), "sweep points", 2, spec.max_points
                    )
                    count = self._readback_count(
                        query("trace_count"), "trace count", 1, spec.max_traces
                    )
                    catalogue = tuple(
                        query("trace_identity", trace) for trace in range(1, count + 1)
                    )
                    return mode, span, points, catalogue

                def check_trace(trace: int, name: str) -> None:
                    if query("trace_identity", trace) != name:
                        raise self._data_error(f"CMT trace {trace} no longer identifies as {name}.")
                    for field, off in (
                        ("trace_math", "OFF"),
                        ("trace_time_transform", "0"),
                        ("trace_gate", "0"),
                        ("trace_conversion", "0"),
                        ("trace_hold", "OFF"),
                    ):
                        if query(field, trace) != off:
                            raise self._configuration_error(
                                f"CMT trace {trace} requires {field} off."
                            )

                try:
                    fields = [field.strip() for field in query("identify").split(",")]
                    if (
                        len(fields) != 4
                        or fields[:2] != ["CMT", "C1209"]
                        or re.fullmatch(r"[0-9]+", fields[2]) is None
                        or (
                            self.config.serial_number is not None
                            and fields[2] != self.config.serial_number
                        )
                        or re.fullmatch(re.escape(spec.software_version) + r"/[0-9]+", fields[3])
                        is None
                    ):
                        raise self._configuration_error(
                            f"Expected CMT C1209 with exact S2VNA version {spec.software_version} and matching serial (if configured)."
                        )
                    before = snapshot()
                    _, span, points, catalogue = before
                    selected: list[tuple[int, str]] = []
                    for name in requested:
                        if catalogue.count(name) != 1:
                            raise self._data_error(
                                f"Expected one configured {name} trace, found {catalogue.count(name)} on channel {spec.channel}."
                            )
                        selected.append((catalogue.index(name) + 1, name))

                    context = (
                        observe_context(self, context_plan, raw_query, "held_readback")
                        if context_plan is not None
                        else None
                    )
                    if context is not None:
                        self._verify_context_traces(
                            context, {name: trace for trace, name in selected}
                        )
                    frequencies = None
                    s_params: list[list[complex]] = []
                    # 48 bytes per number (including separator) bounds the reply
                    # while leaving ample space for vendor floating-point text.
                    for trace, name in selected:
                        check_trace(trace, name)
                        check_idle()
                        axis = self._csv_values(
                            query("trace_axis", trace, points * 48 + 2), points, "frequency axis"
                        )
                        if axis[0] <= 0 or any(
                            right <= left for left, right in zip(axis[:-1], axis[1:], strict=True)
                        ):
                            raise self._data_error(
                                "CMT requires a positive, strictly increasing frequency axis."
                            )
                        if frequencies is not None and axis != frequencies:
                            raise self._data_error(
                                "Selected CMT traces do not share the same frequency axis."
                            )
                        # The vendor defines SPAN as the LIN/LOG stimulus span in Hz.
                        # Allow at most 1 ppm for independent ASCII rounding, plus
                        # float representation noise at the two subtracted endpoints.
                        axis_span = axis[-1] - axis[0]
                        tolerance = span * 1e-6 + math.ulp(axis[0]) + math.ulp(axis[-1])
                        if abs(axis_span - span) > tolerance:
                            raise self._data_error(
                                "CMT frequency axis span disagrees with the observed sweep span."
                            )
                        frequencies = axis
                        values = self._csv_values(
                            query("trace_data", trace, 2 * points * 48 + 2),
                            2 * points,
                            "S-parameter",
                        )
                        s_params.append(
                            [complex(i, q) for i, q in zip(values[::2], values[1::2], strict=True)]
                        )

                    if snapshot() != before:
                        raise self._data_error(
                            "CMT sweep settings or trace catalog changed during readout."
                        )
                    for trace, name in selected:
                        check_trace(trace, name)
                        if (
                            self._csv_values(
                                query("trace_axis", trace, points * 48 + 2),
                                points,
                                "frequency axis",
                            )
                            != frequencies
                        ):
                            raise self._data_error("CMT frequency axis changed during readout.")
                    check_idle()
                    if context_plan is not None and context is not None:
                        self._verify_context_axis(context, frequencies)
                        if (
                            observe_context(self, context_plan, raw_query, "held_readback")
                            != context
                        ):
                            raise self._data_error("CMT context changed during held readback.")
                except BaseException:
                    # Close only, never clear or retry a potentially desynchronized SOCKET.
                    with suppress(Exception):
                        self.close()
                    raise

        assert frequencies is not None
        result = SParameterData(
            frequencies=frequencies,
            s_params=s_params,
            param_names=requested,
            axis_source="instrument",
            trace_identity_verified=True,
        )
        result.context = context
        result._record_capture(
            self.config.model,
            identity=fields,
            channel=spec.channel,
            mode=before[0],
            trace_slots={name: trace for trace, name in selected},
        )
        return result

    def _read_legacy_s_parameters(self) -> SParameterData:
        num_points = self.config.num_points
        start_f = self.config.start_frequency
        stop_f = self.config.stop_frequency
        param_names = list(self.config.s_parameters)
        if (
            num_points is None
            or num_points <= 0
            or start_f is None
            or stop_f is None
            or not math.isfinite(start_f)
            or not math.isfinite(stop_f)
            or not param_names
        ):
            raise self._configuration_error(
                "The profile must declare s_parameters, start_frequency, stop_frequency, and num_points."
            )
        frequencies = [
            start_f + i * (stop_f - start_f) / (num_points - 1 if num_points > 1 else 1)
            for i in range(num_points)
        ]
        raw = self._query_profile_alias("sparameter_data")
        values = self._csv_values(raw, len(param_names) * num_points * 2, "S-parameter")
        pairs = [complex(i, q) for i, q in zip(values[::2], values[1::2], strict=True)]
        result = SParameterData(
            frequencies=frequencies,
            s_params=[pairs[i : i + num_points] for i in range(0, len(pairs), num_points)],
            param_names=param_names,
        )
        result._record_capture(self.config.model)
        return result
