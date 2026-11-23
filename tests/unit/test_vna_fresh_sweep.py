"""Manual-backed E5071C fresh protocol on a scripted, substate-aware transport."""

import csv
import json
from dataclasses import replace

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from pytestlab import Bench
from pytestlab import Experiment
from pytestlab import MeasurementSession
from pytestlab.cli_typer import _profile_scpi_command_rows
from pytestlab.cli_typer import _semantic_operation_rows
from pytestlab.cli_typer import app
from pytestlab.config.loader import load_device_profile
from pytestlab.devices import register_backend
from pytestlab.devices import registry
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.instruments.VectorNetworkAnalyser import VectorNetworkAnalyser
from pytestlab.uncertainty import AtomRegistry
from pytestlab.uncertainty import QuantityArray


class Ena:
    is_simulated = False

    def __init__(self):
        self.writes = []
        self.queries = []
        self.timeout = 750
        self.condition = "0"
        self.complete = False
        self.connects = 0
        self.values = {
            "*IDN?": "Keysight Technologies,E5071C,SER123,A.11.20",
            "*OPT?": "280,008,010",
            "*STB?": "0",
            ":SERV:CHAN:COUN?": "1",
            ":SERV:PORT:COUN?": "2",
            ":TRIG:SOUR?": "BUS",
            ":TRIG:POIN?": "0",
            ":TRIG:OUTP:STAT?": "0",
            ":TRIG:AVER?": "0",
            ":SENS1:AVER?": "0",
            ":OUTP?": "1",
            ":FORM:DATA?": "ASC",
            ":INIT1:CONT?": "0",
            ":SENS1:SWE:TYPE?": "LIN",
            ":SENS1:SWE:GEN?": "STEP",
            ":CALC1:FSIM:STAT?": "0",
            ":SENS1:OFFS:STAT?": "0",
            ":SENS1:SWE:SLOC:STAT?": "0",
            ":SENS1:OFFS:LOC:STAT?": "0",
            ":SENS1:OFFS:LOC:CONT?": "0",
            ":SYST:TSET?": "OFF",
            ":SENS:MULT1:STAT?": "0",
            ":SENS:MULT2:STAT?": "0",
            ":SOUR1:POW:PORT:COUP?": "1",
            ":SOUR1:POW:SLOP:STAT?": "0",
            ":SOUR1:POW:PORT1:CORR?": "0",
            ":SOUR1:POW:PORT2:CORR?": "0",
            ":SOUR1:POW:PORT1:CORR:COLL:TABL:LOSS?": "0",
            ":SOUR1:POW:PORT2:CORR:COLL:TABL:LOSS?": "0",
            ":SENS1:SWE:POIN?": "3",
            ":SENS1:FREQ:STAR?": "1e6",
            ":SENS1:FREQ:STOP?": "3e6",
            ":SENS1:FREQ:SPAN?": "2e6",
            ":SENS1:BWID?": "1000",
            ":SENS1:AVER:COUN?": "8",
            ":SENS:CORR:IMP:INP:MAGN?": "75",
            ":SENS1:CORR:EXT:STAT?": "0",
            ":CALC1:TRAC2:MARK1:STAT?": "1",
            ":CALC1:TRAC2:MARK:REF:STAT?": "0",
            ":CALC1:TRAC2:FORM?": "MLOG",
            ":DISP:WIND1:TRAC2:MEM?": "0",
            ":CALC1:TRAC2:MARK1:DATA?": "-32.5,0,1.9e6",
            ":SOUR1:POW?": "-25",
            ":CALC1:PAR:COUN?": "2",
            ":CALC1:PAR1:DEF?": "S21",
            ":CALC1:PAR2:DEF?": "S11",
            ":SENS1:CORR:TYPE1?": "SOLT2,1,2,0,0",
            ":SENS1:CORR:TYPE2?": "NONE,0,0,0,0",
        }
        for trace in (1, 2):
            self.values[f":DISP:WIND1:TRAC{trace}:STAT?"] = "1"
            for key in ("TRAN:TIME:STAT", "EQU:STAT", "FILT:GATE:TIME:STAT", "CONV:STAT"):
                self.values[f":CALC1:TRAC{trace}:{key}?"] = "0"
            self.values[f":CALC1:TRAC{trace}:MATH:FUNC?"] = "NORM"
            self.values[f":CALC1:TRAC{trace}:HOLD:TYPE?"] = "OFF"
            self.values[f":CALC1:TRAC{trace}:DATA:XAX?"] = "1e6,2e6,3e6"
            self.values[f":CALC1:TRAC{trace}:DATA:SDAT?"] = f"{trace},0,.5,-.3,1,-1"

    def connect(self):
        self.connects += 1

    def disconnect(self):
        pass

    def set_timeout(self, timeout_ms):
        self.timeout = timeout_ms

    def get_timeout(self):
        return self.timeout

    def query(self, command, delay=None):
        self.queries.append(command)
        if command in self.values:
            value = self.values[command]
            if isinstance(value, BaseException):
                raise value
            return value.pop(0) if isinstance(value, list) else value
        if command == ":STAT:OPER:COND?":
            return self.condition
        if command == "*OPC?":
            assert self.writes == [":INIT1", ":TRIG:SING"]
            self.complete = True
            self.condition = "0"
            return "1"
        raise AssertionError(command)

    def write(self, command):
        self.writes.append(command)
        if command == ":INIT1":
            assert self.condition == "0"
            self.condition = "32"
        elif command == ":TRIG:SING":
            assert self.condition == "32"
            self.condition = "16"
        elif command == ":ABOR":
            self.condition = "0"
        else:
            raise AssertionError(f"Unexpected write: {command}")


@pytest.fixture
def ena():
    backend = Ena()
    return VectorNetworkAnalyser(load_device_profile("keysight/E5071C_VNA"), backend), backend


