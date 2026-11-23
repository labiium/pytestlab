"""Hand-authored vendor-manual transcripts, not captured instrument measurements."""

from collections import Counter
from unittest.mock import Mock
from unittest.mock import call

import pytest
from pyvisa.constants import StatusCode
from pyvisa.errors import VisaIOError
from pyvisa.resources import MessageBasedResource

from pytestlab import AutoInstrument
from pytestlab.config.loader import load_device_profile
from pytestlab.config.vna_config import VNAConfig
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.instruments.backends.visa_backend import VisaBackend
from pytestlab.instruments.VectorNetworkAnalyser import VectorNetworkAnalyser
from pytestlab.uncertainty import QuantityArray

PROFILE = "coppermountain/C1209"
ADDR = "TCPIP0::the-socket.example::5025::SOCKET"
STATUS = StatusCode.success_termination_character_read
IDN = b"CMT,C1209,08080188,26.2.2/01"
BASE = {
    "*IDN?": IDN,
    ":TRIG:STAT?": b"HOLD",
    ":INIT1:CONT?": b"0",
    ":SENS1:SWE:TYPE?": b"LOG",
    ":SENS1:SEGM:DATA?": b"5,1,1,1,1,1,2,2e6,2e6,3,500,-20,.1,7,5e6,2e6,11,100,-15,0,0",
    ":SENS1:FREQ:SPAN?": b"99000000",
    ":SERV:PORT:COUN?": b"2",
    ":SERV:CHAN:COUN?": b"16",
    ":SERV:CHAN:TRAC:COUN?": b"16",
    ":SERV:SWE:POIN?": b"+2.00001e5",
    ":SERV:CHAN:ACT?": b"3",
    ":SERV:SWE:FREQ:MIN?": b"1.0e5",
    ":SERV:SWE:FREQ:MAX?": b"9.0e9",
    ":SENS1:FREQ:STAR?": b"1e6",
    ":SENS1:FREQ:STOP?": b"1e8",
    ":SENS1:BWID?": b"500",
    ":SENS1:AVER?": b"1",
    ":SENS1:AVER:COUN?": b"16",
    ":SENS:CORR:PORT1:IMP:INP:MAGN?": b"50",
    ":SENS:CORR:PORT2:IMP:INP:MAGN?": b"75",
    ":SENS1:CORR:STAT?": b"1",
    ":SENS1:CORR:EXT:STAT?": b"0",
    ":CALC1:TRAC2:MARK15:STAT?": b"1",
    ":CALC1:TRAC2:MARK16:STAT?": b"0",
    ":CALC1:TRAC2:FORM?": b"MLOG",
    ":DISP:WIND1:TRAC2:STAT?": b"1",
    ":DISP:WIND1:TRAC2:MEM?": b"0",
    ":CALC1:TRAC2:MARK15:X?": b"25e6",
    ":CALC1:TRAC2:MARK15:Y?": b"-18.1,0",
    ":SENS1:CORR:TYPE1?": b"SOLT2,1,2",
    ":SENS1:CORR:TYPE2?": b"NONE",
    ":SENS1:OFFS:STAT?": b"0",
    ":CALC1:FSIM:STAT?": b"0",
    ":SENS1:SWE:POIN?": b"3",
    ":CALC1:PAR:COUN?": b"2",
    ":CALC1:PAR1:DEF?": b"S21",
    ":CALC1:PAR2:DEF?": b"S11",
    ":CALC1:TRAC1:DATA:SDAT?": b"1,2,3,4,5,6",
    ":CALC1:TRAC2:DATA:SDAT?": b".1,-.2,.3,-.4,.5,-.6",
}
for trace in (1, 2):
    for suffix, value in (
        ("DATA:XAX?", b"1e6,1e7,1e8"),
        ("MATH:FUNC?", b"OFF"),
        ("TRAN:TIME:STAT?", b"0"),
        ("FILT:TIME:STAT?", b"0"),
        ("CONV:STAT?", b"0"),
        ("HOLD:TYPE?", b"OFF"),
    ):
        BASE[f":CALC1:TRAC{trace}:{suffix}"] = value


