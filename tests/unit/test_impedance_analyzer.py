from __future__ import annotations

import csv
import importlib
import re
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from typer.testing import CliRunner

from pytestlab import AutoInstrument
from pytestlab import Bench
from pytestlab import cli_typer
from pytestlab.config.loader import load_device_profile
from pytestlab.devices import AutoDevice
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments import ImpedanceAnalyzer
from pytestlab.instruments.backends.replay_backend import ReplayBackend
from pytestlab.instruments.ImpedanceAnalyzer import CompensationResult
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceCalibrationLayer
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceParameter
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceSourceMode
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceStandardKind

KEYSIGHT = {
    ":FORM:DATA?": "ASC",
    ":SENS1:SWE:TYPE?": "LOG",
    ":INIT1:CONT?": "0",
    ":SENS1:FREQ:DATA?": "1000,15600,49000",
    ":CALC1:DATA:RDAT?": "1,-1,30,-40,2,3",
    ":SYST:ERR?": '0,"No error"',
}
HIOKI = {
    ":MODE?": ":MODE ANALYZER",
    ":SWE:MAIN:SOUR?": ":SWEEP:MAIN:SOURCE FREQ",
    ":SWE:TRIG?": ":SWEEP:TRIGGER SEQUENTIAL",
    ":FORM:DATA?": ":FORMAT:DATA ASCII",
    ":MEAS:VAL?": ":MEASURE:VALID 22",
    ":HEAD?": ":HEADER ON",
    ":MEAS:OUTP:AUTO?": ":MEASURE:OUTPUT:AUTO OFF",
    ":MEAS:POIN? 2": "0,15.600E+03,Z 50.000,PHASE -53.1301023542",
}


def _instrument(profile, replies):
    backend = Mock()
    backend.query.side_effect = lambda command, **_: replies[command]
    analyzer = AutoInstrument.from_config(
        profile, backend_override=backend, address_override="TCPIP0::unused.invalid::inst0::INSTR"
    )
    assert isinstance(analyzer, ImpedanceAnalyzer)
    backend.reset_mock()
    return analyzer, backend


@pytest.mark.parametrize(
    "profile,replies,commands,expected_status",
    [
        ("keysight/E4990A", KEYSIGHT, list(KEYSIGHT)[:-1], None),
        ("hioki/IM3570", HIOKI, list(HIOKI), 0),
    ],
)
def test_same_operation_reads_native_complex_or_polar_buffer(
    profile, replies, commands, expected_status, tmp_path, monkeypatch
):
    backend = Mock()
    backend.query.side_effect = lambda command, **_: replies[command]
    allocate = Mock(return_value=backend)
    monkeypatch.setattr(AutoDevice, "_build_backend", allocate)
    descriptor = tmp_path / "bench.yaml"
    descriptor.write_text(
        f"bench_name: Offline impedance readback\n"
        f"instruments:\n  impedance:\n    profile: {profile}\n"
        "    address: 'TCPIP0::unused.invalid::inst0::INSTR'\n"
    )
    validated = CliRunner().invoke(
        cli_typer.app, ["bench", "validate", str(descriptor), "--strict"]
    )
    assert validated.exit_code == 0, validated.output
    allocate.assert_not_called()

    with Bench.open(descriptor, aliases={"impedance"}, start_experiment=False) as bench:
        analyzer = bench.impedance
        assert analyzer.supports_operation("read_impedance")
        assert analyzer.validate_operation_contract(strict=True, check_parameters=True)[
            "read_impedance"
        ]["supported"]
        allocate.assert_not_called()
        result = analyzer.read_impedance(point=2)

    assert result.frequency_hz == 15_600
    assert result.impedance_ohm == pytest.approx(30 - 40j)
    assert result.magnitude_ohm == pytest.approx(50)
    assert result.phase_deg == pytest.approx(-53.1301023542)
    assert (result.channel, result.point, result.status) == (1, 2, expected_status)
    trace = [call.args[0] for call in backend.query.call_args_list if call.args[0] != ":SYST:ERR?"]
    assert trace == commands
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "profile,replies,command,bad_value,match",
    [
        ("keysight/E4990A", KEYSIGHT, ":CALC1:DATA:RDAT?", "1,2,3,4", "sample count"),
        ("keysight/E4990A", KEYSIGHT, ":CALC1:DATA:RDAT?", "1,2,3,nan,5,6", "numeric"),
        ("keysight/E4990A", KEYSIGHT, ":CALC1:DATA:RDAT?", "1,2,3,9.9E37,5,6", "profile limit"),
        ("keysight/E4990A", KEYSIGHT, ":SENS1:FREQ:DATA?", "1000,,49000", "numeric"),
        ("hioki/IM3570", HIOKI, ":MEAS:POIN? 2", "4,15600,Z 9.999E36,PHASE 0", "not normal"),
        ("hioki/IM3570", HIOKI, ":MEAS:POIN? 2", "0,15600,CS 50,PHASE 0", "labelled"),
    ],
)
def test_invalid_result_never_looks_measured(profile, replies, command, bad_value, match):
    analyzer, backend = _instrument(profile, replies | {command: bad_value})
    with pytest.raises(InstrumentDataError, match=match):
        analyzer.read_impedance(2)
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "profile,replies,command,wrong_state,match",
    [
        ("keysight/E4990A", KEYSIGHT, ":SENS1:SWE:TYPE?", "BIAS", "sweep_domain"),
        ("keysight/E4990A", KEYSIGHT, ":INIT1:CONT?", "1", "continuous_sweep"),
        ("hioki/IM3570", HIOKI, ":MEAS:VAL?", ":MEASURE:VALID 14", "response_fields"),
        ("hioki/IM3570", HIOKI, ":SWE:MAIN:SOUR?", ":SWEEP:MAIN:SOURCE CC", "sweep_domain"),
    ],
)
def test_prepared_state_required_before_reading(profile, replies, command, wrong_state, match):
    analyzer, backend = _instrument(profile, replies | {command: wrong_state})
    with pytest.raises(InstrumentConfigurationError, match=match):
        analyzer.read_impedance(2)
    backend.write.assert_not_called()
    assert all(
        not any(marker in call.args[0] for marker in ("RDAT", "MEAS:POIN"))
        for call in backend.query.call_args_list
    )


def test_rejects_ambiguous_indices_and_compound_profile_queries_before_io():
    config = load_device_profile("hioki/IM3570")
    config.scpi.queries["impedance_point"].template = "*TRG;:MEAS:POIN? {point}"
    analyzer, backend = _instrument(config, {})

    with pytest.raises(InstrumentParameterError, match="integer"):
        analyzer.read_impedance(True)
    with pytest.raises(InstrumentParameterError, match="channel"):
        analyzer.read_impedance(channel=2)
    with pytest.raises(InstrumentConfigurationError, match="single, explicit"):
        analyzer.read_impedance(2)

    assert not backend.mock_calls


KEYSIGHT_SWEEP = KEYSIGHT | {
    ":SENS1:SWE:POIN?": "+3",
    ":SERV:CHAN1:ATR:ACT?": "+2",
    ":CALC1:PAR2:DEF?": "IMP",
    ":CALC1:FORM:TWOD?": "COMP",
    ":CALC1:MATH:FUNC?": "NORM",
    ":CALC1:DATA:FDAT?": "1,-1,30,-40,2,3",
    ":SENS1:FREQ:STAR?": "1000",
    ":SENS1:FREQ:STOP?": "49000",
    ":SERV:SWE:FREQ:MIN?": "20",
    ":SERV:SWE:FREQ:MAX?": "10000000",
    ":SERV:ACH:ACT?": "1",
    ":TRIG:SOUR?": "BUS",
    ":TRIG:SCOP?": "ACT",
    ":TRIG:POIN?": "0",
    ":SENS1:AVER?": "0",
    ":CALC1:AVER?": "0",
    ":SOUR:BIAS:STAT?": "0",
    ":SOUR1:MODE?": "VOLT",
    ":SOUR1:ALC?": "0",
    ":SOUR1:VOLT?": "0.05",
    "*OPC?": "+1",
}
HIOKI_SWEEP = HIOKI | {
    ":DCBIAS?": ":DCBIAS OFF",
    ":COMP:ANAL?": ":COMPARATOR:ANALYZER OFF",
    ":SEGM?": ":SEGMENT OFF",
    ":LIST:STAR:STOP?": ":LIST:START:STOP 1.0000E+03,4.9000E+04,3,LOG",
    ":MEAS:POIN? 1": "0,1.0000E+03,Z 1.414213562,PHASE -45",
    ":MEAS:POIN? 3": "0,4.9000E+04,Z 3.605551275,PHASE 56.309932474",
}


