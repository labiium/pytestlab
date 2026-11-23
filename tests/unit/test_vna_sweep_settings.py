"""Offline guardrails for E5071C sweep setup over scripted SCPI."""

import csv
import re

import pytest

from pytestlab import Bench
from pytestlab.config.loader import load_device_profile
from pytestlab.devices import register_backend
from pytestlab.devices import registry
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.instruments.VectorNetworkAnalyser import VectorNetworkAnalyser
from pytestlab.instruments.VectorNetworkAnalyser import VNASweepSettings


class ENA:
    is_simulated = False

    def __init__(self):
        self.responses = {
            "*IDN?": "Agilent Technologies,E5071C,SN123,A.09.60",
            "*STB?": "0",
            ":OUTP?": "0",
            ":STAT:OPER:COND?": "0",
            ":INIT1:CONT?": "0",
            ":SENS1:SWE:TYPE?": "LIN",
            ":SENS1:FREQ:STAR?": "1e6",
            ":SENS1:FREQ:STOP?": "5e6",
            ":SENS1:BWID?": "1000",
            ":SENS1:OFFS:STAT?": "0",
            ":CALC1:FSIM:STAT?": "0",
            ":SENS1:SWE:POIN?": "201",
            ":SENS1:CORR:STAT?": "1",
            ":SOUR1:POW:PORT:COUP?": "1",
            ":SOUR1:POW?": "-20",
            ":CALC1:PAR:COUN?": "2",
            ":CALC1:PAR1:DEF?": "S21",
            ":CALC1:PAR2:DEF?": "S11",
        }
        self.queries = []
        self.writes = []
        self.connections = 0
        self.ignore = None

    def connect(self):
        self.connections += 1

    def disconnect(self):
        pass

    def query(self, command, delay=None):
        self.queries.append(command)
        value = self.responses[command]
        if isinstance(value, BaseException):
            raise value
        return value.pop(0) if isinstance(value, list) else value

    def write(self, command):
        self.writes.append(command)
        target, value = command.split()
        assert re.fullmatch(
            r":(?:SENS1:(?:FREQ:(?:STAR|STOP)|BWID|SWE:(?:POIN|TYPE))|SOUR1:POW|CALC1:PAR(?:[1-4]:DEF|:COUN))",
            target,
        ), f"Unexpected mutation or RF activation: {command}"
        if target != self.ignore:
            self.responses[target + "?"] = value


@pytest.fixture
def ena():
    config = load_device_profile("keysight/E5071C_VNA")
    backend = ENA()
    return VectorNetworkAnalyser(config, backend), backend


def test_readback_reports_live_parameters_and_slots(ena):
    vna, backend = ena
    assert vna.supports_operation("sparameter_sweep_settings")
    assert not backend.queries and not backend.writes
    state = vna.get_s_parameter_sweep_settings()
    assert state == VNASweepSettings(
        channel=1,
        sweep_type="linear",
        start_freq=1e6,
        stop_freq=5e6,
        num_points=201,
        if_bandwidth=1000,
        power_level=-20,
        s_params=("S21", "S11"),
        rf_output_enabled=False,
        continuous=False,
        active_trace_correction_enabled=True,
        frequency_offset_enabled=False,
        fixture_simulator_enabled=False,
    )
    assert not backend.writes and "SYST:ERR?" not in backend.queries
    assert backend.queries.count(":CALC1:PAR1:DEF?") == 2


def test_read_log_uncoupled_without_claiming_power(ena):
    vna, backend = ena
    backend.responses.update(
        {
            ":SENS1:SWE:TYPE?": "LOG",
            ":INIT1:CONT?": "1",
            ":OUTP?": "1",
            ":SOUR1:POW:PORT:COUP?": "0",
        }
    )
    observed = vna.get_s_parameter_sweep_settings()
    assert observed.sweep_type == "log"
    assert observed.rf_output_enabled and observed.continuous
    assert observed.power_level is None
    assert ":SOUR1:POW?" not in backend.queries
    assert not backend.writes


def test_configure_moves_stop_before_start_and_verifies_trace_replacement(ena):
    vna, backend = ena
    state = vna.configure_s_parameter_sweep(
        s_params=["S11"],
        start_freq=10e6,
        stop_freq=20e6,
        num_points=401,
        if_bandwidth=3000,
        power_level=-15,
    )
    assert state == vna.get_s_parameter_sweep_settings()
    assert state.s_params == ("S11",)
    assert vna.config.s_parameters == ["S11"]
    assert vna.config.start_frequency == state.start_freq
    assert vna.config.stop_frequency == state.stop_freq
    assert vna.config.num_points == state.num_points
    assert vna.config.if_bandwidth == state.if_bandwidth
    assert vna.config.power_level == state.power_level
    assert state.start_freq == 10e6 and state.stop_freq == 20e6
    assert state.num_points == 401 and state.if_bandwidth == 3000 and state.power_level == -15
    assert [command.split()[0] for command in backend.writes] == [
        ":SENS1:FREQ:STOP",
        ":SENS1:FREQ:STAR",
        ":SENS1:SWE:POIN",
        ":SENS1:BWID",
        ":SOUR1:POW",
        ":CALC1:PAR:COUN",
        ":CALC1:PAR1:DEF",
    ]