def _build(monkeypatch, responses=None, *, serial_number=None, s_parameters=None):
    config = load_device_profile(PROFILE)
    assert isinstance(config, VNAConfig)
    config.serial_number = serial_number
    if s_parameters is not None:
        config.s_parameters = s_parameters

    manager = Mock()
    monkeypatch.setattr("pyvisa.ResourceManager", lambda: manager)
    resources = []
    exchanges = []
    visited = Counter()
    overrides = responses or {}

    def open_resource(address):
        assert address == ADDR
        resource = Mock(spec=MessageBasedResource)
        resource.timeout = 5000
        resource.session = 1
        resource.visalib = Mock()
        resources.append(resource)
        last_command = None

        def write(command, *, encoding):
            nonlocal last_command
            assert encoding == "ascii"
            assert command.endswith("?") and ";" not in command
            assert resource.read_termination == "\n"
            assert resource.write_termination == "\n"
            assert command in BASE, command
            last_command = command
            visited[command] += 1
            return len(command) + 1

        def read(session, limit):
            assert session == resource.session
            assert last_command is not None
            exchanges.append((last_command, limit))
            value = overrides.get((last_command, visited[last_command]), BASE[last_command])
            if isinstance(value, BaseException):
                raise value
            if isinstance(value, tuple):
                return value
            return value + b"\n", STATUS

        resource.write.side_effect = write
        resource.visalib.read.side_effect = read
        return resource

    manager.open_resource.side_effect = open_resource
    return VectorNetworkAnalyser(config, VisaBackend(ADDR)), resources, exchanges


def test_contract_and_held_log_data_keep_identity_and_axis_paired(monkeypatch):
    analyzer, resources, exchanges = _build(monkeypatch, serial_number="08080188")
    reports = analyzer.validate_operation_contract(
        strict=True, check_parameters=True, include_unsupported=True
    )
    assert reports["sparameter_data"]["supported"]
    assert not reports["sparameter_sweep_setup"]["supported"]
    assert not reports["sparameter_sweep_settings"]["supported"]
    assert not reports["reset"]["supported"]
    with pytest.raises(InstrumentConfigurationError, match="held trace"):
        analyzer.configure_s_parameter_sweep()
    assert not resources

    result = analyzer.get_s_parameter_data()
    assert result.frequencies == [1e6, 1e7, 1e8]
    assert result.param_names == ["S11", "S21"]
    assert result.s_params == [[0.1 - 0.2j, 0.3 - 0.4j, 0.5 - 0.6j], [1 + 2j, 3 + 4j, 5 + 6j]]
    assert result.axis_source == "instrument" and result.trace_identity_verified
    assert [(command, cap) for command, cap in exchanges if command.endswith("SDAT?")] == [
        (":CALC1:TRAC2:DATA:SDAT?", 290),
        (":CALC1:TRAC1:DATA:SDAT?", 290),
    ]
    assert exchanges[0][0] == "*IDN?"
    assert [command for command, _ in exchanges[-2:]] == [":TRIG:STAT?", ":INIT1:CONT?"]
    resources[0].close.assert_not_called()


@pytest.mark.parametrize(
    ("command", "reply", "message"),
    [
        ("*IDN?", b"Keysight,C1209,08080188,26.2.2/01", "exact S2VNA"),
        ("*IDN?", b"CMT,C1220,08080188,26.2.2/01", "exact S2VNA"),
        ("*IDN?", b"CMT,C1209,08080188,26.2/01", "exact S2VNA"),
        ("*IDN?", b"CMT,C1209,SIM,26.2.2/01", "exact S2VNA"),
        (":TRIG:STAT?", b"WTRG", "HOLD"),
        (":TRIG:STAT?", b"MEAS", "HOLD"),
        (":INIT1:CONT?", b"1", "continuous"),
        (":SENS1:SWE:TYPE?", b"POW", "LIN or LOG"),
        (":SENS1:SWE:TYPE?", b"SEGM", "LIN or LOG"),
        (":SENS1:FREQ:SPAN?", b"0", "positive span"),
        (":SENS1:OFFS:STAT?", b"1", "frequency offset off"),
        (":CALC1:FSIM:STAT?", b"1", "fixture simulator off"),
        (":SENS1:SWE:POIN?", b"20002", "outside supported"),
        (":CALC1:TRAC2:MATH:FUNC?", b"DIV", "trace_math"),
        (":CALC1:TRAC2:TRAN:TIME:STAT?", b"1", "trace_time_transform"),
        (":CALC1:TRAC2:FILT:TIME:STAT?", b"1", "trace_gate"),
        (":CALC1:TRAC2:CONV:STAT?", b"1", "trace_conversion"),
        (":CALC1:TRAC2:HOLD:TYPE?", b"MAX", "trace_hold"),
    ],
)
def test_refuses_unsupported_identity_or_modes(monkeypatch, command, reply, message):
    analyzer, resources, exchanges = _build(monkeypatch, {(command, 1): reply})
    with pytest.raises(InstrumentConfigurationError, match=message):
        analyzer.get_s_parameter_data()
    assert not any("SDAT?" in command for command, _ in exchanges)
    resources[0].close.assert_called_once()