@pytest.mark.parametrize(
    "profile,replies,status",
    [
        ("keysight/E4990A", KEYSIGHT_SWEEP, None),
        ("hioki/IM3570", HIOKI_SWEEP, 0),
    ],
)
def test_complete_sweep_uses_instrument_axis_and_reads_only(profile, replies, status):
    analyzer, backend = _instrument(profile, replies)
    result = analyzer.read_impedance_sweep()
    assert result.frequency_hz == (1000, 15_600, 49_000)
    assert result.impedance_ohm == pytest.approx((1 - 1j, 30 - 40j, 2 + 3j))
    assert [point.status for point in result.readings] == [status] * 3
    assert not result.fresh
    assert analyzer.validate_operation_contract(strict=True, check_parameters=True)[
        "read_impedance_sweep"
    ]["supported"]
    backend.write.assert_not_called()


@pytest.mark.parametrize("model,exported_status", [("e4990a", ""), ("im3570", "0")])
def test_bench_impedance_alias_runs_held_export_recipe_on_strict_replay(
    model, exported_status, tmp_path, monkeypatch, capsys
):
    from examples.replay_mode.export_impedance import main

    examples = Path(__file__).resolve().parents[2] / "examples" / "replay_mode"
    session = examples / f"impedance_{model}.yaml"
    entry = yaml.safe_load(session.read_text())["impedance"]
    backend = ReplayBackend(entry["log"], profile_key="impedance")
    monkeypatch.setattr(AutoDevice, "_build_backend", Mock(return_value=backend))
    descriptor = {
        "bench_name": "Synthetic impedance export",
        "instruments": {
            "impedance": {
                "profile": entry["profile"],
                "address": "TCPIP0::unused.invalid::3570::SOCKET",
            }
        },
    }
    path = tmp_path / "sweep.csv"
    with Bench.open(descriptor, aliases={"impedance"}, start_experiment=False) as bench:
        assert isinstance(bench.impedance, ImpedanceAnalyzer)
        main(bench, path)
    assert backend._step == len(entry["log"])
    assert "minimum sampled |Z| = 1 ohm at 15600 Hz" in capsys.readouterr().out
    with path.open(newline="") as inp:
        rows = list(csv.DictReader(inp))
    assert [float(row["frequency_hz"]) for row in rows] == [1000, 15_600, 49_000]
    assert rows[1] == {
        "point": "2",
        "frequency_hz": "15600.0",
        "impedance_real_ohm": "1.0",
        "impedance_imag_ohm": "0.0",
        "channel": "1",
        "status": exported_status,
        "fresh": "false",
    }


def test_impedance_sweep_csv_does_not_replace_existing_file(tmp_path):
    analyzer, _ = _instrument("keysight/E4990A", KEYSIGHT_SWEEP)
    result = analyzer.read_impedance_sweep()
    path = tmp_path / "sweep.csv"
    path.write_text("keep this")
    with pytest.raises(FileExistsError):
        result.to_csv(path)
    assert path.read_text() == "keep this"
    result.to_csv(path, overwrite=True)
    assert path.read_text().startswith("point,frequency_hz,")


@pytest.mark.parametrize(
    "profile,replies,command,bad_value,match",
    [
        ("keysight/E4990A", KEYSIGHT_SWEEP, ":CALC1:PAR2:DEF?", "ADM", "parameter"),
        ("keysight/E4990A", KEYSIGHT_SWEEP, ":CALC1:DATA:FDAT?", "1,-1,1.#QNB,2,3,4", "numeric"),
        ("keysight/E4990A", KEYSIGHT_SWEEP, ":CALC1:DATA:FDAT?", "1,-1,30,-40", "sample count"),
        ("hioki/IM3570", HIOKI_SWEEP, ":MEAS:POIN? 3", "4,49000,Z 4,PHASE 0", "not normal"),
        ("hioki/IM3570", HIOKI_SWEEP, ":LIST:STAR:STOP?", "1000,49000,802,LOG", "integer"),
        ("hioki/IM3570", HIOKI_SWEEP, ":SEGM?", ":SEGMENT ON", "segment_mode"),
    ],
)
def test_complete_sweep_rejects_invalid_buffers(profile, replies, command, bad_value, match):
    analyzer, backend = _instrument(profile, replies | {command: bad_value})
    with pytest.raises((InstrumentConfigurationError, InstrumentDataError), match=match):
        analyzer.read_impedance_sweep()
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "profile,replies,expected",
    [
        (
            "keysight/E4990A",
            KEYSIGHT_SWEEP,
            [
                ":SENS1:SWE:TYPE LOG",
                ":SENS1:FREQ:STAR 1000",
                ":SENS1:FREQ:STOP 49000",
                ":SENS1:SWE:POIN 3",
            ],
        ),
        ("hioki/IM3570", HIOKI_SWEEP, [":LIST:STAR:STOP 1000,49000,3,LOG"]),
    ],
)
def test_configure_and_verify_without_extra_writes(profile, replies, expected):
    analyzer, backend = _instrument(profile, replies)
    settings = analyzer.configure_frequency_sweep(1000, 49000, 3)
    assert (settings.start_hz, settings.stop_hz, settings.points, settings.spacing) == (
        1000,
        49000,
        3,
        "log",
    )
    assert [call.args[0] for call in backend.write.call_args_list] == expected


@pytest.mark.parametrize("bias", ["ON", ":DCBIAS ON", "0", ":UNEXPECTED OFF"])
def test_hioki_refuses_when_internal_dc_bias_is_on_or_unverified(bias):
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SWEEP | {":DCBIAS?": bias})
    with pytest.raises(InstrumentConfigurationError, match="DC bias OFF"):
        analyzer.configure_frequency_sweep(1000, 49000, 3)
    backend.write.assert_not_called()


@pytest.mark.parametrize("mode", ["CV", ":LEVEL CC", ":LEVEL UNKNOWN", ":UNEXPECTED V"])
def test_hioki_refuses_unverified_open_circuit_voltage_mode_above_1_mhz(mode):
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SWEEP | {":LEVEL?": mode})
    with pytest.raises(InstrumentConfigurationError, match="above 1 MHz.*open-circuit voltage"):
        analyzer.configure_frequency_sweep(1000, 2_000_000, 3)
    backend.write.assert_not_called()


@pytest.mark.parametrize("bias,mode", [("OFF", "V"), (":DCBIAS OFF", ":LEVEL V")])
def test_hioki_verifies_bias_and_source_mode_before_high_band_write(bias, mode):
    analyzer, backend = _instrument(
        "hioki/IM3570",
        HIOKI_SWEEP
        | {
            ":DCBIAS?": bias,
            ":LEVEL?": mode,
            ":LIST:STAR:STOP?": ":LIST:START:STOP 1.0000E+03,2.0000E+06,3,LOG",
        },
    )
    settings = analyzer.configure_frequency_sweep(1000, 2_000_000, 3)
    assert settings.stop_hz == 2_000_000
    trace = [
        (call[0], call.args[0]) for call in backend.mock_calls if call[0] in {"query", "write"}
    ]
    assert trace[-5:] == [
        ("query", ":DCBIAS?"),
        ("query", ":LEVEL?"),
        ("query", ":COMP:ANAL?"),
        ("write", ":LIST:STAR:STOP 1000,2000000,3,LOG"),
        ("query", ":LIST:STAR:STOP?"),
    ]


def test_hioki_at_exactly_1_mhz_does_not_require_voltage_mode():
    analyzer, backend = _instrument(
        "hioki/IM3570",
        HIOKI_SWEEP | {":LIST:STAR:STOP?": "1000,1000000,3,LOG"},
    )
    assert analyzer.configure_frequency_sweep(1000, 1_000_000, 3).stop_hz == 1_000_000
    assert all(call.args != (":LEVEL?",) for call in backend.query.call_args_list)