def test_one_new_sweep_then_observed_complex_data(ena):
    vna, backend = ena
    assert vna.supports_operation("sparameter_sweep_acquire")
    result = vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1", ":TRIG:SING"]
    assert backend.complete and backend.condition == "0" and backend.timeout == 750
    assert backend.queries.index("*OPC?") < backend.queries.index(":CALC1:TRAC1:DATA:SDAT?")
    assert result.fresh and result.trace_identity_verified and result.sweep_type == "linear"
    assert ":SENS1:FREQ:DATA?" not in backend.queries
    assert result.param_names == ["S11", "S21"]
    assert result.frequencies == [1e6, 2e6, 3e6]
    assert result.s_params == [[2 + 0j, 0.5 - 0.3j, 1 - 1j], [1 + 0j, 0.5 - 0.3j, 1 - 1j]]
    held = vna.get_s_parameter_data()
    assert not held.fresh
    queries = list(backend.queries)
    for capture, is_fresh in ((result, True), (held, False)):
        measurement = capture.to_measurement_result()
        info = measurement.envelope["vna"]
        assert measurement.envelope["timestamp_kind"] == "host_receipt"
        assert info["capture_origin"] == "driver"
        assert info["axis_source"] == "instrument" and info["trace_identity_verified"]
        assert info["fresh"] is is_fresh and info["sweep_type"] == "linear"
        assert info["identity"]["serial_number"] == "SER123" and info["channel"] == 1
        assert info["trace_slots"] == {"S11": 2, "S21": 1}
        assert info["context"] is None
    assert backend.queries == queries
    assert backend.writes == [":INIT1", ":TRIG:SING"]


_LOG_AXIS = "1e6,2828427,8e6"


def _set_log_sweep(backend):
    backend.values[":SENS1:SWE:TYPE?"] = "LOG"
    backend.values[":SENS1:FREQ:STOP?"] = "8e6"
    backend.values[":SENS1:FREQ:SPAN?"] = "7e6"
    backend.values[":SENS1:FREQ:DATA?"] = _LOG_AXIS
    for trace in (1, 2):
        backend.values[f":CALC1:TRAC{trace}:DATA:XAX?"] = _LOG_AXIS


def test_bench_alias_acquires_log_and_exports_same_measured_bins(tmp_path, monkeypatch):
    backend = Ena()
    _set_log_sweep(backend)
    registry.ensure_builtin_registrations()
    monkeypatch.setattr(registry, "_backends", registry._backends.copy())
    register_backend("offline_ena_log", lambda _: backend)
    descriptor = tmp_path / "bench.yaml"
    descriptor.write_text(
        "bench_name: Offline fresh log sweep\n"
        "instruments:\n"
        "  vna:\n"
        "    profile: keysight/E5071C_VNA\n"
        "    address: 'TCPIP0::192.0.2.10::inst0::INSTR'\n"
        "    backend: {type: offline_ena_log}\n",
        encoding="utf-8",
    )
    with Bench.open(descriptor, aliases={"vna"}, start_experiment=False) as bench:
        result = bench.vna.acquire_s_parameter_sweep(include_context=True)
        assert result.fresh and result.sweep_type == result.context.sweep_type == "log"
        assert result.context.evidence == "fresh_sweep"
        assert result.axis_source == "instrument" and result.trace_identity_verified
        assert result.frequencies == [1e6, 2828427, 8e6]
        assert result.trace("S11").values[0] == 2 + 0j
        assert result.trace("S21").at_frequency(2828427).value == 0.5 - 0.3j
        destination = tmp_path / "fresh_log.csv"
        result.to_csv(destination)

    with destination.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [float(row["frequency_hz"]) for row in rows] == result.frequencies
    assert rows[1]["fresh"] == "true" and rows[1]["S21_imag"] == "-0.3"
    assert backend.writes == [":INIT1", ":TRIG:SING"]
    opc = backend.queries.index("*OPC?")
    trace_reads = [
        i
        for i, command in enumerate(backend.queries)
        if "DATA:XAX" in command or "DATA:SDAT" in command
    ]
    stimulus_reads = [
        i for i, command in enumerate(backend.queries) if command == ":SENS1:FREQ:DATA?"
    ]
    assert len(stimulus_reads) == 4
    assert stimulus_reads[1] < opc < stimulus_reads[2] < min(trace_reads)
    assert max(trace_reads) < stimulus_reads[3]


@pytest.mark.parametrize(
    "command,reply",
    [
        (":SENS1:SWE:TYPE?", "SEGM"),
        (":SENS1:SWE:GEN?", "ANAL"),
        (":SENS1:FREQ:STOP?", "4e6"),
        (":SENS1:FREQ:STOP?", "3e6"),
    ],
)
def test_rejects_unsupported_log_type_generation_or_span(ena, command, reply):
    vna, backend = ena
    _set_log_sweep(backend)
    backend.values[command] = reply
    with pytest.raises(InstrumentConfigurationError):
        vna.acquire_s_parameter_sweep()
    assert not backend.writes
    assert ":SENS1:FREQ:DATA?" not in backend.queries


def test_log_drift_while_armed_aborts_without_trigger(ena):
    vna, backend = ena
    _set_log_sweep(backend)
    backend.values[":SENS1:SWE:TYPE?"] = ["LOG", "LIN"]
    with pytest.raises(InstrumentDataError, match="changed while arming"):
        vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1", ":ABOR"]


@pytest.mark.parametrize(
    "response",
    ["999998,2828427,8e6", "1e6,2828427,8000002", "1e6,8e6,8e6", "1e6,8e6"],
)
def test_log_checks_planned_stimulus_against_observed_span_before_arm(ena, response):
    vna, backend = ena
    _set_log_sweep(backend)
    backend.values[":SENS1:FREQ:DATA?"] = response
    with pytest.raises(InstrumentDataError, match="channel stimulus"):
        vna.acquire_s_parameter_sweep()
    assert not backend.writes


def test_log_stimulus_drift_while_armed_aborts_without_trigger(ena):
    vna, backend = ena
    _set_log_sweep(backend)
    backend.values[":SENS1:FREQ:DATA?"] = [_LOG_AXIS, "1e6,2828527,8e6"]
    with pytest.raises(InstrumentDataError, match="stimulus changed while arming"):
        vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1", ":ABOR"]


@pytest.mark.parametrize(
    "command,reply",
    [
        (":SENS1:FREQ:DATA?", [_LOG_AXIS] * 2 + ["1e6,2828527,8e6"]),
        (":SENS1:FREQ:DATA?", [_LOG_AXIS] * 3 + ["1e6,2828527,8e6"]),
        (":CALC1:TRAC1:DATA:XAX?", "1e6,2828527,8e6"),
        (":CALC1:TRAC1:DATA:SDAT?", "1.#QNB,0,0,0,0,0"),
    ],
)
def test_log_rejects_wrong_stimulus_or_unpaired_data_after_trigger(ena, command, reply):
    vna, backend = ena
    _set_log_sweep(backend)
    backend.values[command] = reply
    with pytest.raises(InstrumentDataError):
        vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1", ":TRIG:SING"] and backend.complete