@pytest.mark.parametrize(
    ("key", "reply", "message"),
    [
        ((":CALC1:PAR1:DEF?", 1), b"S11", "one configured S11"),
        ((":CALC1:PAR2:DEF?", 1), b"R1", "one configured S11"),
        ((":CALC1:TRAC2:DATA:XAX?", 1), b"0,1e7,1e8", "positive"),
        ((":CALC1:TRAC2:DATA:XAX?", 1), b"1e7,1e6,1e8", "increasing"),
        ((":CALC1:TRAC1:DATA:XAX?", 1), b"1e6,2e7,1e8", "same frequency axis"),
        ((":CALC1:TRAC2:DATA:XAX?", 2), b"1e6,2e7,1e8", "changed during"),
        ((":CALC1:PAR1:DEF?", 3), b"S11", "catalog changed"),
        ((":CALC1:TRAC2:DATA:SDAT?", 1), b"1,2,3", "Expected 6"),
        ((":CALC1:TRAC2:DATA:SDAT?", 1), b"1,2,3,4,5,nan", "finite ASCII"),
        ((":CALC1:TRAC2:DATA:SDAT?", 1), b"1,2,3,4,5,2e309", "non-finite"),
    ],
)
def test_rejects_unpaired_or_corrupt_trace_data(monkeypatch, key, reply, message):
    analyzer, resources, _ = _build(monkeypatch, {key: reply})
    with pytest.raises(InstrumentDataError, match=message):
        analyzer.get_s_parameter_data()
    resources[0].close.assert_called_once()


def test_rejects_matching_same_length_axes_with_wrong_span_before_data(monkeypatch):
    replies = {(f":CALC1:TRAC{trace}:DATA:XAX?", 1): b"1e6,2e6,3e6" for trace in (1, 2)}
    analyzer, resources, exchanges = _build(monkeypatch, replies)
    with pytest.raises(InstrumentDataError, match="axis span disagrees"):
        analyzer.get_s_parameter_data()
    assert not any(command.endswith("SDAT?") for command, _ in exchanges)
    resources[0].close.assert_called_once()


def test_axis_span_check_allows_small_independent_ascii_rounding(monkeypatch):
    analyzer, _, _ = _build(
        monkeypatch,
        {(":SENS1:FREQ:SPAN?", index): b"9.90000001e7" for index in (1, 2)},
    )
    assert analyzer.get_s_parameter_data().frequencies == [1e6, 1e7, 1e8]


@pytest.mark.parametrize(
    "failure",
    [
        (b"1,2,3", StatusCode.success),
        (b"1,2,3\n", StatusCode.success_max_count_read),
        (b"1,2,3\n1,2,3\n", STATUS),
        (b"1,2\xff,3\n", STATUS),
        (b"#11\n", STATUS),
        VisaIOError(StatusCode.error_timeout),
        KeyboardInterrupt(),
    ],
)
def test_discards_ambiguous_socket_without_retry_and_reopens_separately(monkeypatch, failure):
    cmd = ":CALC1:TRAC2:DATA:XAX?"
    analyzer, resources, exchanges = _build(monkeypatch, {(cmd, 1): failure})
    exception = (
        KeyboardInterrupt
        if isinstance(failure, KeyboardInterrupt)
        else InstrumentCommunicationError
    )
    with pytest.raises(exception):
        analyzer.get_s_parameter_data()
    assert exchanges[-1][0] == cmd
    assert len(resources) == 1
    assert resources[0].close.mock_calls == [call()]
    assert analyzer.get_s_parameter_data().frequencies == [1e6, 1e7, 1e8]
    assert len(resources) == 2
    assert resources[1].write.call_args_list[0].args == ("*IDN?",)