@pytest.mark.parametrize("command,stop_hz", [(":DCBIAS?", 49000), (":LEVEL?", 2_000_000)])
def test_hioki_missing_guard_reply_fails_as_communication_error_without_writes(command, stop_hz):
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SWEEP | {":LEVEL?": "V", command: ""})
    with pytest.raises(InstrumentCommunicationError, match=re.escape(command)):
        analyzer.configure_frequency_sweep(1000, stop_hz, 3)
    backend.write.assert_not_called()


def test_hioki_guard_does_not_accept_unexpected_high_band_rounding():
    analyzer, _ = _instrument(
        "hioki/IM3570",
        HIOKI_SWEEP | {":LIST:STAR:STOP?": "1000,1000001,3,LOG"},
    )
    with pytest.raises(InstrumentConfigurationError, match="unexpectedly extends"):
        analyzer.configure_frequency_sweep(1000, 1_000_000, 3)


def test_configure_checks_installed_frequency_option_before_write():
    analyzer, backend = _instrument("keysight/E4990A", KEYSIGHT_SWEEP)
    with pytest.raises(InstrumentParameterError, match="10000000"):
        analyzer.configure_frequency_sweep(1000, 20_000_000, 3)
    backend.write.assert_not_called()


def test_configure_refuses_to_report_clamped_values_as_success():
    analyzer, _ = _instrument("hioki/IM3570", HIOKI_SWEEP)
    with pytest.raises(InstrumentConfigurationError, match="did not verify"):
        analyzer.configure_frequency_sweep(1000, 45000, 3)


def _fresh_keysight(replies, *, backend_type=Mock):
    backend = backend_type()
    analyzer = AutoInstrument.from_config(
        "keysight/E4990A",
        backend_override=backend,
        address_override="TCPIP0::unused.invalid::inst0::INSTR",
    )
    backend.reset_mock()
    state = dict(replies)

    def write(command):
        if command == ":INIT1:CONT ON":
            state[":INIT1:CONT?"] = "1"
        elif command == ":INIT1:CONT OFF":
            state[":INIT1:CONT?"] = "0"

    def query(command, **_):
        response = state[command]
        if isinstance(response, BaseException):
            raise response
        return response

    backend.query.side_effect = query
    backend.write.side_effect = write
    backend.get_timeout.return_value = 2500
    return analyzer, backend


def test_fresh_sweep_is_armed_once_then_held_and_restores_timeout():
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP)
    result = analyzer.acquire_impedance_sweep(timeout_ms=123)
    assert result.fresh
    assert result.to_dataframe()["fresh"].to_list() == [True] * 3
    assert result.impedance_ohm[1] == 30 - 40j
    assert [call.args[0] for call in backend.write.call_args_list] == [
        ":INIT1:CONT ON",
        ":TRIG:SING",
        ":INIT1:CONT OFF",
    ]
    timeouts = [call.args[0] for call in backend.set_timeout.call_args_list]
    assert len(timeouts) > 2
    assert all(0 < timeout <= 123 for timeout in timeouts[::2])
    assert set(timeouts[1::2]) == {2500}


@pytest.mark.parametrize("ceiling", [False, 0, -1, float("nan"), float("inf"), 1.01])
def test_optional_excitation_ceiling_rejects_invalid_limits_before_io(ceiling):
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP)
    with pytest.raises(InstrumentParameterError, match="positive voltage ceiling"):
        analyzer.acquire_impedance_sweep(max_excitation_v_rms=ceiling)
    assert not backend.mock_calls


@pytest.mark.parametrize("voltage", ["0", "0.004", "-0.01", "1.01"])
def test_omitted_ceiling_still_enforces_profile_maximum_before_arming(voltage):
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP | {":SOUR1:VOLT?": voltage})
    with pytest.raises(InstrumentConfigurationError, match="exceeds the permitted excitation"):
        analyzer.acquire_impedance_sweep()
    backend.write.assert_not_called()


def test_custom_profile_cannot_raise_the_native_excitation_maximum(monkeypatch):
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP | {":SOUR1:VOLT?": "1.01"})
    monkeypatch.setattr(analyzer.config.sweep, "max_excitation_v_rms", 2.0)
    with pytest.raises(InstrumentConfigurationError, match="exceeds the permitted excitation"):
        analyzer.acquire_impedance_sweep()
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "profile,replies", [("keysight/E4990A", KEYSIGHT_SWEEP), ("hioki/IM3570", HIOKI_SWEEP)]
)
def test_impedance_direct_setup_is_not_run_by_bulk_diagnostics(profile, replies):
    analyzer, backend = _instrument(profile, replies)
    operations = {
        "configure_frequency_sweep",
        "configure_frequency_segment",
        "configure_measurement_parameter",
        "configure_measurement_settings",
        "configure_voltage_excitation",
    }
    if profile == "keysight/E4990A":
        operations.add("acquire_impedance_sweep")
        ceiling = analyzer.describe_operation("acquire_impedance_sweep")["parameters"][
            "max_excitation_v_rms"
        ]
        assert not ceiling["required"]
    descriptions = {op: analyzer.describe_operation(op) for op in operations}
    forbidden = {"allow_excitation", "dut_disconnected", "idle_and_triggers_isolated"}
    for description in descriptions.values():
        assert description["python_only"]
        assert forbidden.isdisjoint(description["parameters"])
    assert not analyzer.describe_operation("read_impedance_sweep").get("python_only", False)

    semantic_rows, *_ = cli_typer._semantic_operation_rows(analyzer, include_writes=True)
    assert {row["alias"] for row in semantic_rows if row["status"] == "skip"} >= operations
    backend.write.assert_not_called()
    _, scpi_rows, *_ = cli_typer._profile_scpi_command_rows(
        profile, device=analyzer, include_writes=True, strict_response=True
    )
    guarded_aliases = {
        "set_parameter",
        "set_voltage",
        "set_speed",
        "set_averages",
        "set_sweep_limits" if profile == "hioki/IM3570" else "set_sweep_type",
        "set_segment_row" if profile == "hioki/IM3570" else "set_segment_table",
    }
    if profile == "keysight/E4990A":
        guarded_aliases |= {"arm_sweep", "trigger_sweep", "hold_sweep", "abort_sweep"}
    assert {
        row["alias"]
        for row in scpi_rows
        if row["status"] == "skip" and row["detail"] == "reserved for a direct Python operation"
    } >= guarded_aliases


@pytest.mark.parametrize(
    "command,reply,match",
    [
        (":TRIG:SOUR?", "INT", "trigger_source"),
        (":TRIG:SCOP?", "ALL", "trigger_scope"),
        (":SOUR:BIAS:STAT?", "1", "bias"),
        (":SOUR1:ALC?", "1", "source_alc"),
        (":SOUR1:MODE?", "CURR", "source_mode"),
        (":SOUR1:VOLT?", "0.2", "exceeds the permitted"),
    ],
)
def test_fresh_requires_safe_live_readback_before_arming(command, reply, match):
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP | {command: reply})
    with pytest.raises(InstrumentConfigurationError, match=match):
        analyzer.acquire_impedance_sweep(max_excitation_v_rms=0.1)
    backend.write.assert_not_called()


@pytest.mark.parametrize("failure", [TimeoutError("injected timeout"), KeyboardInterrupt()])
def test_pending_completion_without_clear_quarantines_every_impedance_operation(failure):
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP | {"*OPC?": failure})
    expected = (
        KeyboardInterrupt
        if isinstance(failure, KeyboardInterrupt)
        else InstrumentCommunicationError
    )
    with pytest.raises(expected) as caught:
        analyzer.acquire_impedance_sweep(max_excitation_v_rms=0.1)
    assert "native interface clear unavailable" in caught.value.__notes__[0]
    assert backend.write.call_args.args == (":TRIG:SING",)
    assert backend.query.call_args.args == ("*OPC?",)
    assert backend.set_timeout.call_args.args == (2500,)
    backend.reset_mock()
    for operation in (
        analyzer.read_impedance,
        analyzer.read_impedance_sweep,
        lambda: analyzer.configure_frequency_sweep(1000, 49000, 3),
        lambda: analyzer.acquire_impedance_sweep(max_excitation_v_rms=0.1),
    ):
        with pytest.raises(InstrumentCommunicationError, match="session quarantined"):
            operation()
    assert not backend.mock_calls


class _ClearableBackend(Mock):
    def device_clear(self):
        self.clear_native()


