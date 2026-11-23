"""Bounded ENA single-sweep protocol. Not a hardware RF interlock."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Literal
from typing import TypeVar

from ..config.vna_config import VNAReadbackConfig
from ..errors import InstrumentCommunicationError
from ._vna_context import ContextPlan
from ._vna_context import observe_context

if TYPE_CHECKING:
    from .VectorNetworkAnalyser import SParameterData
    from .VectorNetworkAnalyser import VectorNetworkAnalyser

_T = TypeVar("_T")

_OPERATION = "sparameter_sweep_acquire"
_SUPPORTED_OPTIONS = {"240": 4.5e9, "260": 6.5e9, "280": 8.5e9}
_MIN_FREQUENCY_HZ = 9e3
_TEST_SET_OPTIONS = frozenset(
    {
        "230",
        "235",
        "240",
        "245",
        "260",
        "265",
        "280",
        "285",
        "2D5",
        "2K5",
        "430",
        "435",
        "440",
        "445",
        "460",
        "465",
        "480",
        "485",
        "4D5",
        "4K5",
    }
)

_READ_STATE = {
    "port_count": (":SERV:PORT:COUN?", "2"),
    "channel_limit": (":SERV:CHAN:COUN?", "1"),
    "continuous": (":INIT1:CONT?", "0"),
    "trigger_source": (":TRIG:SOUR?", "BUS"),
    "point_trigger": (":TRIG:POIN?", "0"),
    "trigger_output": (":TRIG:OUTP:STAT?", "0"),
    "averaging_trigger": (":TRIG:AVER?", "0"),
    "averaging": (":SENS1:AVER?", "0"),
    "rf_output": (":OUTP?", "1"),
    "format": (":FORM:DATA?", "ASC"),
    "sweep_generation": (":SENS1:SWE:GEN?", "STEP"),
    "fixture_simulator": (":CALC1:FSIM:STAT?", "0"),
    "shift_lo": (":SENS1:SWE:SLOC:STAT?", "0"),
    "frequency_offset": (":SENS1:OFFS:STAT?", "0"),
    "external_lo": (":SENS1:OFFS:LOC:STAT?", "0"),
    "external_source_control": (":SENS1:OFFS:LOC:CONT?", "0"),
    "external_test_set": (":SYST:TSET?", "OFF"),
    "multiplexer_1": (":SENS:MULT1:STAT?", "0"),
    "multiplexer_2": (":SENS:MULT2:STAT?", "0"),
    "coupled_power": (":SOUR1:POW:PORT:COUP?", "1"),
    "power_slope": (":SOUR1:POW:SLOP:STAT?", "0"),
    **{
        f"port_{port}_{name}": (f":SOUR1:POW:PORT{port}:{suffix}", "0")
        for port in (1, 2)
        for name, suffix in (
            ("source_correction", "CORR?"),
            ("loss_compensation", "CORR:COLL:TABL:LOSS?"),
        )
    },
}
_QUERIES = {
    "identify": "*IDN?",
    "options": "*OPT?",
    "status": "*STB?",
    "condition": ":STAT:OPER:COND?",
    "points": ":SENS1:SWE:POIN?",
    "trace_count": ":CALC1:PAR:COUN?",
    "trace_identity": ":CALC1:PAR{trace}:DEF?",
    "trace_correction": ":SENS1:CORR:TYPE{trace}?",
    "trace_time_transform": ":CALC1:TRAC{trace}:TRAN:TIME:STAT?",
    "trace_equation": ":CALC1:TRAC{trace}:EQU:STAT?",
    "trace_live": ":DISP:WIND1:TRAC{trace}:STAT?",
    "trace_gating": ":CALC1:TRAC{trace}:FILT:GATE:TIME:STAT?",
    "trace_conversion": ":CALC1:TRAC{trace}:CONV:STAT?",
    "trace_hold": ":CALC1:TRAC{trace}:HOLD:TYPE?",
    "trace_math": ":CALC1:TRAC{trace}:MATH:FUNC?",
    "start_frequency": ":SENS1:FREQ:STAR?",
    "stop_frequency": ":SENS1:FREQ:STOP?",
    "source_power": ":SOUR1:POW?",
    "sweep_type": ":SENS1:SWE:TYPE?",
    "completion": "*OPC?",
    **{key: pair[0] for key, pair in _READ_STATE.items()},
}
_LOG_STIMULUS = ":SENS1:FREQ:DATA?"
_WRITES = {"arm": ":INIT1", "trigger": ":TRIG:SING", "abort": ":ABOR"}
_INDEXED_DATA = {
    "identify": _QUERIES["identify"],
    "status_byte": _QUERIES["status"],
    "condition": _QUERIES["condition"],
    "continuous": _QUERIES["continuous"],
    "data_format": _QUERIES["format"],
    "sweep_type": _QUERIES["sweep_type"],
    "frequency_span": ":SENS1:FREQ:SPAN?",
    "frequency_offset": _QUERIES["frequency_offset"],
    "fixture_simulator": _QUERIES["fixture_simulator"],
    "points": _QUERIES["points"],
    "trace_count": _QUERIES["trace_count"],
    "trace_identity": _QUERIES["trace_identity"],
    "trace_equation": _QUERIES["trace_equation"],
    "trace_time_transform": _QUERIES["trace_time_transform"],
    "trace_axis": ":CALC1:TRAC{trace}:DATA:XAX?",
    "trace_data": ":CALC1:TRAC{trace}:DATA:SDAT?",
}
_RECOVER = (
    "VNA session quarantined. Stop the sweep and make the DUT safe at the bench; "
    "clear the instrument interface before opening a new session. Do not retry blindly."
)


class _SweepBudget:
    def __init__(self, model: str, timeout_ms: int) -> None:
        self.model = model
        self.deadline = time.monotonic() + timeout_ms / 1000
        self.uncertain_stream = False

    def remaining_ms(self, command: str | None = None) -> int:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise InstrumentCommunicationError(self.model, command, "VNA sweep deadline expired.")
        return math.ceil(remaining * 1000)

    def exchange(self, command: str, action: Callable[..., _T]) -> _T:
        timeout_ms = self.remaining_ms(command)
        try:
            result = action(command, skip_check=True, timeout_ms=timeout_ms)
        except BaseException:
            self.uncertain_stream = True
            raise
        self.remaining_ms(command)
        return result


@dataclass(frozen=True)
class _Snapshot:
    identity: tuple[str, ...]
    options: str
    max_frequency_hz: float
    sweep_type: Literal["linear", "log"]
    points: int
    start_hz: float
    stop_hz: float
    power_dbm: float
    traces: tuple[tuple[str, str], ...]


def _max_source_setpoint(stop_hz: float) -> float:
    # Keysight 5989-5479EN, Test Port Output. Use the stricter band at
    # boundaries across the whole span. The vendor's range is for port 1
    # and does not establish the actual RF power at either DUT port.
    return next(
        level for lower_hz, level in ((7e9, 7), (6e9, 8), (5e9, 9), (0, 10)) if stop_hz >= lower_hz
    )


def acquire(
    vna: VectorNetworkAnalyser,
    *,
    timeout_ms: int,
    context_plan: ContextPlan | None = None,
) -> SParameterData:
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 120_000:
        raise vna._configuration_error("VNA timeout_ms must be an integer from 1 to 120000.")
    spec = vna.config.readback
    operation = vna.config.operation_options.operation(_OPERATION)
    scpi = vna.config.scpi
    if (
        not isinstance(spec, VNAReadbackConfig)
        or spec.channel != 1
        or vna.config.model.casefold() != "e5071c"
        or operation is None
        or scpi is None
    ):
        raise vna._configuration_error("Profile does not implement E5071C fresh acquisition.")

    def build(key: str, expected: str, trace: int | None = None) -> str:
        alias = operation.transport.get(key)
        entries = scpi.queries if expected.endswith("?") else scpi.commands
        if alias is None or alias not in (entries or {}):
            raise vna._configuration_error(f"Missing E5071C fresh acquisition alias {key!r}.")
        args = {"trace": trace} if trace is not None else {}
        commands = vna._build_profile_alias(alias, **args)
        if commands != [expected]:
            raise vna._configuration_error(f"Unverified E5071C fresh acquisition alias {key!r}.")
        return commands[0]

    queries = {
        (key, trace): build(key, expected.format(trace=trace), trace)
        for key, expected in _QUERIES.items()
        for trace in (range(1, 5) if "{trace}" in expected else (None,))
    }
    log_stimulus = build("frequency_stimulus", _LOG_STIMULUS)
    writes = {key: build(key, expected) for key, expected in _WRITES.items()}
    held = vna.config.operation_options.operation("sparameter_data")
    if held is None:
        raise vna._configuration_error("E5071C fresh acquisition requires indexed readback.")
    for key, template in _INDEXED_DATA.items():
        alias = held.transport.get(key)
        if alias is None or alias not in (scpi.queries or {}):
            raise vna._configuration_error(f"Missing indexed readback alias {key!r}.")
        traces = range(1, spec.max_traces + 1) if "{trace}" in template else (None,)
        for trace in traces:
            if vna._build_profile_alias(alias, channel=1, trace=trace) != [
                template.format(trace=trace)
            ]:
                raise vna._configuration_error(f"Unverified indexed readback alias {key!r}.")
    requested = tuple(name.strip().upper() for name in vna.config.s_parameters)
    if (
        not requested
        or len(set(requested)) != len(requested)
        or any(re.fullmatch(r"S[12][12]", name) is None for name in requested)
    ):
        raise vna._configuration_error("Request distinct two-port S-parameters.")

    def run(budget: _SweepBudget) -> SParameterData:
        def raw_query(command: str) -> str:
            return budget.exchange(command, vna._query).strip()

        def query(key: str, trace: int | None = None) -> str:
            return raw_query(queries[key, trace])

        def require_status(condition: int) -> None:
            if vna._readback_count(query("status"), "status byte", 0, 255) & 20:
                raise vna._configuration_error("VNA error queue or unexpected pending reply.")
            if (
                vna._readback_count(query("condition"), "operation condition", 0, 65535)
                != condition
            ):
                raise vna._configuration_error(
                    f"VNA operation state is not {condition}; inspect Hold/trigger status."
                )

        def identity() -> tuple[str, ...]:
            return tuple(entry.strip() for entry in query("identify").split(","))

        def snapshot(condition: int = 0) -> _Snapshot:
            require_status(condition)
            ident = identity()
            if (
                len(ident) != 4
                or any(re.fullmatch(r"[ -~]{1,128}", field) is None for field in ident)
                or ident[0].casefold() not in {"agilent technologies", "keysight technologies"}
                or ident[1].upper() != "E5071C"
                or (vna.config.serial_number is not None and ident[2] != vna.config.serial_number)
            ):
                raise vna._configuration_error("Analyzer identity is not the selected E5071C.")
            firmware = vna._firmware_tuple(ident[3].upper())
            if firmware is None or firmware[0] != "A" or firmware < ("A", 11, 20):
                raise vna._configuration_error(
                    "Fresh acquisition requires E5071C A.11.20 or later A-series firmware."
                )
            options = query("options")
            if re.fullmatch(r"[A-Za-z0-9, /]{1,256}", options) is None:
                raise vna._configuration_error("Invalid E5071C installed-options reply.")
            # *OPT? lists installed option IDs. Require a distinct hardware
            # token; absent, unrecognized or conflicting identity fails closed.
            observed_hardware = _TEST_SET_OPTIONS.intersection(
                re.split(r"[,/\s]+", options.upper())
            )
            if len(observed_hardware) != 1 or not observed_hardware <= _SUPPORTED_OPTIONS.keys():
                raise vna._configuration_error(
                    "Fresh acquisition requires exactly one E5071C hardware option 240, 260 or 280."
                )
            max_frequency = _SUPPORTED_OPTIONS[next(iter(observed_hardware))]
            mode = query("sweep_type").upper()
            if mode not in {"LIN", "LOG"}:
                raise vna._configuration_error(
                    "Fresh acquisition requires a LIN or LOG frequency sweep."
                )
            sweep_type = "linear" if mode == "LIN" else "log"
            for key, (_, expected) in _READ_STATE.items():
                if query(key).upper() != expected:
                    raise vna._configuration_error(f"VNA fresh sweep requires {key}={expected}.")
            points = vna._readback_count(
                query("points"), "sweep points", 2, min(1601, spec.max_points)
            )
            count = vna._readback_count(
                query("trace_count"), "trace count", 1, min(4, spec.max_traces)
            )
            start, stop, power = (
                vna._csv_values(query(key), 1, key)[0]
                for key in ("start_frequency", "stop_frequency", "source_power")
            )
            if not _MIN_FREQUENCY_HZ <= start < stop <= max_frequency:
                raise vna._configuration_error(
                    "Observed frequency span is outside the supported E5071C range."
                )
            # Keysight error 53 can silently return the instrument to LIN.
            if sweep_type == "log" and stop <= 4 * start:
                raise vna._configuration_error("Observed LOG span must exceed two octaves.")
            # Endpoint readback tolerates at most one hertz of quantization.
            if not -55 <= power <= _max_source_setpoint(stop + 1):
                raise vna._configuration_error(
                    "Observed source setpoint is outside the supported E5071C range."
                )
            traces = []
            for trace in range(1, count + 1):
                name = query("trace_identity", trace).upper()
                if re.fullmatch(r"S[12][12]", name) is None:
                    raise vna._configuration_error(f"Unexpected measurement on trace {trace}.")
                correction = query("trace_correction", trace).upper()
                if (
                    re.fullmatch(
                        r"(?:NONE,\s*0,\s*0,\s*0,\s*0|SOLT1,\s*[12],\s*0,\s*0,\s*0|SOLT2,\s*(?:1,\s*2|2,\s*1),\s*0,\s*0)",
                        correction,
                    )
                    is None
                ):
                    raise vna._configuration_error(
                        f"Unsupported correction or port coverage on trace {trace}."
                    )
                if query("trace_live", trace) != "1":
                    raise vna._configuration_error(f"Trace {trace} must display live data.")
                if any(
                    query(key, trace).upper() != expected
                    for key, expected in (
                        ("trace_time_transform", "0"),
                        ("trace_equation", "0"),
                        ("trace_math", "NORM"),
                        ("trace_hold", "OFF"),
                        ("trace_gating", "0"),
                        ("trace_conversion", "0"),
                    )
                ):
                    raise vna._configuration_error(
                        f"Turn off gating, conversion, time transform, equation, trace math and data hold on trace {trace}."
                    )
                traces.append((name, correction))
            if any(sum(name == observed for observed, _ in traces) != 1 for name in requested):
                raise vna._configuration_error(
                    "Each requested S-parameter must have one unique trace."
                )
            require_status(condition)
            return _Snapshot(
                ident, options, max_frequency, sweep_type, points, start, stop, power, tuple(traces)
            )

        def read_log_stimulus(state: _Snapshot, condition: int = 0) -> list[float] | None:
            if state.sweep_type != "log":
                return None
            axis = vna._csv_values(raw_query(log_stimulus), state.points, "channel stimulus")
            if (
                not _MIN_FREQUENCY_HZ <= axis[0] < axis[-1] <= state.max_frequency_hz
                or not math.isclose(axis[0], state.start_hz, rel_tol=0, abs_tol=1)
                or not math.isclose(axis[-1], state.stop_hz, rel_tol=0, abs_tol=1)
                or any(right <= left for left, right in zip(axis[:-1], axis[1:], strict=True))
            ):
                raise vna._data_error("VNA LOG channel stimulus does not match the observed span.")
            require_status(condition)
            return axis

        may_be_armed = False
        before: _Snapshot | None = None
        try:
            before = snapshot()
            stimulus = read_log_stimulus(before)
            captured_context = (
                observe_context(vna, context_plan, raw_query, "fresh_sweep")
                if context_plan is not None
                else None
            )
            if captured_context is not None and (
                captured_context.sweep_type != before.sweep_type
                or (
                    captured_context.manufacturer,
                    captured_context.model,
                    captured_context.serial_number,
                    captured_context.software_revision,
                )
                != before.identity
                or captured_context.options_reply != before.options
                or (
                    captured_context.start_hz,
                    captured_context.stop_hz,
                    captured_context.point_count,
                )
                != (before.start_hz, before.stop_hz, before.points)
            ):
                raise vna._data_error("VNA channel context does not match the observed settings.")
            budget.remaining_ms()
            may_be_armed = True
            budget.exchange(writes["arm"], vna._send_command)
            if snapshot(32) != before:
                raise vna._data_error("VNA settings changed while arming; no trigger sent.")
            if (
                context_plan is not None
                and observe_context(vna, context_plan, raw_query, "fresh_sweep", armed=True)
                != captured_context
            ):
                raise vna._data_error("VNA channel context changed while arming; no trigger sent.")
            if read_log_stimulus(before, condition=32) != stimulus:
                raise vna._data_error(
                    "VNA LOG channel stimulus changed while arming; no trigger sent."
                )
            budget.exchange(writes["trigger"], vna._send_command)
            if query("completion") not in {"1", "+1"}:
                # *OPC? cannot legitimately return another value. This could
                # be an unrelated reply, so do not send abort on this stream.
                budget.uncertain_stream = True
                raise vna._data_error("VNA fresh sweep completion was not confirmed.")
            require_status(0)
            if query("continuous") != "0":
                raise vna._configuration_error("VNA did not finish in non-continuous Hold.")
            may_be_armed = False
            if snapshot() != before:
                raise vna._data_error("VNA fresh-sweep settings changed during acquisition.")
            # Keysight documents rounding of actual LOG measurement points.
            # Preserve the indexed measured axis, and cross-check it against the
            # separate read-only channel stimulus, not a computed geometric axis.
            if read_log_stimulus(before) != stimulus:
                raise vna._data_error("VNA LOG channel stimulus changed during the sweep.")
            result = vna._read_indexed_s_parameters(spec, synchronized_query=raw_query)
            if stimulus is not None and (
                stimulus != result.frequencies or read_log_stimulus(before) != stimulus
            ):
                raise vna._data_error("VNA measured log axis disagrees with the channel stimulus.")
            if (
                len(result.frequencies) != before.points
                or not math.isclose(result.frequencies[0], before.start_hz, rel_tol=0, abs_tol=1)
                or not math.isclose(result.frequencies[-1], before.stop_hz, rel_tol=0, abs_tol=1)
                or result.frequencies[0] < _MIN_FREQUENCY_HZ
                or result.frequencies[-1] > before.max_frequency_hz
                or tuple(result.param_names) != requested
                or snapshot() != before
            ):
                raise vna._data_error(
                    "VNA observed axis, trace identity or settings did not match acquisition."
                )
            if context_plan is not None and captured_context is not None:
                vna._verify_context_axis(captured_context, result.frequencies)
                if observe_context(vna, context_plan, raw_query, "fresh_sweep") != captured_context:
                    raise vna._data_error("VNA channel context changed during fresh acquisition.")
                result._record_fresh_context(captured_context)
            result._fresh_sweep_type = before.sweep_type
            result.fresh = True
            return result
        except BaseException as error:
            if budget.uncertain_stream:
                vna._fresh_session_quarantined = True
                error.add_note(_RECOVER)
            elif may_be_armed and before is not None:
                cleanup = _SweepBudget(vna.config.model, 1000)
                try:
                    cleaned_identity = cleanup.exchange(queries["identify", None], vna._query)
                    cleaned_options = cleanup.exchange(queries["options", None], vna._query)
                    if (
                        tuple(field.strip() for field in cleaned_identity.strip().split(","))
                        != before.identity
                        or cleaned_options.strip() != before.options
                    ):
                        raise vna._data_error("VNA identity changed; abort cannot be bounded.")
                    # ABOR is global and immediately rearms continuously initiated
                    # channels. Do not send it if scope or mode is now uncertain.
                    for key, expected in (("channel_limit", "1"), ("continuous", "0")):
                        observed = cleanup.exchange(queries[key, None], vna._query)
                        if observed.strip() != expected:
                            raise vna._data_error(
                                "VNA scope or mode changed; abort cannot be bounded."
                            )
                    cleanup.exchange(writes["abort"], vna._send_command)
                    for key, expected in (("condition", "0"), ("continuous", "0")):
                        observed = cleanup.exchange(queries[key, None], vna._query)
                        if observed.strip() != expected:
                            raise vna._data_error("VNA Hold was not verified after abort.")
                except BaseException as cleanup_error:
                    vna._fresh_session_quarantined = True
                    error.add_note(f"{_RECOVER} Cleanup failed: {cleanup_error}.")
                else:
                    error.add_note("VNA abort returned to Hold; verify the DUT and error queue.")
            raise

    budget = _SweepBudget(vna.config.model, timeout_ms)
    with vna._operation_lock:
        vna._require_fresh_session()
        vna._ensure_backend_connected()
        with vna._profile_transaction():
            return run(budget)