def test_refuses_non_socket_visa_resource_without_sending_a_query(monkeypatch):
    config = load_device_profile(PROFILE)
    assert isinstance(config, VNAConfig)
    manager = Mock()
    resource = Mock(spec=MessageBasedResource)
    manager.open_resource.return_value = resource
    monkeypatch.setattr("pyvisa.ResourceManager", lambda: manager)
    analyzer = VectorNetworkAnalyser(config, VisaBackend("TCPIP0::the-socket.example::INSTR"))
    with pytest.raises(InstrumentConfigurationError, match="TCPIP SOCKET"):
        analyzer.get_s_parameter_data()
    resource.write.assert_not_called()


def test_factory_profile_discovery_is_offline():
    analyzer = AutoInstrument.from_config(PROFILE)
    assert isinstance(analyzer, VectorNetworkAnalyser)
    assert set(analyzer.list_operations(include_unsupported=False)) == {
        "sparameter_data",
        "sparameter_channel_context",
        "sparameter_frequency_marker",
        "sparameter_segment_table",
        "vna_inventory",
    }


def test_cmt_context_is_passive_and_uses_variable_length_calibration_grammar(monkeypatch):
    analyzer, _, exchanges = _build(monkeypatch)
    context = analyzer.get_s_parameter_channel_context()
    assert context.evidence == "live_configuration"
    assert (context.model, context.software_revision, context.hardware_revision) == (
        "C1209",
        "26.2.2",
        "01",
    )
    assert context.port_reference_ohms == (50, 75)
    assert context.correction_enabled
    assert context.averaging_enabled and context.averaging_count == 16
    assert context.trace(1).correction_ports == (1, 2)
    assert context.trace(2).correction_ports == ()
    assert not any("DATA:" in command for command, _ in exchanges)
    held = analyzer.get_s_parameter_data(include_context=True)
    assert held.context is not None and held.context.evidence == "held_readback"
    assert held.trace("S21").context == context.trace(1)


def test_cmt_opt_in_held_context_rejects_drift_and_closes(monkeypatch):
    key = (":SENS:CORR:PORT2:IMP:INP:MAGN?", 2)
    analyzer, resources, _ = _build(monkeypatch, {key: b"80"})
    with pytest.raises(InstrumentDataError, match="context changed"):
        analyzer.get_s_parameter_data(include_context=True)
    resources[0].close.assert_called_once()


@pytest.mark.parametrize("reply", [b"NONE,0,0,0,0", b"SOLT2,1,1", b"SOLT2,1,3", b"SOLT1"])
def test_cmt_context_does_not_guess_approximate_reply_formats(monkeypatch, reply):
    analyzer, resources, _ = _build(monkeypatch, {(":SENS1:CORR:TYPE1?", 1): reply})
    with pytest.raises(InstrumentDataError, match="correction"):
        analyzer.get_s_parameter_channel_context()
    resources[0].close.assert_called_once()


def test_cmt_marker_uses_separate_indexed_x_and_y_and_allows_marker_15(monkeypatch):
    analyzer, _, exchanges = _build(monkeypatch)
    value = analyzer.get_s_parameter_frequency_marker(2, marker=15)
    assert (value.parameter, value.marker, value.frequency_hz, value.magnitude_db) == (
        "S11",
        15,
        25e6,
        -18.1,
    )
    assert [command for command, _ in exchanges].count(":CALC1:TRAC2:MARK15:X?") == 4
    assert [command for command, _ in exchanges].count(":CALC1:TRAC2:MARK15:Y?") == 2


def test_cmt_marker_declines_reference_delta_without_reading_its_data(monkeypatch):
    analyzer, resources, exchanges = _build(monkeypatch, {(":CALC1:TRAC2:MARK16:STAT?", 1): b"1"})
    with pytest.raises(InstrumentConfigurationError, match="reference"):
        analyzer.get_s_parameter_frequency_marker(2, marker=15)
    assert not any(":X?" in command or ":Y?" in command for command, _ in exchanges)
    resources[0].close.assert_called_once()


def test_cmt_marker_rejects_a_shifted_stimulus_without_retry(monkeypatch):
    analyzer, resources, _ = _build(monkeypatch, {(":CALC1:TRAC2:MARK15:X?", 2): b"26e6"})
    with pytest.raises(InstrumentDataError, match="Marker moved"):
        analyzer.get_s_parameter_frequency_marker(2, marker=15)
    resources[0].close.assert_called_once()