def test_pending_completion_clears_native_stream_before_abort_and_hold():
    analyzer, backend = _fresh_keysight(
        KEYSIGHT_SWEEP | {"*OPC?": TimeoutError("injected timeout")},
        backend_type=_ClearableBackend,
    )
    with pytest.raises(InstrumentCommunicationError, match="injected timeout") as caught:
        analyzer.acquire_impedance_sweep(max_excitation_v_rms=0.1)
    assert "verified analyzer hold" in caught.value.__notes__[0]
    trace = [
        (call[0], *call.args)
        for call in backend.mock_calls
        if call[0] in {"query", "write", "clear_native"}
    ]
    end = trace.index(("query", "*OPC?"))
    assert trace[end:] == [
        ("query", "*OPC?"),
        ("clear_native",),
        ("write", ":ABOR"),
        ("write", ":INIT1:CONT OFF"),
        ("query", ":INIT1:CONT?"),
        ("query", ":SYST:ERR?"),
    ]
    assert not analyzer.read_impedance_sweep().fresh


def test_failed_native_clear_never_sends_scpi_on_uncertain_stream():
    analyzer, backend = _fresh_keysight(
        KEYSIGHT_SWEEP | {"*OPC?": TimeoutError("injected timeout")},
        backend_type=_ClearableBackend,
    )
    backend.clear_native.side_effect = RuntimeError("clear failed")
    with pytest.raises(InstrumentCommunicationError, match="injected timeout") as caught:
        analyzer.acquire_impedance_sweep(max_excitation_v_rms=0.1)
    assert "clear failed" in caught.value.__notes__[0]
    assert backend.query.call_args.args == ("*OPC?",)
    assert backend.write.call_args.args == (":TRIG:SING",)
    with pytest.raises(InstrumentCommunicationError, match="quarantined"):
        analyzer.read_impedance_sweep()


def test_completion_past_wall_clock_deadline_is_rejected_even_when_it_returns_one(monkeypatch):
    from types import SimpleNamespace

    module = importlib.import_module("pytestlab.instruments.ImpedanceAnalyzer")
    now = 0.0
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now))
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP)
    original = backend.query.side_effect

    def elapsed_query(command, **kwargs):
        nonlocal now
        if command in (":FORM:DATA?", ":SOUR1:MODE?"):
            now += 0.035
        if command == "*OPC?":
            assert backend.set_timeout.call_args.args[0] <= 31
            now += 0.031
        return original(command, **kwargs)

    backend.query.side_effect = elapsed_query
    with pytest.raises(InstrumentCommunicationError, match="deadline expired") as caught:
        analyzer.acquire_impedance_sweep(max_excitation_v_rms=0.1, timeout_ms=100)
    assert "verified analyzer hold" in caught.value.__notes__[0]
    assert [call.args[0] for call in backend.write.call_args_list][-2:] == [
        ":ABOR",
        ":INIT1:CONT OFF",
    ]
    assert not any("FDAT" in call.args[0] for call in backend.query.call_args_list)


def test_fresh_refuses_unsupported_hioki_before_io():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SWEEP)
    assert not analyzer.supports_operation("acquire_impedance_sweep")
    with pytest.raises(InstrumentConfigurationError, match="does not support fresh"):
        analyzer.acquire_impedance_sweep()
    assert not backend.mock_calls


def test_readback_past_deadline_does_not_return_a_fresh_curve(monkeypatch):
    from types import SimpleNamespace

    module = importlib.import_module("pytestlab.instruments.ImpedanceAnalyzer")
    now = 0.0
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now))
    analyzer, backend = _fresh_keysight(KEYSIGHT_SWEEP)
    original = backend.query.side_effect

    def elapsed_query(command, **kwargs):
        nonlocal now
        if command == ":CALC1:DATA:FDAT?":
            now = 0.101
        return original(command, **kwargs)

    backend.query.side_effect = elapsed_query
    with pytest.raises(InstrumentCommunicationError, match="deadline expired"):
        analyzer.acquire_impedance_sweep(max_excitation_v_rms=0.1, timeout_ms=100)
    assert backend.write.call_args.args == (":INIT1:CONT OFF",)
    assert not analyzer.read_impedance_sweep().fresh


HIOKI_VOLTAGE = HIOKI_SWEEP | {
    ":LEVEL?": ":LEVEL V",
    ":LEVEL:VOLT?": ":LEVEL:VOLTAGE 25.0E-3",
}


@pytest.mark.parametrize(
    "profile,replies,parameter,values",
    [
        (
            "keysight/E4990A",
            KEYSIGHT_SWEEP
            | {":CALC1:PAR2:DEF?": "LS", ":CALC1:DATA:FDAT?": "3e-6,0,4e-6,0,5e-6,0"},
            ImpedanceParameter.SERIES_INDUCTANCE,
            (3e-6, 4e-6, 5e-6),
        ),
        (
            "hioki/IM3570",
            HIOKI_SWEEP
            | {
                ":MEAS:POIN? 1": "0,1000,CP 5e-8,D 0.01",
                ":MEAS:POIN? 2": "0,15600,CP 6e-8,D 0.02",
                ":MEAS:POIN? 3": "0,49000,CP 7e-8,D 0.03",
            },
            ImpedanceParameter.PARALLEL_CAPACITANCE,
            (5e-8, 6e-8, 7e-8),
        ),
    ],
)
def test_native_scalar_results_use_verified_parameter_and_native_axis(
    profile, replies, parameter, values, tmp_path
):
    analyzer, backend = _instrument(profile, replies)
    curve = analyzer.read_measurement_sweep(parameter)
    assert curve.parameter is parameter
    assert curve.unit == parameter.unit
    assert curve.frequency_hz == (1000, 15_600, 49_000)
    assert curve.values == values
    status = 0 if profile == "hioki/IM3570" else None
    assert curve.to_dataframe().row(1, named=True) == {
        "point": 2,
        "frequency_hz": 15_600.0,
        "value": values[1],
        "parameter": parameter.value,
        "unit": parameter.unit,
        "channel": 1,
        "status": status,
        "fresh": False,
    }
    path = tmp_path / "scalar.csv"
    curve.to_csv(path)
    with path.open(newline="") as inp:
        row = list(csv.DictReader(inp))[1]
    assert row["parameter"] == parameter.value
    assert row["unit"] == parameter.unit
    assert float(row["value"]) == values[1]
    assert row["status"] == ("0" if status == 0 else "")
    assert row["fresh"] == "false"
    backend.write.assert_not_called()


def test_scalar_result_refuses_wrong_active_trace_or_buffer_shape():
    replies = KEYSIGHT_SWEEP | {":CALC1:DATA:FDAT?": "3,0,4,0,5,1"}
    analyzer, backend = _instrument("keysight/E4990A", replies)
    with pytest.raises(InstrumentConfigurationError, match="parameter"):
        analyzer.read_measurement_sweep("quality_factor")
    assert ":CALC1:DATA:FDAT?" not in [call.args[0] for call in backend.query.call_args_list]
    replies[":CALC1:PAR2:DEF?"] = "Q"
    with pytest.raises(InstrumentDataError, match="zero secondary"):
        analyzer.read_measurement_sweep("quality_factor")
    backend.write.assert_not_called()


@pytest.mark.parametrize("phase_unit", ["DEG", "RAD"])
@pytest.mark.parametrize("parameter,code", [("phase", "TZ"), ("admittance_phase", "TY")])
def test_keysight_phase_reports_degrees_only_for_verified_units(phase_unit, parameter, code):
    analyzer, backend = _instrument(
        "keysight/E4990A",
        KEYSIGHT_SWEEP
        | {
            ":CALC1:PAR2:DEF?": code,
            ":CALC1:FORM:EPH?": "0",
            ":CALC1:UNIT:ANGL?": phase_unit,
            ":CALC1:DATA:FDAT?": "30,0,-45,0,90,0",
        },
    )
    if phase_unit == "DEG":
        result = analyzer.read_measurement_sweep(parameter)
        assert (result.values, result.unit) == ((30, -45, 90), "deg")
    else:
        with pytest.raises(InstrumentConfigurationError, match="phase_unit.*RAD"):
            analyzer.read_measurement_sweep(parameter)
        assert ":CALC1:DATA:FDAT?" not in [call.args[0] for call in backend.query.call_args_list]
    backend.write.assert_not_called()