def test_log_stimulus_timeout_does_not_read_or_retry(ena):
    vna, backend = ena
    _set_log_sweep(backend)
    backend.values[":SENS1:FREQ:DATA?"] = TimeoutError("late stimulus reply")
    with pytest.raises(InstrumentCommunicationError, match="late stimulus reply"):
        vna.acquire_s_parameter_sweep()
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        vna.get_s_parameter_data()
    assert not backend.writes
    assert not any("DATA:SDAT" in command for command in backend.queries)


def test_log_stimulus_alias_verified_before_io(ena):
    vna, backend = ena
    assert vna.config.scpi is not None and vna.config.scpi.queries is not None
    del vna.config.scpi.queries["fresh_frequency_stimulus"]
    with pytest.raises(InstrumentConfigurationError, match="frequency_stimulus"):
        vna.acquire_s_parameter_sweep()
    assert not backend.connects and not backend.writes and not backend.queries


def test_fresh_acquisition_remains_direct_python_only(ena, monkeypatch):
    vna, backend = ena

    def unexpected_io(*args, **kwargs):
        pytest.fail("Generic dispatch must not call fresh acquisition")

    operation = vna.describe_operation("sparameter_sweep_acquire")
    assert operation["python_only"] is True
    assert "python_arguments" not in operation
    monkeypatch.setattr("pytestlab.cli_typer._operation_instrument", lambda *a, **kw: vna)
    monkeypatch.setattr(vna, "acquire_s_parameter_sweep", unexpected_io)
    response = CliRunner().invoke(
        app,
        [
            "instrument",
            "execute-operation",
            "keysight/E5071C_VNA",
            "sparameter_sweep_acquire",
        ],
    )
    assert response.exit_code == 1
    error = json.loads(response.stdout)["error"]
    assert error["code"] == "python_only_operation"
    assert "direct Python call" in error["message"]

    descriptors = tuple(
        descriptor
        for descriptor in vna.operation_descriptors()
        if descriptor.operation_id == "sparameter_sweep_acquire"
    )
    monkeypatch.setattr(vna, "operation_descriptors", lambda: descriptors)
    rows, failures, warnings, _ = _semantic_operation_rows(vna, include_writes=True)
    assert failures == warnings == 0
    assert len(rows) == 1 and rows[0]["status"] == "skip"
    assert "direct Python call" in rows[0]["detail"]
    assert not backend.connects and not backend.writes and not backend.queries