def test_cmt_segment_table_reads_columns_without_inventing_reserved_timing(monkeypatch):
    analyzer, resources, exchanges = _build(
        monkeypatch, {(":SENS1:SWE:TYPE?", 1): b"SEGM", (":SENS1:SWE:TYPE?", 2): b"SEGM"}
    )
    assert analyzer.supports_operation("sparameter_segment_table")
    report = analyzer.get_s_parameter_segment_table()
    assert (report.model, report.software_revision, report.hardware_revision) == (
        "C1209",
        "26.2.2",
        "01",
    )
    assert report.active_sweep_type == "segment" and report.frequency_mode == "center_span"
    first, second = report.segments
    assert (first.start_hz, first.stop_hz, first.point_count, first.if_bandwidth_hz) == (
        1e6,
        3e6,
        3,
        500,
    )
    assert (first.power_dbm, first.delay_s, first.vendor_reserved_value) == (-20, 0.1, 7)
    assert first.sweep_time_s is None and first.enabled is None and first.sweep_mode is None
    assert second.start_hz == 4e6 and second.stop_hz == 6e6
    assert report.individual_state_control is None
    assert len([cmd for cmd, _ in exchanges if cmd == ":SENS1:SEGM:DATA?"]) == 2
    assert all(
        command in {"*IDN?", ":TRIG:STAT?", ":INIT1:CONT?", ":SENS1:SWE:TYPE?", ":SENS1:SEGM:DATA?"}
        for command, _ in exchanges
    )
    resources[0].close.assert_not_called()


def test_cmt_segment_table_can_exceed_small_query_bound_but_uses_capped_read(monkeypatch):
    rows = [f"{index * 1_000_000},{index * 1_000_000 + 500_000},101" for index in range(1, 21)]
    wire = ("5,0,0,0,0,0,20," + ",".join(rows)).encode()
    assert len(wire) > 256
    analyzer, _, exchanges = _build(monkeypatch, {(":SENS1:SEGM:DATA?", n): wire for n in (1, 2)})
    table = analyzer.get_s_parameter_segment_table()
    assert len(table.segments) == 20 and table.segments[-1].stop_hz == 20_500_000
    assert all(len(wire) < limit <= 2_000_000 for cmd, limit in exchanges if cmd.endswith(":DATA?"))
    assert all(limit == 256 for cmd, limit in exchanges if not cmd.endswith(":DATA?"))


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (b"6,0,0,0,0,1,0,1,1e6,2e6,3,0", InstrumentDataError, "wire format"),
        (b"5,0,0,0,0,0,1,2e6,1e6,3", InstrumentDataError, "point count"),
        (b"5,0,0,0,0,0,1,1e6,2e6,3,", InstrumentDataError, "empty field"),
        (b"5,0,0,0,0,0,1,1e6,2e6,NaN", InstrumentDataError, "finite ASCII"),
        (
            (b"5,0,0,0,0,0,1,1e6,2e6,3", StatusCode.success_max_count_read),
            InstrumentCommunicationError,
            "socket discarded",
        ),
    ],
)
def test_cmt_segment_malformed_or_unterminated_reply_discards_socket(
    monkeypatch, response, error, message
):
    analyzer, resources, exchanges = _build(monkeypatch, {(":SENS1:SEGM:DATA?", 1): response})
    with pytest.raises(error, match=message):
        analyzer.get_s_parameter_segment_table()
    assert exchanges[-1][0] == ":SENS1:SEGM:DATA?"
    resources[0].close.assert_called_once()
    assert analyzer.get_s_parameter_segment_table().serial_number == "08080188"
    assert len(resources) == 2


def test_cmt_segment_refuses_different_s2vna_version_before_table_read(monkeypatch):
    analyzer, resources, exchanges = _build(
        monkeypatch, {("*IDN?", 1): b"CMT,C1209,08080188,26.4.1/01"}
    )
    with pytest.raises(InstrumentConfigurationError, match="exact S2VNA"):
        analyzer.get_s_parameter_segment_table()
    assert all(not command.endswith(":DATA?") for command, _ in exchanges)
    resources[0].close.assert_called_once()