def test_scalar_result_refuses_misaligned_hioki_labels():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SWEEP)
    with pytest.raises(InstrumentDataError, match="does not report LS"):
        analyzer.read_measurement_sweep("series_inductance")
    backend.write.assert_not_called()


def test_keysight_selects_trace_definition_but_does_not_activate_it():
    analyzer, backend = _instrument("keysight/E4990A", KEYSIGHT_SWEEP | {":CALC1:PAR:COUN?": "2"})
    actual = analyzer.configure_measurement_parameter("impedance", trace=2)
    assert actual == "impedance"
    backend.write.assert_called_once_with(":CALC1:PAR2:DEF IMP")
    backend.reset_mock()
    with pytest.raises(InstrumentParameterError, match="trace"):
        analyzer.configure_measurement_parameter("resistance", trace=3)
    backend.write.assert_not_called()


def test_keysight_measurement_speed_and_averaging_are_verified():
    analyzer, backend = _instrument(
        "keysight/E4990A",
        KEYSIGHT_SWEEP | {":SENS1:APER?": "4", ":SENS1:AVER?": "1", ":SENS1:AVER:COUN?": "16"},
    )
    settings = analyzer.configure_measurement_settings(
        speed_step=4,
        averages=16,
    )
    assert (settings.speed_step, settings.averages, settings.auto_range) == (4, 16, None)
    assert [call.args[0] for call in backend.write.call_args_list] == [
        ":SENS1:APER 4",
        ":SENS1:AVER:COUN 16",
        ":SENS1:AVER ON",
    ]


def test_hioki_probe_ranges_and_direct_tuning():
    replies = HIOKI_SWEEP | {
        ":SPEE?": ":SPEED MEDIUM",
        ":AVER?": ":AVERAGING OFF",
        ":RANG:AUTO?": ":RANGE:AUTO OFF",
        ":RANG?": ":RANGE 4",
    }
    analyzer, backend = _instrument("hioki/IM3570", replies)
    setup = analyzer.configure_measurement_settings(
        speed_step=2,
        averages=1,
        range_mode="fixed",
        fixed_range_ohm=300,
    )
    assert (setup.speed_step, setup.averages, setup.fixed_range_ohm) == (2, 1, 300)
    assert [call.args[0] for call in backend.write.call_args_list] == [
        ":SPEE MEDIUM",
        ":AVER OFF",
        ":RANG 4",
    ]
    backend.reset_mock()
    replies[":LIST:STAR:STOP?"] = "1000,2e6,3,LOG"
    with pytest.raises(InstrumentConfigurationError, match="stop frequency"):
        analyzer.configure_measurement_settings(
            range_mode="fixed",
            fixed_range_ohm=1e6,
        )
    backend.write.assert_not_called()


def test_reads_hioki_current_without_switching_source_or_bias():
    analyzer, backend = _instrument(
        "hioki/IM3570",
        HIOKI_SWEEP | {":LEVEL?": ":LEVEL CC", ":LEVEL:CCURR?": ":LEVEL:CCURRENT 1e-3"},
    )
    source = analyzer.get_excitation()
    assert source.mode is ImpedanceSourceMode.CURRENT
    assert source.level_a_rms == 0.001
    assert source.level_v_rms is None and not source.dc_bias_enabled
    with pytest.raises(InstrumentConfigurationError, match="voltage mode"):
        analyzer.configure_voltage_excitation(0.05)
    backend.write.assert_not_called()


def test_hioki_voltage_and_correction_inspection_are_distinct_operations():
    analyzer, backend = _instrument(
        "hioki/IM3570",
        HIOKI_VOLTAGE
        | {
            ":CORR:OPEN:RET?": ":CORRECTION:OPEN:RETURN ALL",
            ":CORR:SHOR:RET?": ":CORRECTION:SHORT:RETURN OFF",
        },
    )
    source = analyzer.configure_voltage_excitation(0.025)
    assert source.mode is ImpedanceSourceMode.OPEN_CIRCUIT_VOLTAGE
    assert source.level_v_rms == 0.025
    before = backend.write.call_count
    correction = analyzer.get_fixture_correction()
    assert (correction.open_enabled, correction.short_enabled, correction.load_enabled) == (
        True,
        False,
        None,
    )
    assert "correction_load" not in analyzer.config.scpi.queries
    assert ":CORR:LOAD:RET?" not in [call.args[0] for call in backend.query.call_args_list]
    assert backend.write.call_count == before == 1


@pytest.mark.parametrize("profile", ["keysight/E4990A", "hioki/IM3570"])
def test_typed_impedance_operations_are_strictly_discoverable_without_io(profile):
    analyzer, backend = _instrument(profile, {})
    report = analyzer.validate_operation_contract(strict=True, check_parameters=True)
    for key in (
        "read_measurement_sweep",
        "get_measurement_settings",
        "configure_measurement_settings",
        "get_excitation",
        "configure_voltage_excitation",
        "get_fixture_correction",
        "get_segmented_sweep",
        "configure_frequency_segment",
        "configure_measurement_parameter",
        "get_fixture_setup",
        "read_fixture_standard",
    ):
        assert report[key]["supported"]
    assert report["acquire_impedance_sweep"]["supported"] is profile.startswith("keysight")
    options = analyzer.list_operation_options("read_measurement_sweep", "parameter")
    assert any(
        option["value"] == "parallel_capacitance" and option["unit"] == "F" for option in options
    )
    assert not backend.mock_calls


KEYSIGHT_SEGMENTS = KEYSIGHT_SWEEP | {
    ":SENS1:SWE:TYPE?": "SEGM",
    ":SENS1:SEGM:DATA?": "7,0,0,0,1,1,0,1,2,1000,2000,10,2,3,0.01,4000,5000,30,4,8,0",
    ":SENS1:SEGM:SWE:POIN?": "40",
}
HIOKI_SEGMENTS = HIOKI_SWEEP | {
    ":SEGM?": ":SEGMENT ON",
    ":SEGM:NUM?": "SEGMENT:NUM 2",
    ":SEGM:SUB:SOUR?": ":SEGMENT:SUB:SOURCE V",
    ":SEGM:STAR:STOP? 1": ":SEGMENT:START:STOP 1000,2000,10,LOG",
    ":SEGM:STAR:STOP? 2": ":SEGMENT:START:STOP 4000,5000,30,LINEAR",
    ":SEGM:SUB:SOUR:VAL? 1": ":SEGMENT:SUB:SOURCE:VALUE 0.025",
    ":SEGM:SUB:SOUR:VAL? 2": ":SEGMENT:SUB:SOURCE:VALUE 0.05",
    ":SEGM:RANG? 1": ":SEGMENT:RANGE AUTO",
    ":SEGM:RANG? 2": ":SEGMENT:RANGE 4",
    ":SEGM:SPEE? 1": ":SEGMENT:SPEED MEDIUM",
    ":SEGM:SPEE? 2": ":SEGMENT:SPEED SLOW2",
    ":SEGM:AVER? 1": ":SEGMENT:AVERAGING OFF",
    ":SEGM:AVER? 2": ":SEGMENT:AVERAGING 5",
    ":SEGM:PDEL? 1": ":SEGMENT:PDELAY 0.0005",
    ":SEGM:PDEL? 2": ":SEGMENT:PDELAY 0.001",
}


def test_keysight_segment_table_decodes_center_span_and_optional_units():
    replies = KEYSIGHT_SEGMENTS | {
        ":SENS1:SEGM:DATA?": "7,1,1,1,1,1,1,1,2,1500,1000,10,1,0.001,0,-0.5,2,3,0.1,0.01,4500,1000,30,0,0.05,1,0.0001,4,8,0.2,0",
    }
    analyzer, backend = _instrument("keysight/E4990A", replies)
    table = analyzer.get_segmented_sweep()
    assert table.total_points == 40
    a, b = table.segments
    assert (a.index, a.start_hz, a.stop_hz, a.points, a.spacing) == (1, 1000, 2000, 10, "linear")
    assert a.source is not None and (a.source.unit, a.source.value) == ("Arms", 0.001)
    assert a.bias is not None and (a.bias.unit, a.bias.value) == ("V", -0.5)
    assert (a.speed_step, a.averages, a.sweep_time_s, a.delay_s) == (2, 3, 0.1, 0.01)
    assert b.source is not None and (b.source.unit, b.source.value) == ("Vrms", 0.05)
    assert b.bias is not None and (b.bias.unit, b.bias.value) == ("A", 0.0001)
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "replies,match",
    [
        (
            KEYSIGHT_SEGMENTS | {":SENS1:SEGM:DATA?": "7,0,0,0,0,0,0,0,2,1000,2000,10"},
            "field count",
        ),
        (KEYSIGHT_SEGMENTS | {":SENS1:SEGM:SWE:POIN?": "39"}, "point total"),
    ],
)
def test_keysight_segment_table_rejects_inconsistent_replies(replies, match):
    analyzer, backend = _instrument("keysight/E4990A", replies)
    with pytest.raises(InstrumentDataError, match=match):
        analyzer.get_segmented_sweep()
    backend.write.assert_not_called()