def test_bulk_live_diagnostics_skip_fresh_transaction_writes(ena, tmp_path, monkeypatch):
    vna, backend = ena
    profile = tmp_path / "aliases.yaml"
    profile.write_text(
        "scpi:\n"
        "  commands:\n"
        "    fresh_arm: {template: ':INIT1'}\n"
        "    fresh_trigger: {template: ':TRIG:SING'}\n"
        "    fresh_abort: {template: ':ABOR'}\n"
        "    clear_status: {template: '*CLS'}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(vna, "write", backend.writes.append)
    _, rows, failures, warnings, skipped = _profile_scpi_command_rows(
        str(profile), device=vna, include_writes=True, strict_response=True
    )
    assert failures == warnings == 0
    assert skipped == 4
    assert rows[0]["detail"] == "reserved for a direct Python operation"
    assert [(row["alias"], row["status"]) for row in rows] == [
        ("fresh_arm", "skip"),
        ("fresh_trigger", "skip"),
        ("fresh_abort", "skip"),
        ("clear_status", "skip"),
    ]
    assert not backend.writes

    _, offline, failures, warnings, skipped = _profile_scpi_command_rows(
        str(profile), strict_response=False
    )
    assert failures == warnings == skipped == 0
    assert [row["detail"] for row in offline] == [":INIT1", ":TRIG:SING", ":ABOR", "*CLS"]
    assert not backend.writes


@pytest.mark.parametrize(
    "command,value",
    [
        ("*IDN?", "Unknown Maker,E5071C,SER123,A.11.20"),
        ("*IDN?", "Keysight Technologies,E5072A,SER123,A.11.20"),
        ("*IDN?", "Keysight Technologies,E5071C,,A.11.20"),
        ("*IDN?", "Keysight Technologies,E5071C,SER123,A.09.60"),
        ("*OPT?", "480"),
        ("*STB?", "4"),
        ("*STB?", "16"),
        (":SERV:CHAN:COUN?", "160"),
        (":SERV:PORT:COUN?", "4"),
        (":STAT:OPER:COND?", "32"),
        (":INIT1:CONT?", "1"),
        (":TRIG:SOUR?", "EXT"),
        (":TRIG:POIN?", "1"),
        (":TRIG:AVER?", "1"),
        (":TRIG:OUTP:STAT?", "1"),
        (":SENS1:OFFS:LOC:STAT?", "1"),
        (":SENS1:OFFS:LOC:CONT?", "1"),
        (":SENS:MULT2:STAT?", "1"),
        (":SOUR1:POW:SLOP:STAT?", "1"),
        (":SOUR1:POW:PORT:COUP?", "0"),
        (":SOUR1:POW:PORT2:CORR?", "1"),
        (":SOUR1:POW:PORT2:CORR:COLL:TABL:LOSS?", "1"),
        (":OUTP?", "0"),
        (":SENS1:SWE:TYPE?", "SEGM"),
        (":SENS1:SWE:TYPE?", "POW"),
        (":SENS1:SWE:GEN?", "ANAL"),
        (":SOUR1:POW?", "-55.1"),
        (":SOUR1:POW?", "10.1"),
        (":SENS1:FREQ:STAR?", "8999"),
        (":SENS1:FREQ:STOP?", "8.500001e9"),
        (":CALC1:PAR2:DEF?", "S31"),
        (":DISP:WIND1:TRAC2:STAT?", "0"),
        (":SENS1:SWE:SLOC:STAT?", "1"),
        (":SENS1:CORR:TYPE2?", "SOLT3,1,2,3,0"),
        (":CALC1:TRAC2:HOLD:TYPE?", "MAX"),
        (":CALC1:TRAC2:FILT:GATE:TIME:STAT?", "1"),
    ],
)
def test_refuses_unsupported_observed_state_before_arm(ena, command, value):
    vna, backend = ena
    backend.values[command] = value
    with pytest.raises(InstrumentConfigurationError):
        vna.acquire_s_parameter_sweep()
    assert not backend.writes


def test_waiting_recheck_can_abort_without_trigger(ena):
    vna, backend = ena
    backend.values[":SOUR1:POW?"] = ["-25", "-21"]
    with pytest.raises(InstrumentDataError, match="changed while arming"):
        vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1", ":ABOR"]


def test_opc_timeout_does_not_read_stale_data_or_reuse_stream(ena):
    vna, backend = ena
    backend.values["*OPC?"] = TimeoutError("late sweep response")
    with pytest.raises(InstrumentCommunicationError, match="late sweep response") as caught:
        vna.acquire_s_parameter_sweep()
    assert any("quarantined" in note for note in caught.value.__notes__)
    assert backend.writes == [":INIT1", ":TRIG:SING"]
    before = len(backend.queries)
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        vna.get_s_parameter_data()
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        vna.acquire_s_parameter_sweep()
    assert len(backend.queries) == before
    assert not any("DATA:SDAT" in query for query in backend.queries)


def test_invalid_completion_quarantines_uncertain_session(ena):
    vna, backend = ena
    backend.values["*OPC?"] = "0"
    with pytest.raises(InstrumentDataError, match="completion"):
        vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1", ":TRIG:SING"]
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        vna.get_s_parameter_data()


@pytest.mark.parametrize(
    "command,value",
    [
        (":CALC1:TRAC2:DATA:SDAT?", "NaN,0,.5,-.3,1,-1"),
        (":CALC1:TRAC2:DATA:XAX?", "1e6,2.1e6,3e6"),
    ],
)
def test_fresh_result_still_requires_verified_trace_data(ena, command, value):
    vna, backend = ena
    backend.values[command] = value
    with pytest.raises(InstrumentDataError):
        vna.acquire_s_parameter_sweep()
    assert backend.complete and backend.writes == [":INIT1", ":TRIG:SING"]


def test_continuous_drift_never_aborts_and_rearms_other_state(ena):
    vna, backend = ena
    backend.values[":INIT1:CONT?"] = ["0", "1", "1"]
    with pytest.raises(InstrumentConfigurationError, match="continuous") as caught:
        vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1"]
    assert any("quarantined" in note for note in caught.value.__notes__)


def test_missing_indexed_data_plan_refuses_before_connect(ena):
    vna, backend = ena
    assert vna.config.scpi is not None and vna.config.scpi.queries is not None
    del vna.config.scpi.queries["readback_trace_axis"]
    with pytest.raises(InstrumentConfigurationError, match="indexed readback alias 'trace_axis'"):
        vna.acquire_s_parameter_sweep()
    assert not backend.connects and not backend.writes and not backend.queries


@pytest.mark.parametrize("reply", ["285,008,010", "280,285,008,010", "008,010", "1280,008,010"])
def test_live_hardware_option_required(ena, reply):
    vna, backend = ena
    backend.values["*OPT?"] = reply
    with pytest.raises(InstrumentConfigurationError, match="exactly one E5071C hardware option"):
        vna.acquire_s_parameter_sweep()
    assert not backend.writes


@pytest.mark.parametrize("stop_hz,level", [(5e9, 10), (6e9, 9), (7e9, 8), (8.5e9, 10)])
def test_live_power_uses_stricter_high_frequency_band(ena, stop_hz, level):
    vna, backend = ena
    backend.values[":SENS1:FREQ:STOP?"] = str(stop_hz)
    backend.values[":SOUR1:POW?"] = str(level)
    with pytest.raises(InstrumentConfigurationError, match="source setpoint"):
        vna.acquire_s_parameter_sweep()
    assert not backend.writes


def test_analyzer_matches_profile_serial_if_configured(ena):
    vna, backend = ena
    vna.config.serial_number = "DIFFERENT"
    with pytest.raises(InstrumentConfigurationError, match="identity"):
        vna.acquire_s_parameter_sweep()
    assert not backend.writes


def test_identity_drift_while_armed_never_triggers_or_aborts_another_analyzer(ena):
    vna, backend = ena
    before = backend.values["*IDN?"]
    changed = before.replace("SER123", "SER456")
    backend.values["*IDN?"] = [before, changed, changed]
    with pytest.raises(InstrumentDataError, match="changed while arming") as caught:
        vna.acquire_s_parameter_sweep()
    assert backend.writes == [":INIT1"]
    assert any("identity changed" in note for note in caught.value.__notes__)


def test_read_only_context_catalogue_and_opt_in_held_provenance(ena, tmp_path):
    vna, backend = ena
    context = vna.get_s_parameter_channel_context()
    assert context.evidence == "live_configuration"
    assert context.model == "E5071C"
    assert context.serial_number == "SER123"
    assert context.software_revision == "A.11.20"
    assert context.hardware_revision is None
    assert context.options_reply == "280,008,010"
    assert context.channel == 1
    assert context.sweep_type == "linear"
    assert (context.start_hz, context.stop_hz, context.point_count) == (1e6, 3e6, 3)
    assert (context.if_bandwidth_hz, context.averaging_enabled, context.averaging_count) == (
        1000,
        False,
        8,
    )
    assert context.port_count == 2
    assert context.port_reference_ohms == (75, 75)
    assert context.correction_enabled is None
    assert (context.trace(1).parameter, context.trace(1).correction_ports) == ("S21", (1, 2))
    assert context.trace(2).correction_method == "NONE"
    with pytest.raises(KeyError):
        context.trace(0)
    assert not backend.writes and not any(":DATA:" in cmd for cmd in backend.queries)
    held = vna.get_s_parameter_data(include_context=True)
    assert held.context == replace(context, evidence="held_readback")
    assert held.trace("s11").context == context.trace(2)
    assert held.trace("s21").context == context.trace(1)
    assert not held.fresh
    with pytest.raises(ValueError, match="characterized fresh"):
        held.to_touchstone(tmp_path / "held.s2p")
    assert not (tmp_path / "held.s2p").exists()
    assert not backend.writes


def test_context_detects_reference_impedance_and_trace_catalogue_changes(ena):
    vna, backend = ena
    backend.values[":SENS:CORR:IMP:INP:MAGN?"] = ["50", "75"]
    with pytest.raises(InstrumentDataError, match="changed during inspection"):
        vna.get_s_parameter_channel_context()
    assert not backend.writes


@pytest.mark.parametrize("response", ["NONE", "SOLT2,1,1,0,0", "SOLT1,2,1,0,0", "UNKNOWN,0,0,0,0"])
def test_context_rejects_invalid_ena_correction_reply(ena, response):
    vna, backend = ena
    backend.values[":SENS1:CORR:TYPE1?"] = response
    with pytest.raises(InstrumentDataError, match="correction"):
        vna.get_s_parameter_channel_context()
    assert not backend.writes


def test_context_timeout_quarantines_even_for_legacy_held_read(ena):
    vna, backend = ena
    backend.values[":SENS:CORR:IMP:INP:MAGN?"] = TimeoutError("lost context reply")
    with pytest.raises(InstrumentCommunicationError, match="lost context reply"):
        vna.get_s_parameter_channel_context()
    before = len(backend.queries)
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        vna.get_s_parameter_data()
    assert len(backend.queries) == before and not backend.writes


def test_fresh_context_change_while_armed_blocks_trigger(ena):
    vna, backend = ena
    backend.values[":SENS:CORR:IMP:INP:MAGN?"] = ["50", "75"]
    with pytest.raises(InstrumentDataError, match="context changed while arming"):
        vna.acquire_s_parameter_sweep(include_context=True)
    assert backend.writes == [":INIT1", ":ABOR"]


@pytest.mark.parametrize("port_extension", ["0", "1"])
def test_full_fresh_sweep_exports_responding_then_stimulus_port_order_and_read_z0(
    ena, tmp_path, port_extension
):
    vna, backend = ena
    vna.config.s_parameters = ["S22", "S11", "S12", "S21"]
    backend.values[":SENS1:CORR:EXT:STAT?"] = port_extension
    backend.values[":CALC1:PAR:COUN?"] = "4"
    for slot, name in ((3, "S22"), (4, "S12")):
        backend.values[f":CALC1:PAR{slot}:DEF?"] = name
        backend.values[f":SENS1:CORR:TYPE{slot}?"] = "SOLT2,1,2,0,0"
        backend.values[f":DISP:WIND1:TRAC{slot}:STAT?"] = "1"
        for tag in ("TRAN:TIME:STAT", "EQU:STAT", "FILT:GATE:TIME:STAT", "CONV:STAT"):
            backend.values[f":CALC1:TRAC{slot}:{tag}?"] = "0"
        backend.values[f":CALC1:TRAC{slot}:MATH:FUNC?"] = "NORM"
        backend.values[f":CALC1:TRAC{slot}:HOLD:TYPE?"] = "OFF"
        backend.values[f":CALC1:TRAC{slot}:DATA:XAX?"] = "1e6,2e6,3e6"
        backend.values[f":CALC1:TRAC{slot}:DATA:SDAT?"] = f"{slot},0,.5,-.3,1,-1"

    result = vna.acquire_s_parameter_sweep(include_context=True)
    assert result.context is not None and result.context.evidence == "fresh_sweep"
    assert backend.writes == [":INIT1", ":TRIG:SING"]
    native = result.to_measurement_result()
    context = native.envelope["vna"]["context"]
    assert context["evidence"] == "fresh_sweep" and context["port_reference_ohms"] == [75, 75]
    assert context["traces"][0]["correction_ports"] == [1, 2]
    experiment = Experiment("Native E5071C sweep")
    experiment.add_trial(result)
    assert len(experiment) == 1
    row = experiment.data.row(0, named=True)
    assert row["result"] == native.values.to_dicts()
    assert json.loads(row["result__measurement"])["result"]["envelope"] == native.envelope
    with MeasurementSession("Native E5071C sweep session", compliance=False) as session:
        session.parameter("trial", [1])

        @session.acquire
        def sweep():
            return result

        trial = session.run(show_progress=False)
    with MeasurementDatabase(tmp_path / "vna") as db:
        key = db.store_experiment(None, trial)
        restored = db.retrieve_experiment(key).data
    assert restored.height == 1
    samples = restored["sweep"][0].struct.unnest()
    assert samples.equals(native.values)
    assert samples.select("frequency_hz", "S22_real", "S22_imag").rows() == [
        (1e6, 3.0, 0.0),
        (2e6, 0.5, -0.3),
        (3e6, 1.0, -1.0),
    ]
    recorded = json.loads(restored["sweep__measurement"][0])["result"]
    assert recorded["timestamp"] == native.timestamp
    assert recorded["envelope"] == native.envelope
    assert recorded["envelope"]["vna"]["trace_slots"] == {"S22": 3, "S11": 2, "S12": 4, "S21": 1}
    path = tmp_path / "measured.s2p"
    if port_extension == "1":
        assert result.context.port_extension_enabled
        with pytest.raises(ValueError, match="port extension off"):
            result.to_touchstone(path)
        assert not path.exists()
        return
    result.to_touchstone(path)
    contents = path.read_text().splitlines()
    assert contents[2] == "# Hz S RI R 75"
    assert list(map(float, contents[3].split())) == [1e6, 2, 0, 1, 0, 4, 0, 3, 0]
    assert len(contents) == 6
    with pytest.raises(FileExistsError):
        result.to_touchstone(path)
    with pytest.raises(ValueError, match="extension"):
        result.to_touchstone(tmp_path / "incorrect.s1p")
    result.s_params[0][0] += 1
    with pytest.raises(ValueError, match="modified VNA payload"):
        result.to_measurement_result()
    with pytest.raises(ValueError, match="unchanged"):
        result.to_touchstone(path, overwrite=True)
    assert path.read_text().splitlines() == contents


def test_fresh_partial_data_cannot_be_filled_with_invented_values(ena, tmp_path):
    vna, _ = ena
    result = vna.acquire_s_parameter_sweep(include_context=True)
    with pytest.raises(ValueError, match="requires S11, S21, S12, and S22"):
        result.to_touchstone(tmp_path / "partial.s2p")
    assert not (tmp_path / "partial.s2p").exists()


def test_ena_reads_enabled_absolute_marker_without_selecting_a_trace(ena):
    vna, backend = ena
    marker = vna.get_s_parameter_frequency_marker(2)
    assert (marker.channel, marker.trace_slot, marker.marker, marker.parameter) == (1, 2, 1, "S11")
    assert (marker.frequency_hz, marker.magnitude_db) == (1.9e6, -32.5)
    assert backend.queries.count(":CALC1:TRAC2:MARK1:DATA?") == 2
    assert not backend.writes


@pytest.mark.parametrize(
    ("command", "value", "diagnostic"),
    [
        (":CALC1:TRAC2:MARK1:STAT?", "0", "state"),
        (":CALC1:TRAC2:MARK:REF:STAT?", "1", "reference"),
        (":CALC1:TRAC2:FORM?", "PHAS", "format"),
        (":DISP:WIND1:TRAC2:MEM?", "1", "display_memory"),
        (":CALC1:TRAC2:TRAN:TIME:STAT?", "1", "time_transform"),
    ],
)
def test_ena_marker_does_not_read_unsupported_display_context(ena, command, value, diagnostic):
    vna, backend = ena
    backend.values[command] = value
    with pytest.raises(InstrumentConfigurationError, match=diagnostic):
        vna.get_s_parameter_frequency_marker(2)
    assert ":CALC1:TRAC2:MARK1:DATA?" not in backend.queries
    assert not backend.writes


@pytest.mark.parametrize("value", ["-32.5,1,1.9e6", "-32.5,0,3.1e6", "9.9e37,0,1.9e6"])
def test_ena_marker_rejects_unphysical_format_or_stimulus(ena, value):
    vna, backend = ena
    backend.values[":CALC1:TRAC2:MARK1:DATA?"] = value
    with pytest.raises(InstrumentDataError, match="absolute log-magnitude"):
        vna.get_s_parameter_frequency_marker(2)
    assert not backend.writes


@pytest.mark.parametrize(("trace", "marker"), [(True, 1), (17, 1), (1, 0), (1, 10)])
def test_invalid_ena_marker_or_slot_never_connects(ena, trace, marker):
    vna, backend = ena
    with pytest.raises(InstrumentConfigurationError):
        vna.get_s_parameter_frequency_marker(trace, marker)
    assert not backend.connects


@pytest.fixture
def ena_segment_table(ena):
    _, backend = ena
    backend.values.update(
        {
            ":SENS1:SWE:TYPE?": "SEGM",
            ":SENS1:SEGM:DATA?": "6,0,1,1,1,1,1,2,2e6,1e6,3,10e3,-15,.02,2,0,4e6,4e6,1,1e3,-20,0,0,.3",
            ":SENS1:SEGM:LIST:CONT:STAT?": "1",
            ":SENS1:SEGM:LIST:CONT:DATA?": "1,0",
            ":SENS1:SEGM:ARB:STAT?": "1",
        }
    )
    return ena


def test_ena_inspects_segment_buffer_six_with_order_state_and_optional_fields(ena_segment_table):
    vna, backend = ena_segment_table
    assert vna.supports_operation("sparameter_segment_table")
    report = vna.get_s_parameter_segment_table()
    assert (report.serial_number, report.software_revision, report.channel) == (
        "SER123",
        "A.11.20",
        1,
    )
    assert report.active_sweep_type == "segment" and report.frequency_mode == "start_stop"
    assert report.individual_state_control and report.arbitrary_segments_enabled
    first, second = report.segments
    assert (first.index, first.start_hz, first.stop_hz, first.point_count) == (1, 2e6, 1e6, 3)
    assert (first.if_bandwidth_hz, first.power_dbm, first.delay_s) == (10_000, -15, 0.02)
    assert first.sweep_mode == "stepped" and first.sweep_time_s == 0 and first.enabled
    assert (second.index, second.start_hz, second.stop_hz, second.point_count) == (2, 4e6, 4e6, 1)
    assert second.enabled is False and second.sweep_time_s == 0.3
    assert not backend.writes and backend.queries.count(":SENS1:SEGM:DATA?") == 2
    assert all("SDAT" not in query and "XAX" not in query for query in backend.queries)


def test_ena_inspects_inactive_segment_table_on_older_supported_firmware(ena_segment_table):
    vna, backend = ena_segment_table
    backend.values.update(
        {
            "*IDN?": "Agilent Technologies,E5071C,SER123,A.09.60",
            ":SENS1:SWE:TYPE?": "LOG",
            ":SENS1:SEGM:DATA?": "+5.0,1,1,0,0,0,2,2e6,2e6,3,1e3,4e6,2e6,5,100",
            ":SENS1:SEGM:LIST:CONT:STAT?": "0",
        }
    )
    report = vna.get_s_parameter_segment_table()
    assert report.active_sweep_type == "log" and report.frequency_mode == "center_span"
    assert report.arbitrary_segments_enabled is None and report.individual_state_control is False
    first, second = report.segments
    assert (first.start_hz, first.stop_hz, first.if_bandwidth_hz) == (1e6, 3e6, 1000)
    assert second.enabled and second.power_dbm is None and second.sweep_mode is None
    assert all(
        query not in backend.queries
        for query in (":SENS1:SEGM:LIST:CONT:DATA?", ":SENS1:SEGM:ARB:STAT?")
    )


@pytest.mark.parametrize(
    ("command", "reply", "message"),
    [
        (":SENS1:SEGM:DATA?", "6,0,0,0,0,0,0,1,1e6,2e6,3", "option flags"),
        (":SENS1:SEGM:DATA?", "5,0,0,0,0,0,2,1e6,2e6,3", "declared fields"),
        (":SENS1:SEGM:DATA?", "5,0,0,0,0,0,202,1e6,2e6,3", "segment count"),
        (":SENS1:SEGM:DATA?", "5,0,0,0,0,0,1,1e6,2e6,1", "point count"),
        (":SENS1:SEGM:DATA?", "5,1,0,0,0,0,1,1e6,-2e6,2", "negative span"),
        (":SENS1:SEGM:LIST:CONT:DATA?", "1", "Expected 2 segment state"),
        (":SENS1:SEGM:LIST:CONT:DATA?", "1,2", "non-Boolean"),
        (":SENS1:SEGM:ARB:STAT?", "0", "requires enabled arbitrary"),
        (":SENS1:SEGM:LIST:CONT:DATA?", ["1,0", "0,1"], "table changed"),
        (":SENS1:SWE:TYPE?", ["SEGM", "LOG"], "table changed"),
    ],
)
def test_ena_segment_declines_malformed_or_unstable_table(
    ena_segment_table, command, reply, message
):
    vna, backend = ena_segment_table
    backend.values[command] = reply
    with pytest.raises(InstrumentDataError, match=message):
        vna.get_s_parameter_segment_table()
    assert not backend.writes


@pytest.mark.parametrize(
    ("command", "reply", "message"),
    [
        ("*IDN?", "Keysight Technologies,E5071C,SER123,A.08.50", "profile-supported"),
        (":FORM:DATA?", "REAL", "ASCII"),
        (":STAT:OPER:COND?", "32", "stable held sweep"),
        ("*STB?", "16", "stable held sweep"),
        (":INIT1:CONT?", "1", "stable held sweep"),
    ],
)
def test_ena_segment_guards_run_before_reading_table(ena_segment_table, command, reply, message):
    vna, backend = ena_segment_table
    backend.values[command] = reply
    with pytest.raises(InstrumentConfigurationError, match=message):
        vna.get_s_parameter_segment_table()
    assert ":SENS1:SEGM:DATA?" not in backend.queries and not backend.writes


def test_ena_segment_alias_rejected_before_io(ena_segment_table):
    vna, backend = ena_segment_table
    config = vna.config.model_copy(deep=True)
    config.scpi.queries["segment_table"].template = ":CALC1:DATA:SDAT?"
    vna = VectorNetworkAnalyser(config, backend)
    with pytest.raises(InstrumentConfigurationError, match="Unverified.*table"):
        vna.get_s_parameter_segment_table()
    assert not backend.queries and not backend.writes


def test_ena_segment_timeout_quarantines_without_recovery_writes(ena_segment_table):
    vna, backend = ena_segment_table
    backend.values[":SENS1:SEGM:DATA?"] = TimeoutError("lost segment reply")
    with pytest.raises(InstrumentCommunicationError, match="lost segment reply"):
        vna.get_s_parameter_segment_table()
    count = len(backend.queries)
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        vna.get_s_parameter_data()
    assert len(backend.queries) == count and not backend.writes


@pytest.fixture
def ena_inventory(ena):
    _, backend = ena
    backend.values.update(
        {
            "*OPT?": "4K5,008,010,019",
            ":SERV:PORT:COUN?": "4",
            ":SERV:CHAN:COUN?": "96",
            ":SERV:CHAN:TRAC:COUN?": "9",
            ":SERV:SWE:POIN?": "201",
            ":SERV:CHAN:ACT?": "32",
        }
    )
    return ena


def test_ena_inventory_separates_observed_service_limits_and_vendor_option_range(ena_inventory):
    vna, backend = ena_inventory
    report = vna.get_vna_inventory()
    assert (report.model, report.serial_number, report.software_revision) == (
        "E5071C",
        "SER123",
        "A.11.20",
    )
    assert (
        report.port_count,
        report.max_channels,
        report.max_traces_per_channel,
        report.max_sweep_points,
    ) == (4, 96, 9, 201)
    assert (report.active_channel, report.profile_channel, report.profile_channel_trace_count) == (
        32,
        1,
        2,
    )
    assert (report.profile_max_traces, report.profile_max_points) == (16, 20_001)
    assert report.options_reply == "4K5,008,010,019" and report.test_set_option == "4K5"
    assert report.bias_tees_installed is True
    limits = report.frequency_limits
    assert limits is not None
    assert (limits.minimum_hz, limits.maximum_hz, limits.source) == (
        300_000,
        20e9,
        "vendor_option_table",
    )
    assert backend.queries.count(":SERV:SWE:POIN?") == 2
    assert all(
        not any(word in query for word in ("SDAT", "XAX", "FREQ:", "SWE:TYPE"))
        for query in backend.queries
    )
    assert not backend.writes


@pytest.mark.parametrize(
    ("reply", "ports", "expected"),
    [
        ("280 / 008 010", "2", (9_000, 8.5e9, False)),
        ("435, 010", "4", (100_000, 3e9, True)),
        ("0", "4", None),
        ("008,010,1180", "4", None),
    ],
)
def test_ena_inventory_never_guesses_unreported_option_limits(
    ena_inventory, reply, ports, expected
):
    vna, backend = ena_inventory
    backend.values.update({"*OPT?": reply, ":SERV:PORT:COUN?": ports})
    report = vna.get_vna_inventory()
    assert report.options_reply == reply
    limits = report.frequency_limits
    if expected is None:
        assert (
            limits is None and report.test_set_option is None and report.bias_tees_installed is None
        )
    else:
        assert limits is not None
        assert (limits.minimum_hz, limits.maximum_hz, report.bias_tees_installed) == expected


@pytest.mark.parametrize(
    ("query", "reply", "error", "message"),
    [
        ("*OPT?", "4K5,480", InstrumentDataError, "conflicting test-set"),
        ("*OPT?", "280", InstrumentDataError, "disagrees"),
        ("*OPT?", "4K5;*CLS", InstrumentDataError, "installed-options"),
        (":SERV:CHAN:ACT?", "97", InstrumentConfigurationError, "active channel"),
        (":SERV:SWE:POIN?", "20002", InstrumentConfigurationError, "max points"),
        (":CALC1:PAR:COUN?", "10", InstrumentConfigurationError, "trace count"),
        (":SERV:CHAN:ACT?", ["32", "13"], InstrumentDataError, "inventory changed"),
    ],
)
def test_ena_inventory_rejects_incoherent_or_changing_report_without_writes(
    ena_inventory, query, reply, error, message
):
    vna, backend = ena_inventory
    backend.values[query] = reply
    with pytest.raises(error, match=message):
        vna.get_vna_inventory()
    assert not backend.writes


def test_ena_inventory_only_compiles_the_exact_service_queries(ena_inventory):
    vna, backend = ena_inventory
    config = vna.config.model_copy(deep=True)
    config.scpi.queries["inventory_points"].template = ":SENS1:SWE:POIN?"
    clone = VectorNetworkAnalyser(config, backend)
    with pytest.raises(InstrumentConfigurationError, match="Unverified.*max_points"):
        clone.get_vna_inventory()
    assert not backend.queries and not backend.writes


def test_ena_inventory_ambiguous_service_exchange_quarantines(ena_inventory):
    vna, backend = ena_inventory
    backend.values[":SERV:SWE:POIN?"] = TimeoutError("missing points limit")
    with pytest.raises(InstrumentCommunicationError, match="missing points limit"):
        vna.get_vna_inventory()
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        vna.get_s_parameter_segment_table()
    assert backend.queries[-1] == ":SERV:SWE:POIN?" and not backend.writes


def test_attached_ri_uncertainty_retains_full_covariance_across_storage(ena, tmp_path):
    vna, backend = ena
    fresh = vna.acquire_s_parameter_sweep(include_context=True)
    nominal = np.array([2, 0, 1, 0, 0.5, -0.3, 0.5, -0.3, 1, -1, 1, -1], dtype=float)
    reg = AtomRegistry()
    a = reg.mint(nominal=0, std_uncertainty=0.01, label="test influence A")
    b = reg.mint(nominal=0, std_uncertainty=0.02, label="test influence B")
    other = reg.mint(nominal=0, std_uncertainty=0.1, label="unrelated record")
    reg.set_correlation(a.uid, b.uid, -0.25)
    reg.set_correlation(b.uid, other.uid, 0.1)
    budget = QuantityArray(
        nominal.copy(),
        unit="1",
        diagonal_variance=[0.0001] * len(nominal),
        atom_sensitivities={a.uid: np.arange(1, 13), b.uid: np.arange(12, 0, -1)},
        registry=reg,
    )
    expected_covariance = budget.covariance_matrix()
    assert expected_covariance[0, 1] != 0  # RI
    assert expected_covariance[0, 2] != 0  # Cross-trace
    assert expected_covariance[0, 4] != 0  # Cross-frequency
    queries = backend.queries.copy()
    measured = fresh.with_uncertainty(
        budget,
        frequencies_hz=[1e6, 2e6, 3e6],
        trace_order=["S11", "S21"],
        source="Example lab budget B55",
        setup="Example cable, adapter and calibration record C12, DUT reference planes",
    )
    budget.nominal[0] = -20
    reg.set_correlation(a.uid, b.uid, 0.8)
    assert fresh.uncertainty is None
    assert measured.uncertainty is not None
    np.testing.assert_array_equal(measured.uncertainty.nominal, nominal)
    np.testing.assert_allclose(measured.uncertainty.covariance_matrix(), expected_covariance)
    converted = measured.to_measurement_result()
    assert converted.values.equals(fresh.to_measurement_result().values)
    assert converted.envelope["uncertainty_status"] == "externally_evaluated"
    assert converted.envelope["vna"]["uncertainty_evidence"] == {
        "source": "Example lab budget B55",
        "setup": "Example cable, adapter and calibration record C12, DUT reference planes",
        "component_order": "frequency_major_trace_ri",
    }

    with MeasurementSession("VNA budget", compliance=False) as session:
        session.parameter("trial", [1])

        @session.acquire
        def sweep():
            return measured

        trial = session.run(show_progress=False)
    parquet = tmp_path / "experiment.parquet"
    trial.save_parquet(str(parquet))
    parquet_envelope = json.loads(pl.read_parquet(parquet)["sweep__measurement"][0])["result"][
        "envelope"
    ]
    with MeasurementDatabase(tmp_path / "vna") as db:
        key = db.store_measurement(None, measured)
        restored = db.retrieve_measurement(key)
    assert restored.values.equals(converted.values)
    for envelope in (parquet_envelope, restored.envelope):
        assert envelope == converted.envelope
        serialized = envelope["uncertainty"]
        assert serialized["kind"] == "quantity_array"
        assert other.uid not in str(serialized)
        reopened = QuantityArray.from_dict(serialized["payload"])
        np.testing.assert_allclose(reopened.covariance_matrix(), expected_covariance)
    assert backend.queries == queries
    assert backend.writes == [":INIT1", ":TRIG:SING"]

    measured.s_params[0][0] += 1
    with pytest.raises(ValueError, match="modified VNA payload"):
        _ = measured.uncertainty
    assert fresh.s_params[0][0] == 2 + 0j


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("no context", "captured with context"),
        ("wrong grid", "frequency grid"),
        ("wrong trace order", "trace order"),
        ("wrong nominal values", "match the dimensionless captured RI"),
        ("wrong unit", "match the dimensionless captured RI"),
        ("unsourced", "source of the evaluated budget"),
        ("unknown setup", "applicable calibration and setup"),
        ("nominal only", "positive uncertainty"),
        ("nonfinite", "finite nonnegative diagonal variances"),
        ("non-PSD", "positive semi-definite"),
    ],
)
def test_vna_uncertainty_rejects_unmatched_or_incomplete_evidence(ena, case, message):
    vna, _ = ena
    fresh = vna.acquire_s_parameter_sweep(include_context=case != "no context")
    nominal = np.array([2, 0, 1, 0, 0.5, -0.3, 0.5, -0.3, 1, -1, 1, -1], dtype=float)
    diagonal = np.full(nominal.shape, 0.0001)
    reg = AtomRegistry()
    sensitivities = {}
    if case == "wrong nominal values":
        nominal[6] = 9
    if case == "nominal only":
        diagonal[0] = 0
    if case == "nonfinite":
        diagonal[5] = float("nan")
    if case == "non-PSD":
        atoms = [reg.mint(nominal=0, std_uncertainty=0.01, label=str(i)) for i in range(3)]
        reg.set_correlation(atoms[0].uid, atoms[1].uid, 0.9)
        reg.set_correlation(atoms[0].uid, atoms[2].uid, 0.9)
        reg.set_correlation(atoms[1].uid, atoms[2].uid, -0.9)
        sensitivities = {atom.uid: np.ones_like(nominal) for atom in atoms}
    budget = QuantityArray(
        nominal,
        unit="dB" if case == "wrong unit" else "1",
        diagonal_variance=diagonal,
        atom_sensitivities=sensitivities,
        registry=reg,
    )
    with pytest.raises(ValueError, match=message):
        fresh.with_uncertainty(
            budget,
            frequencies_hz=[1e6, 2.5e6, 3e6] if case == "wrong grid" else [1e6, 2e6, 3e6],
            trace_order=["S21", "S11"] if case == "wrong trace order" else ["S11", "S21"],
            source=" " if case == "unsourced" else "Source report",
            setup="" if case == "unknown setup" else "Setup record",
        )
    assert fresh.uncertainty is None
    assert fresh.to_measurement_result().envelope["uncertainty_status"] == "not_evaluated"