def test_configure_moves_start_before_stop_when_moving_down(ena):
    vna, backend = ena
    state = vna.configure_s_parameter_sweep(start_freq=1e5, stop_freq=5e5)
    assert state.start_freq == 1e5 and state.stop_freq == 5e5
    assert [write.split()[0] for write in backend.writes] == [
        ":SENS1:FREQ:STAR",
        ":SENS1:FREQ:STOP",
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"num_points": True},
        {"num_points": 201.5},
        {"start_freq": float("nan")},
        {"if_bandwidth": float("inf")},
        {"s_params": []},
        {"s_params": ["S21", "s21"]},
    ],
)
def test_invalid_setup_has_no_io(ena, kwargs):
    vna, backend = ena
    with pytest.raises(InstrumentConfigurationError):
        vna.configure_s_parameter_sweep(**kwargs)
    assert not backend.writes and not backend.queries and backend.connections == 0


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        (":OUTP?", "1", "RF output OFF"),
        (":OUTP?", "UNKNOWN", "Invalid rf_output"),
        (":INIT1:CONT?", "1", "idle Hold"),
        (":STAT:OPER:COND?", "32", "idle Hold"),
        (":SENS1:OFFS:STAT?", "1", "offset"),
        (":CALC1:FSIM:STAT?", "1", "fixture"),
        (":SENS1:SWE:TYPE?", "POW", "LIN and LOG"),
        (":SOUR1:POW:PORT:COUP?", "0", "coupled"),
        ("*STB?", "4", "error queue"),
        ("*IDN?", "Keysight,E5071C,SN123,A.09.59", "firmware"),
        ("*IDN?", "Rohde&Schwarz,ZNB8,SN123,4.25", "did not identify"),
    ],
)
def test_setup_rejects_an_ineligible_instrument_state_before_writes(ena, key, value, error):
    vna, backend = ena
    backend.responses[key] = value
    with pytest.raises((InstrumentConfigurationError, InstrumentDataError), match=error):
        vna.configure_s_parameter_sweep(power_level=-25)
    assert not backend.writes


def test_rejects_settings_stale_on_second_read(ena):
    vna, backend = ena
    backend.responses[":SENS1:BWID?"] = ["1000", "3000"]
    with pytest.raises(InstrumentDataError, match="changed during readback"):
        vna.get_s_parameter_sweep_settings()
    assert not backend.writes


def test_refuses_out_of_order_bound_before_any_write(ena):
    vna, backend = ena
    with pytest.raises(InstrumentConfigurationError, match="below stop"):
        vna.configure_s_parameter_sweep(start_freq=6e6, s_params=["S12"])
    assert not backend.writes


def test_rejects_instrument_coercion_instead_of_returning_requested_settings(ena):
    vna, backend = ena
    backend.ignore = ":SENS1:BWID"
    previous = vna.config.if_bandwidth
    with pytest.raises(InstrumentDataError, match="readback mismatch.*if_bandwidth"):
        vna.configure_s_parameter_sweep(if_bandwidth=2000)
    assert len(backend.writes) == 1
    assert vna.config.if_bandwidth == previous


def test_stops_on_instrument_error_without_consuming_the_queue(ena):
    vna, backend = ena
    backend.responses["*STB?"] = ["0", "0", "4"]
    with pytest.raises(InstrumentConfigurationError, match="partially applied"):
        vna.configure_s_parameter_sweep(num_points=401, if_bandwidth=100)
    assert backend.writes == [":SENS1:SWE:POIN 401"]
    assert "SYST:ERR?" not in backend.queries


def test_timeout_while_verifying_does_not_retry_writes_or_return_settings(ena):
    vna, backend = ena
    backend.responses["*STB?"] = ["0", "0"]
    original_query = backend.query

    def fail_after_write(command, delay=None):
        if backend.writes:
            raise TimeoutError("scripted VISA timeout")
        return original_query(command, delay)

    backend.query = fail_after_write
    with pytest.raises(InstrumentCommunicationError, match="scripted VISA timeout"):
        vna.configure_s_parameter_sweep(num_points=401, if_bandwidth=100)
    assert backend.writes == [":SENS1:SWE:POIN 401"]


def test_switches_linear_to_log_and_back_without_rearming(ena):
    vna, backend = ena
    state = vna.configure_s_parameter_sweep(sweep_type="log", num_points=51)
    assert (state.sweep_type, state.num_points) == ("log", 51)
    assert not state.rf_output_enabled and not state.continuous
    assert backend.writes == [":SENS1:SWE:TYPE LOG", ":SENS1:SWE:POIN 51"]

    assert vna.configure_s_parameter_sweep(sweep_type="log").sweep_type == "log"
    assert len(backend.writes) == 2
    assert vna.configure_s_parameter_sweep(sweep_type="linear").sweep_type == "linear"
    assert backend.writes[-1] == ":SENS1:SWE:TYPE LIN"