def test_hioki_segment_table_preserves_per_row_state_and_programmed_units():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SEGMENTS)
    table = analyzer.get_segmented_sweep()
    a, b = table.segments
    assert table.total_points == 40
    assert (a.spacing, a.auto_range, a.averages, a.delay_s) == ("log", True, 1, 0.0005)
    assert (b.spacing, b.fixed_range_ohm, b.speed_step, b.averages) == ("linear", 300, 4, 5)
    assert b.source is not None and b.source.unit == "Vrms" and b.source.value == 0.05
    backend.write.assert_not_called()


def test_keysight_edits_one_existing_segment_preserving_optional_fields():
    replies = dict(KEYSIGHT_SEGMENTS)
    analyzer, backend = _instrument("keysight/E4990A", replies)
    expected = ":SENS1:SEGM:DATA 7,0,0,0,1,1,0,1,2,1000,2000,10,2,3,0.01,6000,6500,40,4,8,0"

    def write(command, **_):
        assert command == expected
        replies[":SENS1:SEGM:DATA?"] = expected.split(" ", 1)[1]
        replies[":SENS1:SEGM:SWE:POIN?"] = "50"

    backend.write.side_effect = write
    row = analyzer.configure_frequency_segment(2, 6000, 6500, 40)
    assert (row.start_hz, row.stop_hz, row.points, row.averages) == (6000, 6500, 40, 8)
    backend.write.assert_called_once_with(expected)


def test_hioki_edits_only_the_existing_segment_after_guards():
    replies = dict(HIOKI_SEGMENTS)
    analyzer, backend = _instrument("hioki/IM3570", replies)

    def write(command, **_):
        assert command == ":SEGM:STAR:STOP 1,1000,3000,50,LOG"
        replies[":SEGM:STAR:STOP? 1"] = ":SEGMENT:START:STOP 1000,3000,50,LOG"

    backend.write.side_effect = write
    row = analyzer.configure_frequency_segment(1, 1000, 3000, 50, spacing="log")
    assert (row.index, row.points, row.spacing) == (1, 50, "log")
    backend.write.assert_called_once_with(":SEGM:STAR:STOP 1,1000,3000,50,LOG")


@pytest.mark.parametrize(
    "profile,replies,stop_hz,points,match",
    [
        ("hioki/IM3570", HIOKI_SEGMENTS | {":DCBIAS?": ":DCBIAS ON"}, 2000, 50, "DC bias"),
        (
            "hioki/IM3570",
            HIOKI_SEGMENTS | {":SEGM:SUB:SOUR?": ":SEGMENT:SUB:SOURCE CC"},
            2000,
            50,
            "V source",
        ),
        ("hioki/IM3570", HIOKI_SEGMENTS, 1_100_000, 50, "at or below 1 MHz"),
        ("hioki/IM3570", HIOKI_SEGMENTS, 2000, 801, "total point limit"),
        ("keysight/E4990A", KEYSIGHT_SEGMENTS | {":SOUR:BIAS:STAT?": "1"}, 2000, 50, "bias"),
        (
            "keysight/E4990A",
            KEYSIGHT_SEGMENTS
            | {":SENS1:SEGM:DATA?": "7,0,1,0,0,0,0,0,2,1000,2000,10,0,0.005,4000,5000,30,0,0.005"},
            2000,
            50,
            "list oscillator",
        ),
    ],
)
def test_segment_setup_fails_before_write_for_unsafe_or_excessive_state(
    profile, replies, stop_hz, points, match
):
    analyzer, backend = _instrument(profile, replies)
    with pytest.raises((InstrumentConfigurationError, InstrumentParameterError), match=match):
        analyzer.configure_frequency_segment(1, 1000, stop_hz, points)
    backend.write.assert_not_called()


def test_segment_edit_does_not_claim_unverified_settings():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SEGMENTS)
    with pytest.raises(InstrumentConfigurationError, match="did not verify"):
        analyzer.configure_frequency_segment(1, 1000, 3000, 10)
    backend.write.assert_called_once()


def test_hioki_selects_second_analyzer_slot_using_hardware_para3():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SWEEP | {":PARA3?": ":PARAMETER3 G"})
    assert (
        analyzer.configure_measurement_parameter(
            "conductance",
            trace=2,
        )
        is ImpedanceParameter.CONDUCTANCE
    )
    backend.write.assert_called_once_with(":PARA3 G")
    assert backend.query.call_args.args == (":PARA3?",)


def test_hioki_rejects_lcr_and_active_bias_before_writing_a_display_slot():
    replies = HIOKI_SWEEP | {":MODE?": ":MODE LCR"}
    analyzer, backend = _instrument("hioki/IM3570", replies)
    with pytest.raises(InstrumentConfigurationError, match="measurement_mode"):
        analyzer.configure_measurement_parameter("conductance")
    replies[":MODE?"] = ":MODE ANALYZER"
    replies[":DCBIAS?"] = ":DCBIAS ON"
    with pytest.raises(InstrumentConfigurationError, match="DC bias"):
        analyzer.configure_measurement_parameter("conductance")
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "profile,replies",
    [
        (
            "keysight/E4990A",
            KEYSIGHT_SWEEP
            | {
                ":CALC1:PAR2:DEF?": "G",
                ":CALC1:DATA:FDAT?": "0.001,0,0.002,0,0.003,0",
            },
        ),
        (
            "hioki/IM3570",
            HIOKI_SWEEP
            | {
                ":MEAS:POIN? 1": "0,1000,Y 0.1,G 0.001",
                ":MEAS:POIN? 2": "0,15600,Y 0.1,G 0.002",
                ":MEAS:POIN? 3": "0,49000,Y 0.1,G 0.003",
            },
        ),
    ],
)
def test_admittance_conductance_uses_native_si_units(profile, replies):
    analyzer, backend = _instrument(profile, replies)
    curve = analyzer.read_measurement_sweep("conductance")
    assert curve.parameter is ImpedanceParameter.CONDUCTANCE
    assert (curve.values, curve.unit) == ((0.001, 0.002, 0.003), "S")
    backend.write.assert_not_called()


def test_get_fixture_setup_distinguishes_keysight_user_cal_and_fixture_settings():
    analyzer, backend = _instrument(
        "keysight/E4990A",
        KEYSIGHT_SWEEP
        | {
            ":SENS1:CORR2:OPEN?": "1",
            ":SENS1:CORR2:SHOR?": "0",
            ":SENS1:CORR2:LOAD?": "1",
            ":SENS1:CORR1:STAT?": "0",
            ":SENS1:CORR2:EDEL:STAT?": "1",
            ":SENS1:CORR2:EDEL:TIME?": "2.5e-9",
        },
    )
    setup = analyzer.get_fixture_setup()
    assert setup.correction.open_enabled and setup.correction.load_enabled
    assert setup.port_calibration_enabled is False
    assert setup.port_extension_enabled and setup.port_extension_s == 2.5e-9
    assert setup.cable_compensation_m is None
    backend.write.assert_not_called()