def test_cmt_segment_table_change_discards_socket(monkeypatch):
    analyzer, resources, _ = _build(
        monkeypatch, {(":SENS1:SEGM:DATA?", 2): b"5,0,0,0,0,0,1,1e6,2e6,3"}
    )
    with pytest.raises(InstrumentDataError, match="table changed"):
        analyzer.get_s_parameter_segment_table()
    resources[0].close.assert_called_once()


def test_cmt_inventory_uses_service_replies_and_keeps_existing_offline_cap(monkeypatch):
    analyzer, resources, exchanges = _build(monkeypatch)
    report = analyzer.get_vna_inventory()
    assert (report.model, report.software_revision, report.hardware_revision) == (
        "C1209",
        "26.2.2",
        "01",
    )
    assert (report.port_count, report.max_channels, report.max_traces_per_channel) == (2, 16, 16)
    assert (report.max_sweep_points, report.profile_max_points) == (200_001, 20_001)
    assert (report.active_channel, report.profile_channel, report.profile_channel_trace_count) == (
        3,
        1,
        2,
    )
    limits = report.frequency_limits
    assert limits is not None
    assert (limits.minimum_hz, limits.maximum_hz, limits.source) == (
        100_000,
        9e9,
        "instrument_query",
    )
    assert report.options_reply is None and report.bias_tees_installed is None
    assert exchanges.count((":SERV:SWE:POIN?", 256)) == 2
    assert all(
        cmd not in {"*OPT?", ":SENS1:SWE:TYPE?", ":SENS1:SWE:POIN?"} and cap == 256
        for cmd, cap in exchanges
    )
    resources[0].close.assert_not_called()


@pytest.mark.parametrize(
    ("command", "response", "error", "message"),
    [
        (":TRIG:STAT?", b"MEAS", InstrumentConfigurationError, "stable held sweep"),
        ("*IDN?", b"CMT,C1220,08080188,26.2.2/01", InstrumentConfigurationError, "exact S2VNA"),
        (":SERV:PORT:COUN?", b"4", InstrumentConfigurationError, "ports"),
        (":SERV:SWE:POIN?", b"20.5", InstrumentDataError, "not an integer"),
        (":SERV:SWE:FREQ:MIN?", b"9e9", InstrumentDataError, "frequency limits"),
        (":SERV:SWE:FREQ:MAX?", b"inf", InstrumentDataError, "finite ASCII"),
        (
            ":SERV:SWE:POIN?",
            (b"200001", StatusCode.success_max_count_read),
            InstrumentCommunicationError,
            "socket discarded",
        ),
    ],
)
def test_cmt_inventory_rejects_invalid_identity_limits_or_transport_state(
    monkeypatch, command, response, error, message
):
    analyzer, resources, _ = _build(monkeypatch, {(command, 1): response})
    with pytest.raises(error, match=message):
        analyzer.get_vna_inventory()
    resources[0].close.assert_called_once()
    assert analyzer.get_vna_inventory().model == "C1209"
    assert len(resources) == 2


def test_cmt_inventory_rejects_changed_report(monkeypatch):
    analyzer, resources, _ = _build(monkeypatch, {(":SERV:SWE:FREQ:MAX?", 2): b"8e9"})
    with pytest.raises(InstrumentDataError, match="inventory changed"):
        analyzer.get_vna_inventory()
    resources[0].close.assert_called_once()


def test_cmt_held_readback_keeps_external_budget_separate_from_freshness(monkeypatch):
    analyzer, _, exchanges = _build(monkeypatch)
    held = analyzer.get_s_parameter_data(include_context=True)
    before = exchanges.copy()
    measured = held.with_uncertainty(
        QuantityArray(
            [0.1, -0.2, 1, 2, 0.3, -0.4, 3, 4, 0.5, -0.6, 5, 6],
            unit="1",
            diagonal_variance=[0.0001] * 12,
        ),
        frequencies_hz=[1e6, 1e7, 1e8],
        trace_order=["S11", "S21"],
        source="Example laboratory uncertainty evaluation",
        setup="Example held capture with matched calibration and reference planes",
    )
    envelope = measured.to_measurement_result().envelope
    assert envelope["uncertainty_status"] == "externally_evaluated"
    assert envelope["vna"]["context"]["evidence"] == "held_readback"
    assert not envelope["vna"]["fresh"]
    assert exchanges == before