def test_mode_rejection_leaves_later_commands_unsent(ena):
    vna, backend = ena
    backend.ignore = ":SENS1:SWE:TYPE"
    with pytest.raises(InstrumentDataError, match="sweep type was not applied"):
        vna.configure_s_parameter_sweep(sweep_type="log", num_points=51)
    assert backend.writes == [":SENS1:SWE:TYPE LOG"]
    assert vna.config.num_points != 51


@pytest.mark.parametrize(
    ("query", "reply", "message"),
    [
        (":OUTP?", ["0", "1"], "RF output OFF"),
        (":SOUR1:POW:PORT:COUP?", ["1", "0"], "range or power state changed"),
        (":SENS1:FREQ:STOP?", ["5e6", "4e6"], "range or power state changed"),
    ],
)
def test_mode_change_rechecks_safety_before_remaining_writes(ena, query, reply, message):
    vna, backend = ena
    backend.responses[query] = reply
    with pytest.raises((InstrumentConfigurationError, InstrumentDataError), match=message):
        vna.configure_s_parameter_sweep(sweep_type="log", num_points=51)
    assert backend.writes == [":SENS1:SWE:TYPE LOG"]


def test_mode_never_sends_a_poisoned_profile_setter_or_rf_status_query(ena):
    vna, backend = ena
    for collection, key, template in (
        ("commands", "set_sweep_type", ":SOUR1:POW {mode}"),
        ("queries", "sweep_rf_output", ":SYST:BEEP:WARN:STAT?"),
    ):
        config = vna.config.model_copy(deep=True)
        getattr(config.scpi, collection)[key].template = template
        modified = VectorNetworkAnalyser(config, backend)
        with pytest.raises(InstrumentConfigurationError, match="Invalid VNA"):
            modified.configure_s_parameter_sweep(sweep_type="log")
    assert not backend.queries and not backend.writes and backend.connections == 0


def test_bench_alias_configures_log_sweep_then_exports_operator_held_csv(tmp_path, monkeypatch):
    backend = ENA()
    registry.ensure_builtin_registrations()
    monkeypatch.setattr(registry, "_backends", registry._backends.copy())
    register_backend("offline_ena_transcript", lambda _: backend)
    descriptor = tmp_path / "bench.yaml"
    descriptor.write_text(
        "bench_name: Offline E5071C workflow\n"
        "instruments:\n"
        "  vna:\n"
        "    profile: keysight/E5071C_VNA\n"
        "    address: 'TCPIP0::192.0.2.10::inst0::INSTR'\n"
        "    backend: {type: offline_ena_transcript}\n",
        encoding="utf-8",
    )

    with Bench.open(descriptor, aliases={"vna"}, start_experiment=False) as bench:
        assert not backend.writes
        initial = bench.vna.get_s_parameter_sweep_settings()
        assert initial.sweep_type == "linear"
        assert not initial.rf_output_enabled and not initial.continuous
        applied = bench.vna.configure_s_parameter_sweep(
            sweep_type="log", s_params=["S11", "S21"], stop_freq=4e6, num_points=3
        )
        assert bench.vna.get_s_parameter_sweep_settings() == applied
        assert (applied.sweep_type, applied.stop_freq, applied.num_points) == ("log", 4e6, 3)
        assert applied.s_params == ("S11", "S21")

        # These are already-held replies supplied by the fake, representing a
        # separate operator acquisition. Python never enables RF or triggers it.
        backend.responses.update(
            {
                ":FORM:DATA?": "ASC",
                ":SENS1:FREQ:SPAN?": "3e6",
                ":CALC1:TRAC1:EQU:STAT?": "0",
                ":CALC1:TRAC2:EQU:STAT?": "0",
                ":CALC1:TRAC1:TRAN:TIME:STAT?": "0",
                ":CALC1:TRAC2:TRAN:TIME:STAT?": "0",
                ":CALC1:TRAC1:DATA:XAX?": "1e6,2e6,4e6",
                ":CALC1:TRAC2:DATA:XAX?": "1e6,2e6,4e6",
                ":CALC1:TRAC1:DATA:SDAT?": "0.1,0.2,0.3,0.4,0.5,0.6",
                ":CALC1:TRAC2:DATA:SDAT?": "0.6,-0.5,0.4,-0.3,0.2,-0.1",
            }
        )
        held = bench.vna.get_s_parameter_data()
        assert held.trace("S21").at_frequency(2e6).value == 0.4 - 0.3j
        destination = tmp_path / "held.csv"
        held.to_csv(destination)

    assert backend.writes == [
        ":SENS1:SWE:TYPE LOG",
        ":SENS1:FREQ:STOP 4000000.0",
        ":SENS1:SWE:POIN 3",
        ":CALC1:PAR1:DEF S11",
        ":CALC1:PAR2:DEF S21",
    ]
    with destination.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [float(row["frequency_hz"]) for row in rows] == [1e6, 2e6, 4e6]
    assert rows[1] == {
        "frequency_hz": "2000000.0",
        "axis_source": "instrument",
        "trace_identity_verified": "true",
        "fresh": "false",
        "S11_real": "0.3",
        "S11_imag": "0.4",
        "S21_real": "0.4",
        "S21_imag": "-0.3",
    }