def test_get_fixture_setup_retains_hioki_modes_and_range_without_lcr_queries():
    analyzer, backend = _instrument(
        "hioki/IM3570",
        HIOKI_SWEEP
        | {
            ":CORR:OPEN:RET?": ":CORRECTION:OPEN:RETURN ALL",
            ":CORR:SHOR:RET?": ":CORRECTION:SHORT:RETURN SPOT",
            ":CORR:CABL?": ":CORRECTION:CABLE 1",
            ":CORR:SCAL?": ":CORRECTION:SCALE ON",
            ":CORR:LIM:POIN?": ":CORRECTION:OPEN:LIMIT 1000,20000",
        },
    )
    setup = analyzer.get_fixture_setup()
    assert (setup.open_mode, setup.short_mode) == ("ALL", "SPOT")
    assert setup.cable_compensation_m == 1 and setup.scaling_enabled
    assert setup.ac_compensation_hz == (1000, 20000)
    assert setup.correction.load_enabled is None
    assert setup.port_calibration_enabled is None
    assert all(":CORR:LOAD" not in call.args[0] for call in backend.query.call_args_list)
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "profile,reply,match",
    [
        ("keysight/E4990A", {":INIT1:CONT?": ":OTHER 0"}, "continuous_sweep"),
        ("keysight/E4990A", {":SOUR:BIAS:STAT?": ":OTHER 0"}, "bias"),
        ("hioki/IM3570", {":SWE:MAIN:SOUR?": ":WRONG FREQ"}, "response header"),
        ("hioki/IM3570", {":COMP:ANAL?": ":OTHER OFF"}, "response header"),
        ("hioki/IM3570", {":COMP:ANAL?": ":COMPARATOR:ANALYZER PEAK"}, "Comparator OFF"),
        ("hioki/IM3570", {":SEGM:STAR:STOP? 1": "1000,2e6,10,LIN"}, "at or below 1 MHz"),
    ],
)
def test_segment_edit_rejects_wrong_reply_context_and_active_comparator(profile, reply, match):
    baseline = KEYSIGHT_SEGMENTS if profile.startswith("keysight") else HIOKI_SEGMENTS
    analyzer, backend = _instrument(profile, baseline | reply)
    with pytest.raises(InstrumentConfigurationError, match=match):
        analyzer.configure_frequency_segment(1, 1000, 3000, 10)
    backend.write.assert_not_called()


def test_hioki_parameter_and_normal_sweep_edits_preserve_active_comparator():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_SWEEP | {":COMP:ANAL?": "AREA"})
    with pytest.raises(InstrumentConfigurationError, match="Comparator OFF"):
        analyzer.configure_frequency_sweep(1000, 2000, 10)
    with pytest.raises(InstrumentConfigurationError, match="Comparator OFF"):
        analyzer.configure_measurement_parameter("conductance")
    backend.write.assert_not_called()


@pytest.mark.parametrize("scalar", [False, True])
def test_keysight_segmented_buffer_uses_total_from_segment_table(scalar):
    replies = KEYSIGHT_SWEEP | {
        ":SENS1:SWE:TYPE?": "SEGM",
        ":SENS1:SWE:POIN?": "999",
        ":SENS1:SEGM:SWE:POIN?": "3",
    }
    if scalar:
        replies |= {":CALC1:PAR2:DEF?": "G", ":CALC1:DATA:FDAT?": "0.001,0,0.002,0,0.003,0"}
    analyzer, backend = _instrument("keysight/E4990A", replies)
    curve = (
        analyzer.read_measurement_sweep("conductance")
        if scalar
        else analyzer.read_impedance_sweep()
    )
    assert len(curve.frequency_hz) == 3
    calls = [call.args[0] for call in backend.query.call_args_list]
    assert ":SENS1:SEGM:SWE:POIN?" in calls
    assert ":SENS1:SWE:POIN?" not in calls


E4990_STANDARD = KEYSIGHT_SWEEP | {
    ":SENS1:CORR2:ZME:OPEN:POIN?": "2",
    ":SENS1:CORR2:ZME:OPEN:FREQ?": "1000,2000",
    ":SENS1:CORR2:ZME:OPEN?": "1e7,-2e7,3e7,-4e7",
    ":SENS1:CORR2:OPEN?": "0",
}
HIOKI_STANDARD = HIOKI_SWEEP | {
    ":CORR:OPEN:RET?": ":CORRECTION:OPEN:RETURN ALL",
    ":CORR:OPEN:ERR?": ":CORRECTION:OPEN:ERROR 2",
    ":CORR:OPEN:DATA:ALL?": "0,1e-9,0,4,0,0,5e6,-0.25e-8,1.5e-7",
    ":CORR:SHOR:RET?": ":CORRECTION:SHORT:RETURN SPOT",
    ":CORR:SHOR:ERR?": ":CORRECTION:SHORT:ERROR 0",
    ":CORR:SHOR:DATA:SPOT? 1": "OFF,0,0",
    ":CORR:SHOR:DATA:SPOT? 5": "0,0.011,0",
}


def test_e4990a_retained_fixture_standard_uses_its_own_axis_and_units():
    analyzer, backend = _instrument("keysight/E4990A", E4990_STANDARD)
    data = analyzer.read_fixture_standard(ImpedanceStandardKind.OPEN)
    assert data.calibration_layer is ImpedanceCalibrationLayer.FIXTURE
    assert (data.unit, data.ac_span_hz, data.correction_enabled) == ("ohm", (1000, 2000), False)
    assert [sample.value for sample in data.samples] == [1e7 - 2e7j, 3e7 - 4e7j]
    assert data.compensation_result_flag is None
    assert all(":CORR1:" not in call.args[0] for call in backend.query.call_args_list)
    backend.write.assert_not_called()


def test_e4990a_user_layer_uses_shared_cal1_axis_not_active_or_fixture_axis():
    analyzer, backend = _instrument(
        "keysight/E4990A",
        KEYSIGHT_SWEEP
        | {
            ":SENS1:CORR1:ZME:POIN?": "2",
            ":SENS1:CORR1:ZME:FREQ?": "1000,20000",
            ":SENS1:CORR1:ZME:LOAD?": "49,0.2,49.5,0.4",
            ":SENS1:CORR1:STAT?": "1",
        },
    )
    data = analyzer.read_fixture_standard("load", calibration_layer=ImpedanceCalibrationLayer.USER)
    assert data.standard is ImpedanceStandardKind.LOAD and data.correction_enabled
    assert [sample.frequency_hz for sample in data.samples] == [1000, 20000]
    assert [sample.value for sample in data.samples] == [49 + 0.2j, 49.5 + 0.4j]
    assert all(":CORR2:" not in call.args[0] for call in backend.query.call_args_list)
    backend.write.assert_not_called()


def test_e4990a_empty_standard_does_not_read_data_or_certify_enable_state():
    analyzer, backend = _instrument(
        "keysight/E4990A",
        E4990_STANDARD
        | {
            ":SENS1:CORR2:ZME:OPEN:POIN?": "0",
            ":SENS1:CORR2:OPEN?": "1",
        },
    )
    data = analyzer.read_fixture_standard("open")
    assert data.samples == () and data.ac_span_hz is None
    assert data.correction_enabled
    queries = [call.args[0] for call in backend.query.call_args_list]
    assert ":SENS1:CORR2:ZME:OPEN?" not in queries
    assert ":SENS1:CORR2:ZME:OPEN:FREQ?" not in queries
    backend.write.assert_not_called()


def test_hioki_all_open_standard_preserves_dc_and_ambiguous_zero_in_siemens():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_STANDARD)
    data = analyzer.read_fixture_standard("open")
    assert (data.quantity, data.unit, data.applied_mode) == ("admittance", "S", "ALL")
    assert data.compensation_result_flag is CompensationResult.RANGE_UNDETERMINED
    assert data.zero_may_be_uncaptured
    assert [sample.frequency_hz for sample in data.samples] == [0, 4, 5e6]
    assert [sample.value for sample in data.samples] == [1e-9 + 0j, 0j, -0.25e-8 + 1.5e-7j]
    assert data.ac_span_hz == (4, 5e6)
    backend.write.assert_not_called()


@pytest.mark.parametrize("index,frequencies", [(1, []), (5, [0])])
def test_hioki_spot_distinguishes_disabled_and_valid_dc(index, frequencies):
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_STANDARD)
    data = analyzer.read_fixture_standard("short", spot=index)
    assert (data.unit, data.spot, data.ac_span_hz) == ("ohm", index, None)
    assert [sample.frequency_hz for sample in data.samples] == frequencies
    assert data.compensation_result_flag is CompensationResult.NORMAL
    assert backend.query.call_args.args == (f":CORR:SHOR:DATA:SPOT? {index}",)
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "profile,base,override,match",
    [
        ("keysight/E4990A", E4990_STANDARD, {":SENS1:CORR2:ZME:OPEN?": "0,1,2"}, "counts disagree"),
        (
            "keysight/E4990A",
            E4990_STANDARD,
            {":SENS1:CORR2:ZME:OPEN:FREQ?": "0,20"},
            "Invalid retained",
        ),
        (
            "hioki/IM3570",
            HIOKI_STANDARD,
            {":CORR:OPEN:DATA:ALL?": "4,0,0,5"},
            "Malformed Hioki ALL",
        ),
    ],
)
def test_malformed_retained_standard_never_returns_samples(profile, base, override, match):
    analyzer, backend = _instrument(profile, base | override)
    with pytest.raises(InstrumentDataError, match=match):
        analyzer.read_fixture_standard("open")
    backend.write.assert_not_called()


def test_standard_discovery_does_not_offer_hioki_load_or_keysight_spot():
    hioki, backend = _instrument("hioki/IM3570", {})
    hioki_options = hioki.list_operation_options(
        "read_fixture_standard", "standard", include_unsupported=True
    )
    assert {opt["value"] for opt in hioki_options if opt["supported"]} == {"open", "short"}
    assert {opt["value"] for opt in hioki_options if not opt["supported"]} == {"load"}
    with pytest.raises(InstrumentParameterError):
        hioki.read_fixture_standard("load")
    with pytest.raises(InstrumentParameterError):
        hioki.read_fixture_standard("open", calibration_layer="user")
    assert not backend.mock_calls

    keysight, backend = _instrument("keysight/E4990A", {})
    with pytest.raises(InstrumentParameterError):
        keysight.read_fixture_standard("open", spot=2)
    assert not backend.mock_calls


KEYSIGHT_LIMITS = KEYSIGHT_SWEEP | {
    ":CALC1:PAR2:DEF?": "G",
    ":CALC1:LIM?": "1",
    ":CALC1:LIM:DATA?": "3,1,-100,200e6,0.005,0.007,2,1000,2000,0,0.001,0,0,0,0,0",
    ":CALC1:LIM:OFFS:STIM?": "+20",
    ":CALC1:LIM:OFFS:AMPL?": "-0.0002",
}
HIOKI_AREA_LIMITS = HIOKI_SWEEP | {
    ":COMP:ANAL?": ":COMPARATOR:ANALYZER AREA",
    ":COMP:PARA?": ":COMPARATOR:PARAMETER ALL",
    ":PARA3?": ":PARAMETER3 CP",
    ":POIN? 2": ":POINT 15600",
    ":COMP:AREA:LIM? 2,2": ":COMPARATOR:AREA:LIMIT OFF,5e-8",
}
HIOKI_PEAK_LIMITS = HIOKI_SEGMENTS | {
    ":COMP:ANAL?": "PEAK",
    ":COMP:PARA?": "1",
    ":PARA1?": "Z",
    ":COMP:PEAK? 2,1,MIN": "4100,OFF,1.5,50",
}


def test_keysight_limit_table_uses_active_scalar_units_and_keeps_raw_offsets():
    analyzer, backend = _instrument("keysight/E4990A", KEYSIGHT_LIMITS)
    data = analyzer.get_trace_limit_table("conductance")
    assert (data.trace, data.unit, data.enabled) == (2, "S", True)
    assert (data.stimulus_offset_hz, data.response_offset) == (20, -0.0002)
    assert [line.kind for line in data.lines] == ["upper", "lower", "off"]
    assert (data.lines[0].start_hz, data.lines[0].stop_hz, data.lines[0].stop_value) == (
        -100,
        200e6,
        0.007,
    )
    backend.write.assert_not_called()


def test_keysight_trace_limit_table_rejects_bad_shape_and_nonfrequency_axis():
    replies = KEYSIGHT_LIMITS | {":CALC1:LIM:DATA?": "2,1,1000,2000,0.005,0.007"}
    analyzer, backend = _instrument("keysight/E4990A", replies)
    with pytest.raises(InstrumentDataError, match="field count"):
        analyzer.get_trace_limit_table("conductance")
    replies[":SENS1:SWE:TYPE?"] = "BIAS"
    backend.reset_mock()
    with pytest.raises(InstrumentConfigurationError, match="sweep_domain"):
        analyzer.get_trace_limit_table("conductance")
    assert ":CALC1:LIM:DATA?" not in [call.args[0] for call in backend.query.call_args_list]
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "bad_readback,field",
    [
        ({":CALC1:UNIT:ANGL?": "RAD"}, "phase_unit"),
        ({":CALC1:FORM:EPH?": "1"}, "expanded_phase"),
    ],
)
def test_keysight_phase_limit_table_refuses_unverified_angle_context(bad_readback, field):
    analyzer, backend = _instrument(
        "keysight/E4990A",
        KEYSIGHT_LIMITS
        | {
            ":CALC1:PAR2:DEF?": "TZ",
            ":CALC1:FORM:EPH?": "0",
            ":CALC1:UNIT:ANGL?": "DEG",
        }
        | bad_readback,
    )
    with pytest.raises(InstrumentConfigurationError, match=field):
        analyzer.get_trace_limit_table("phase")
    assert ":CALC1:LIM:DATA?" not in [call.args[0] for call in backend.query.call_args_list]
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "command,states,field",
    [
        (":CALC1:UNIT:ANGL?", ("DEG", "RAD"), "phase_unit"),
        (":CALC1:FORM:EPH?", ("0", "1"), "expanded_phase"),
        (":SENS1:SWE:TYPE?", ("LIN", "LOG"), "context changed"),
    ],
)
def test_keysight_limits_are_not_returned_after_context_drift(command, states, field):
    replies = KEYSIGHT_LIMITS | {
        ":CALC1:PAR2:DEF?": "TZ",
        ":CALC1:FORM:EPH?": "0",
        ":CALC1:UNIT:ANGL?": "DEG",
    }
    analyzer, backend = _instrument("keysight/E4990A", replies)
    responses = iter(states)
    backend.query.side_effect = lambda actual, **_: (
        next(responses) if actual == command else replies[actual]
    )
    with pytest.raises(InstrumentConfigurationError, match=field):
        analyzer.get_trace_limit_table("phase")
    assert ":CALC1:LIM:DATA?" in [call.args[0] for call in backend.query.call_args_list]
    backend.write.assert_not_called()


def test_hioki_area_uses_point_setpoint_and_logical_display_slot_units():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_AREA_LIMITS)
    data = analyzer.get_area_comparator_limits(2, slot=2)
    assert (data.point, data.frequency_hz, data.unit) == (2, 15600, "F")
    assert (data.lower, data.upper) == (None, 5e-8)
    assert data.parameter is ImpedanceParameter.PARALLEL_CAPACITANCE
    backend.write.assert_not_called()


def test_hioki_peak_binds_segment_slot_and_extremum_without_reading_results():
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_PEAK_LIMITS)
    data = analyzer.get_peak_comparator_limits(segment=2, peak="min")
    assert (data.segment, data.peak, data.unit) == (2, "min", "ohm")
    assert (data.left_hz, data.right_hz, data.lower, data.upper) == (4100, None, 1.5, 50)
    assert backend.query.call_args.args == (":COMP:PEAK? 2,1,MIN",)
    backend.write.assert_not_called()


@pytest.mark.parametrize(
    "override,match",
    [
        ({":COMP:PARA?": "1"}, "not selected"),
        ({":COMP:AREA:LIM? 2,2": ":WRONG OFF,1"}, "response header"),
        ({":SWE:MAIN:SOUR?": ":SWEEP:MAIN:SOURCE V"}, "sweep_domain"),
    ],
)
def test_hioki_configured_limits_fail_closed_on_wrong_axis_or_slot(override, match):
    analyzer, backend = _instrument("hioki/IM3570", HIOKI_AREA_LIMITS | override)
    with pytest.raises(InstrumentConfigurationError, match=match):
        analyzer.get_area_comparator_limits(2, slot=2)
    backend.write.assert_not_called()


@pytest.mark.parametrize("profile", ["keysight/E4990A", "hioki/IM3570"])
def test_comparator_discovery_is_model_specific_and_passive(profile):
    analyzer, backend = _instrument(profile, {})
    support = analyzer.validate_operation_contract(strict=True, check_parameters=True)
    hioki = profile.startswith("hioki")
    assert support["get_trace_limit_table"]["supported"] is not hioki
    assert support["get_area_comparator_limits"]["supported"] is hioki
    assert support["get_peak_comparator_limits"]["supported"] is hioki
    assert not backend.mock_calls
