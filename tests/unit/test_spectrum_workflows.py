"""Model-specific manual-derived spectrum workflows; no instrument I/O."""

from collections import deque
from typing import cast

import pytest

from pytestlab import Bench
from pytestlab.config.loader import load_device_profile
from pytestlab.config.spectrum_analyzer_config import SpectrumAnalyzerConfig
from pytestlab.devices import register_backend
from pytestlab.devices import registry
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.instruments.backends.replay_backend import ReplayBackend
from pytestlab.instruments.SpectrumAnalyser import SpectrumAnalyser

_KEYSIGHT = "keysight/N9000A_SA"
_FSW = "rohdeschwarz/FSW26"
_OK = ("SYST:ERR?", '0,"No error"')
_INIT = ("INIT:IMM", None)
_META = [("FREQ:SPAN?", "1000"), ("SWE:POIN?", "101"), ("UNIT:POW?", '"dBmV"')]


class ScriptedSpectrum:
    def __init__(self, exchange):
        self.exchange = deque(exchange)
        self.timeout = 5000
        self.history = []
        self.operation_timeouts = []

    def connect(self):
        pass

    def disconnect(self):
        pass

    def get_timeout(self):
        return self.timeout

    def set_timeout(self, timeout):
        self.timeout = timeout

    def _exchange(self, command):
        self.history.append(command)
        self.operation_timeouts.append(self.timeout)
        expected, reply = self.exchange.popleft()
        assert command == expected
        if isinstance(reply, Exception):
            raise reply
        return reply

    def query(self, command, delay=None):
        reply = self._exchange(command)
        assert type(reply) is str
        return reply

    def write(self, command):
        assert self._exchange(command) is None


def _built(model, exchange):
    backend = ScriptedSpectrum(exchange)
    instrument = cast(SpectrumAnalyser, AutoInstrument.from_config(model, backend_override=backend))
    return instrument, backend


def _safe_source(model):
    if model == _KEYSIGHT:
        return [("INST:SOUR?", "OFF")]
    return [("*OPT?", "B3,K9,K14"), ("SYST:SEQ?", "0")]


def _mode(model):
    return ("CONF?", "SAN") if model == _KEYSIGHT else ("INST:SEL?", "'SAN'")


def _held(model):
    return [_mode(model), ("INIT:CONT?", "0"), ("FORM:DATA?", "ASC,0")]


def _key_trace_checks():
    return [
        ("CALC:NTD?", "0"),
        ("CALC:MATH? TRACE1", "OFF,TRACE2,TRACE3,0,0"),
        ("TRAC1:UPD?", "1"),
        *[(f"TRAC{n}:UPD?", "0") for n in range(2, 7)],
        ("TRAC1:TYPE?", "WRIT"),
    ]


def _until_init(model, meta=None):
    preflight = [_OK, *_held(model), *(_META if meta is None else meta), *_safe_source(model)]
    if model == _KEYSIGHT:
        return [
            *preflight,
            *_key_trace_checks(),
            _OK,
            ("DISP:VIEW NORM", None),
            *_key_trace_checks(),
            _OK,
        ]
    return [
        *preflight,
        ("SWE:COUN?", "1"),
        ("CALC:MATH:STAT?", "0"),
        ("DISP:TRAC1:MODE?", "WRIT"),
        _OK,
    ]


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
@pytest.mark.parametrize("zero_span", [False, True])
def test_configure_read_back_acquire_and_peak(model, zero_span):
    axis = tuple(
        (i * i / 1e6 - 0.001) if zero_span else (999_999_500 + i * i / 10) for i in range(101)
    )
    amplitude = tuple(-13.0 if index in (19, 51) else -60.0 for index in range(101))
    meta = [("FREQ:SPAN?", "0"), *_META[1:]] if zero_span else _META
    settings_reply = [
        _mode(model),
        ("FREQ:CENT?", "1.000000001e9"),
        meta[0],
        ("BAND?", "1100.0"),
        ("BAND:VID?", "500.0"),
        *meta[1:],
    ]
    if model == _KEYSIGHT:
        payload = [
            (
                "FETC:SAN1?",
                ",".join(str(v) for pair in zip(axis, amplitude, strict=True) for v in pair),
            )
        ]
    else:
        payload = [
            ("TRAC:DATA:X? TRACE1", ",".join(map(str, axis))),
            ("TRAC:DATA? TRACE1", ",".join(map(str, amplitude))),
        ]
    instrument, backend = _built(
        model,
        [
            _OK,
            _mode(model),
            *_safe_source(model),
            _OK,
            ("FREQ:CENT 1000000000.0", None),
            _OK,
            (f"FREQ:SPAN {0.0 if zero_span else 1000.0}", None),
            _OK,
            ("BAND 1000.0", None),
            _OK,
            ("BAND:VID 500.0", None),
            _OK,
            ("SWE:POIN 101", None),
            _OK,
            *settings_reply,
            *_until_init(model, meta),
            _INIT,
            ("*OPC?", "1"),
            _OK,
            *meta,
            *payload,
            _OK,
        ],
    )
    assert instrument.supports_operation("get_sweep_settings")
    assert instrument.supports_operation("acquire_trace")
    instrument.configure_measurement(
        1e9, 0.0 if zero_span else 1000.0, 1000.0, vbw=500.0, sweep_points=101
    )
    settings = instrument.get_sweep_settings()
    assert settings.center_freq_hz == 1_000_000_001
    assert settings.rbw_hz == 1100
    assert settings.vbw_hz == 500
    assert settings.sweep_points == 101
    settings_commands = len(backend.history)
    trace = instrument.acquire_trace(timeout_ms=1300)
    assert trace.acquisition == "fresh"
    assert trace.axis == axis
    assert trace.amplitudes == amplitude
    assert trace.axis_unit == ("s" if zero_span else "Hz")
    assert trace.amplitude_unit == "dBmV"
    peak = trace.peak()
    assert (peak.index, peak.coordinate, peak.amplitude) == (19, axis[19], -13.0)
    assert peak.axis_unit == trace.axis_unit
    assert peak.amplitude_unit == trace.amplitude_unit
    peak_measurement = peak.to_measurement_result()
    assert peak_measurement.envelope["bin_index"] == 19
    assert peak_measurement.envelope["trace"] == 1
    assert peak_measurement.envelope["source_acquisition"] == "fresh"
    assert peak_measurement.timestamp == trace.readout_timestamp
    assert peak_measurement.values.row(0) == (axis[19], -13.0)
    assert backend.history.count("INIT:IMM") == 1
    assert all(0 < ms <= 1300 for ms in backend.operation_timeouts[settings_commands:])
    assert backend.timeout == 5000
    assert not backend.exchange


@pytest.mark.parametrize(
    ("model", "first_replies", "message"),
    [
        (_KEYSIGHT, [_OK, ("CONF?", "ACP")], "standard spectrum"),
        (_KEYSIGHT, [_OK, _mode(_KEYSIGHT), ("INIT:CONT?", "1")], "continuous"),
        (_FSW, [_OK, _mode(_FSW), ("INIT:CONT?", "0"), ("FORM:DATA?", "REAL,32")], "ASCII"),
        (_KEYSIGHT, [_OK, *_held(_KEYSIGHT), *_META[:2], ("UNIT:POW?", "dB?")], "amplitude unit"),
        (_KEYSIGHT, [_OK, *_held(_KEYSIGHT), *_META, ("INST:SOUR?", "TRAC")], "source control"),
        (
            _FSW,
            [_OK, *_held(_FSW), *_META, ("*OPT?", "B3,B10"), ("SOUR:EXT:STAT?", "1")],
            "generator",
        ),
        (_FSW, [_OK, *_held(_FSW), *_META, ("*OPT?", "B3,K9"), ("SYST:SEQ?", "1")], "sequencer"),
        (_FSW, [_OK, *_held(_FSW), *_META, *_safe_source(_FSW), ("SWE:COUN?", "2")], "sweep count"),
        (_FSW, [*_until_init(_FSW)[:-2], ("DISP:TRAC1:MODE?", "VIEW")], "Clear/Write"),
        (
            _KEYSIGHT,
            [
                _OK,
                *_held(_KEYSIGHT),
                *_META,
                *_safe_source(_KEYSIGHT),
                *_key_trace_checks()[:3],
                ("TRAC2:UPD?", "1"),
                ("TRAC2:TYPE?", "AVER"),
            ],
            "active averaged",
        ),
        (
            _KEYSIGHT,
            [
                _OK,
                *_held(_KEYSIGHT),
                *_META,
                *_safe_source(_KEYSIGHT),
                *_key_trace_checks()[:2],
                ("TRAC1:UPD?", "0"),
            ],
            "not updating",
        ),
    ],
)
def test_acquisition_rejects_unsafe_or_stale_state_before_any_write(model, first_replies, message):
    instrument, backend = _built(model, first_replies)
    with pytest.raises(InstrumentDataError, match=message):
        instrument.acquire_trace()
    assert all("?" in command for command in backend.history)
    assert backend.timeout == 5000
    assert not backend.exchange


@pytest.mark.parametrize(
    ("outcome", "error", "message"),
    [
        (
            ("*OPC?", TimeoutError("trigger timeout")),
            InstrumentCommunicationError,
            "trigger timeout",
        ),
        (("*OPC?", "0"), InstrumentDataError, "completion"),
        (("SYST:ERR?", '-221,"Sweep rejected"'), InstrumentDataError, "Sweep rejected"),
    ],
)
def test_acquisition_failure_never_fetches_held_samples(outcome, error, message):
    after_init = [] if outcome[0] == "*OPC?" else [("*OPC?", "1")]
    instrument, backend = _built(_FSW, [*_until_init(_FSW), _INIT, *after_init, outcome])
    with pytest.raises(error, match=message):
        instrument.acquire_trace(timeout_ms=750)
    assert backend.history.count("INIT:IMM") == 1
    assert not any(command.startswith("TRAC:DATA") for command in backend.history)
    assert backend.timeout == 5000
    assert not backend.exchange


@pytest.mark.parametrize(
    "settings", [{"sweep_points": 100}, {"sweep_points": 101.5}, {"sweep_points": True}, {"vbw": 0}]
)
def test_invalid_configure_never_applies_earlier_requested_settings(settings):
    instrument, backend = _built(_FSW, [])
    with pytest.raises((InstrumentConfigurationError, InstrumentParameterError)):
        instrument.configure_measurement(1e9, **settings)
    assert not backend.history


def test_incomplete_acquisition_binding_rejected_without_queries_or_writes():
    config = cast(SpectrumAnalyzerConfig, load_device_profile(_KEYSIGHT))
    config.operation_options.operations["acquire_trace"].transport.pop("normal_view")
    backend = ScriptedSpectrum([])
    instrument = SpectrumAnalyser(config, backend)
    with pytest.raises(InstrumentConfigurationError, match="normal_view"):
        instrument.acquire_trace()
    assert not backend.history


@pytest.mark.parametrize("value", [0, True, 2.5, 10**100])
def test_invalid_timeout_rejected_without_queries_or_writes(value):
    instrument, backend = _built(_FSW, [])
    with pytest.raises(InstrumentConfigurationError, match="timeout_ms"):
        instrument.acquire_trace(timeout_ms=value)
    assert not backend.history


def test_configure_refuses_active_analyzer_source():
    instrument, backend = _built(_KEYSIGHT, [_OK, _mode(_KEYSIGHT), ("INST:SOUR?", "TRACKING")])
    with pytest.raises(InstrumentDataError, match="source control"):
        instrument.configure_measurement(center_freq=1e9)
    assert all("?" in command for command in backend.history)
    assert not backend.exchange


def test_single_sweep_consumes_one_timeout_budget(monkeypatch):
    import importlib

    spectrum_module = importlib.import_module("pytestlab.instruments.SpectrumAnalyser")
    instrument, backend = _built(_FSW, [*_until_init(_FSW), _INIT, ("*OPC?", "1")])
    # Simulate finishing the blocking OPC query just as the deadline passes.
    # No later query may receive a newly restarted timeout budget.
    monkeypatch.setattr(
        spectrum_module, "monotonic", lambda: 1.01 if "*OPC?" in backend.history else 1.0
    )
    with pytest.raises(InstrumentCommunicationError, match="acquisition timed out"):
        instrument.acquire_trace(timeout_ms=5)
    assert backend.history[-1] == "*OPC?"
    assert backend.timeout == 5000
    assert not backend.exchange


def _assert_session_needs_recovery(instrument, backend):
    history = list(backend.history)
    # Simulate unread bytes waiting to be taken as later replies.
    leftover = ("INST:SEL?", "SAN")
    backend.exchange.append(leftover)
    for action in (
        instrument.get_sweep_settings,
        instrument.get_trace,
        instrument.acquire_trace,
        lambda: instrument.configure_measurement(center_freq=1e9),
    ):
        with pytest.raises(InstrumentCommunicationError, match="open a new session"):
            action()
    assert backend.history == history
    assert list(backend.exchange) == [leftover]
    assert backend.timeout == 5000


@pytest.mark.parametrize(
    "failure",
    [
        [("INIT:IMM", TimeoutError("write acknowledgment lost"))],
        [_INIT, ("*OPC?", TimeoutError("completion still outstanding"))],
        [_INIT, ("*OPC?", "0")],
        [
            _INIT,
            ("*OPC?", "1"),
            _OK,
            *_META,
            ("TRAC:DATA:X? TRACE1", ",".join(map(str, range(101)))),
            ("TRAC:DATA? TRACE1", TimeoutError("payload still outstanding")),
        ],
    ],
)
def test_uncertain_sweep_quarantines_connection_until_manual_recovery(failure):
    instrument, backend = _built(_FSW, [*_until_init(_FSW), *failure])
    with pytest.raises((InstrumentCommunicationError, InstrumentDataError)):
        instrument.acquire_trace()
    _assert_session_needs_recovery(instrument, backend)


def test_held_read_timeout_also_quarantines_the_connection():
    instrument, backend = _built(
        _FSW, [_mode(_FSW), ("INIT:CONT?", "0"), ("*OPC?", TimeoutError("held timeout"))]
    )
    with pytest.raises(InstrumentCommunicationError, match="held timeout"):
        instrument.get_trace()
    _assert_session_needs_recovery(instrument, backend)


def test_final_reply_from_backend_returning_after_deadline_is_not_accepted(monkeypatch):
    import importlib

    spectrum_module = importlib.import_module("pytestlab.instruments.SpectrumAnalyser")
    instrument, backend = _built(
        _FSW,
        [
            *_until_init(_FSW),
            _INIT,
            ("*OPC?", "1"),
            _OK,
            *_META,
            ("TRAC:DATA:X? TRACE1", ",".join(map(str, range(101)))),
            ("TRAC:DATA? TRACE1", ",".join(["-40.0"] * 101)),
            _OK,
        ],
    )
    monkeypatch.setattr(
        spectrum_module,
        "monotonic",
        lambda: 1.0 if backend.exchange else 1.02,
    )
    with pytest.raises(InstrumentCommunicationError, match="acquisition timed out"):
        instrument.acquire_trace(timeout_ms=5)
    assert backend.history[-2:] == ["TRAC:DATA? TRACE1", "SYST:ERR?"]
    _assert_session_needs_recovery(instrument, backend)


def _setup(model):
    return [_OK, _mode(model), *_safe_source(model), _OK]


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_rf_input_preamplifier_option_and_readback(model):
    key = model == _KEYSIGHT
    ref = "DISP:WIND:TRAC:Y:RLEV" if key else "DISP:TRAC:Y:RLEV"
    att = "POW:ATT" if key else "INP:ATT"
    preamp = "POW:GAIN:STAT" if key else "INP:GAIN:STAT"
    options = ("*OPT?", "503,P03" if key else "B3,B24")
    unit = ("UNIT:POW?", "DBM")
    sa, backend = _built(
        model,
        [
            *_setup(model),
            unit,
            options,
            _OK,
            (f"{att} 22", None),
            _OK,
            (f"{ref} -17DBM", None),
            _OK,
            (f"{preamp} ON", None),
            _OK,
            _mode(model),
            unit,
            options,
            (f"{ref}?", "-16.5"),
            (f"{att}?", "25"),
            (f"{att}:AUTO?", "0"),
            (f"{preamp}?", "1"),
            _OK,
            *_setup(model),
            ("*OPT?", "503" if key else "B3"),
        ],
    )
    assert sa.supports_operation("configure_rf_input")
    sa.configure_rf_input(reference_level_dbm=-17, attenuation_db=22, preamp=True)
    state = sa.get_rf_input()
    assert (
        state.reference_level_dbm,
        state.attenuation_db,
        state.attenuation_auto,
        state.preamp,
    ) == (-16.5, 25.0, False, True)
    with pytest.raises(InstrumentConfigurationError, match="preamp option"):
        sa.configure_rf_input(preamp=True)
    assert not backend.exchange


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_configure_zero_span_control_and_read_actual_time(model):
    key = model == _KEYSIGHT
    ext = "EXT1" if key else "EXT"
    sa, backend = _built(
        model,
        [
            *_setup(model),
            ("FREQ:SPAN?", "0"),
            ("INIT:CONT OFF", None),
            _OK,
            (f"TRIG:SOUR {ext}", None),
            _OK,
            ("SWE:TIME 0.002", None),
            _OK,
            _mode(model),
            ("FREQ:SPAN?", "0"),
            ("SWE:TIME?", "0.00205"),
            *([] if key else [("SWE:TIME:AUTO?", "0")]),
            ("TRIG:SOUR?", "EXT1" if key else "EXTERNAL"),
            ("INIT:CONT?", "0"),
            _OK,
        ],
    )
    sa.configure_sweep_control(sweep_time_s=0.002, trigger_source="external_1", continuous=False)
    state = sa.get_sweep_control()
    assert state.sweep_time_s == pytest.approx(0.00205)
    assert state.sweep_time_auto is (None if key else False)
    assert state.trigger_source == "external_1"
    assert not state.continuous
    assert not backend.exchange


def test_keysight_fft_refuses_sweep_time_write():
    sa, backend = _built(
        _KEYSIGHT, [*_setup(_KEYSIGHT), ("FREQ:SPAN?", "1000"), ("SWE:TYPE?", "FFT")]
    )
    with pytest.raises(InstrumentConfigurationError, match="manual timing"):
        sa.configure_sweep_control(sweep_time_s=1)
    assert not backend.exchange


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_native_trace_setup_readback_and_fresh_accumulation(model):
    key = model == _KEYSIGHT
    tt = "TRAC1:TYPE" if key else "DISP:TRAC1:MODE"
    det = "DET:TRAC1" if key else "DET1"
    count = "AVER:COUN" if key else "SWE:COUN"
    update = "TRAC1:UPD?" if key else "DISP:TRAC1:STAT?"
    mode = "AVER" if key else "MAXH"
    semantic = "average" if key else "max_hold"
    state = [(f"{tt}?", mode), (f"{count}?", "4")]
    if key:
        guard = _key_trace_checks()[:-1]
        acquisition_setup = [
            *guard,
            *state,
            _OK,
            ("DISP:VIEW NORM", None),
            *guard,
            *state,
            _OK,
        ]
        payload = [("FETC:SAN1?", ",".join(f"{n},-21" for n in range(101)))]
    else:
        acquisition_setup = [("CALC:MATH:STAT?", "0"), *state, _OK]
        payload = [
            ("TRAC:DATA:X? TRACE1", ",".join(map(str, range(101)))),
            ("TRAC:DATA? TRACE1", ",".join(["-21"] * 101)),
        ]
    sa, backend = _built(
        model,
        [
            *_setup(model),
            (f"{count} 4", None),
            _OK,
            (f"{tt} {mode}", None),
            _OK,
            (f"{det}:AUTO OFF", None),
            _OK,
            (f"{det} SAMP", None),
            _OK,
            _mode(model),
            (f"{tt}?", mode),
            (f"{det}?", "SAMP"),
            (f"{det}:AUTO?", "0"),
            (f"{count}?", "4"),
            (update, "1"),
            _OK,
            _OK,
            *_held(model),
            *_META,
            *_safe_source(model),
            *acquisition_setup,
            _INIT,
            ("*OPC?", "1"),
            _OK,
            *_META,
            *payload,
            _OK,
        ],
    )
    sa.configure_trace(
        1, mode=semantic, detector="sample", detector_auto=False, accumulation_count=4
    )
    state = sa.get_trace_settings()
    assert (
        state.mode,
        state.detector,
        state.detector_auto,
        state.accumulation_count,
        state.updating,
    ) == (semantic, "sample", False, 4, True)
    trace = sa.acquire_trace(accumulation_count=4)
    assert trace.acquisition == "fresh"
    assert trace.sweep_count == 4
    assert trace.trace_mode == semantic
    assert trace.peak().amplitude == -21
    assert backend.history.count("INIT:IMM") == 1
    assert not backend.exchange


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_native_count_mismatch_does_not_initiate(model):
    key = model == _KEYSIGHT
    guard = _key_trace_checks()[:-1] if key else [("CALC:MATH:STAT?", "0")]
    mode = "TRAC1:TYPE?" if key else "DISP:TRAC1:MODE?"
    count = "AVER:COUN?" if key else "SWE:COUN?"
    sa, backend = _built(
        model,
        [_OK, *_held(model), *_META, *_safe_source(model), *guard, (mode, "MINH"), (count, "9")],
    )
    with pytest.raises(InstrumentDataError, match="does not match"):
        sa.acquire_trace(accumulation_count=8)
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange


def _marker_guard(model, *, channel=1):
    held = [
        _OK,
        _mode(model),
        ("INIT:CONT?", "0"),
        ("*OPC?", "1"),
        ("FREQ:SPAN?", "2000000"),
        ("UNIT:POW?", "DBM"),
    ]
    if model == _KEYSIGHT:
        active = [(f"TRAC{channel}:UPD?", "1"), (f"TRAC{channel}:TYPE?", "WRIT")]
        return [*held, *active, _OK, ("DISP:VIEW NORM", None), _OK, held[-2], *active, _OK]
    return [*held, ("DISP:TRAC:Y:SPAC?", "LOG"), _OK]


def _marker_setup(model, marker, channel):
    prefix = f"CALC:MARK{marker}"
    if model == _KEYSIGHT:
        return [
            (f"{prefix}:MODE POS", None),
            _OK,
            (f"{prefix}:TRAC {channel}", None),
            _OK,
            (f"{prefix}:FUNC OFF", None),
            _OK,
            (f"{prefix}:X:READ FREQ", None),
            _OK,
        ]
    return [(f"{prefix} ON", None), _OK, (f"{prefix}:TRAC {channel}", None), _OK]


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_held_marker_search_next_and_measured_delta(model):
    sa, backend = _built(
        model,
        [
            *_marker_guard(model),
            *_marker_setup(model, 1, 1),
            ("CALC:MARK1:MAX", None),
            _OK,
            ("CALC:MARK1:X?", "1000000001"),
            ("CALC:MARK1:Y?", "-21.5"),
            _OK,
            *_marker_guard(model),
            *_marker_setup(model, 1, 1),
            ("CALC:MARK1:X?", "1000000001"),
            ("CALC:MARK1:MAX:NEXT", None),
            _OK,
            ("CALC:MARK1:X?", "1000000101"),
            ("CALC:MARK1:Y?", "-36.5"),
            _OK,
            *_marker_guard(model),
            *_marker_setup(model, 3, 1),
            ("CALC:MARK3:X 1000000000.0HZ", None),
            _OK,
            ("CALC:MARK3:X?", "1000000001"),
            ("CALC:MARK3:Y?", "-21.5"),
            _OK,
            *_marker_setup(model, 4, 1),
            ("CALC:MARK4:X 1000000100.0HZ", None),
            _OK,
            ("CALC:MARK4:X?", "1000000101"),
            ("CALC:MARK4:Y?", "-36.5"),
            _OK,
        ],
    )
    first = sa.find_marker_peak()
    second = sa.find_marker_peak(next_peak=True)
    assert first.frequency_hz < second.frequency_hz
    delta = sa.measure_marker_delta(1e9, 1e9 + 100, reference_marker=3, marker=4)
    assert delta.frequency_delta_hz == 100
    assert delta.amplitude_delta_db == -15
    assert delta.reference.marker == 3
    marker = first.to_measurement_result()
    assert marker.values.row(0) == (1000000001.0, -21.5)
    assert marker.envelope["acquisition"] == "held"
    delta_measurement = delta.to_measurement_result()
    assert delta_measurement.values.row(0) == (
        1000000001.0,
        1000000101.0,
        100.0,
        -21.5,
        -36.5,
        -15.0,
    )
    assert delta_measurement.envelope["acquisition"] == "derived"
    assert delta_measurement.envelope["source_acquisition"] == "held"
    assert delta_measurement.envelope["column_units"]["amplitude_delta_db"] == "dB"
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange


def test_spectrum_setup_rejects_bad_arguments_before_commands():
    sa, backend = _built(_KEYSIGHT, [])
    with pytest.raises(InstrumentConfigurationError, match="mutually exclusive"):
        sa.configure_rf_input(attenuation_db=30, attenuation_auto=True)
    with pytest.raises(InstrumentConfigurationError, match="Choose"):
        sa.configure_trace(detector="sample", detector_auto=True)
    with pytest.raises(InstrumentParameterError):
        sa.configure_trace(7, mode="average")
    with pytest.raises(InstrumentParameterError):
        sa.configure_rf_input(reference_level_dbm=-20, attenuation_db=float("nan"))
    assert not backend.history


def _native_measurement_guard(model, power):
    if model == _KEYSIGHT:
        suffix = "CHP" if power else "OBW"
        return [
            _OK,
            ("CONF?", suffix),
            ("INST:NSEL?", "1"),
            (f"{suffix}:AVER:STAT?", "0"),
            ("INIT:CONT?", "0"),
            *_safe_source(model),
            _OK,
        ]
    return [
        _OK,
        _mode(model),
        ("FREQ:SPAN?", "1e6"),
        ("INIT:CONT?", "0"),
        *_safe_source(model),
        _OK,
        ("CALC:MARK:FUNC:POW:SEL " + ("CPOW" if power else "OBW"), None),
        _OK,
        _mode(model),
        *_safe_source(model),
        ("INIT:CONT?", "0"),
        ("SWE:COUN?", "1"),
        ("CALC:MATH:STAT?", "0"),
        ("DISP:TRAC1:MODE?", "WRIT"),
        ("DISP:TRAC1:STAT?", "1"),
    ]


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
@pytest.mark.parametrize("power", [True, False])
def test_native_scalar_measurement_reads_back_actual_settings_and_waits(model, power):
    key = model == _KEYSIGHT
    suffix = "CHP" if power else "OBW"
    guard = _native_measurement_guard(model, power)
    if power and not key:
        guard += [
            ("UNIT:POW?", "DBM"),
            ("DISP:TRAC:Y:SPAC?", "LOG"),
            ("POW:ACH:TXCH:COUN?", "1"),
            ("CALC:MARK:FUNC:POW:MODE?", "WRIT"),
            ("POW:TRAC 1", None),
            _OK,
        ]
    if not key and not power:
        guard += [("CALC:MARK1:TRAC 1", None), _OK]
    setting = (
        ("CHP:BAND:INT" if key else "POW:ACH:BAND:CHAN1")
        if power
        else ("OBW:PERC" if key else "POW:BWID")
    )
    parameter = "100000.0" if power else ("98" if key else "98PCT")
    actual = "100023" if power else "98.1"
    result = "-17.5" if power else "159.5"
    init = f"INIT:{suffix}" if key else "INIT:IMM"
    fetch = (
        f"FETC:{suffix}:{suffix}?"
        if key
        else "CALC:MARK:FUNC:POW:RES? " + ("CPOW" if power else "OBW")
    )
    sa, backend = _built(
        model,
        [
            *guard,
            (f"{setting} {parameter}", None),
            _OK,
            (f"{setting}?", actual),
            *([("CALC:MARK:FUNC:POW:RES:PHZ?", "0")] if power and not key else []),
            _OK,
            (init, None),
            ("*OPC?", "1"),
            *([("CALC:MARK:FUNC:POW:RES:PHZ?", "0")] if power and not key else []),
            _OK,
            (fetch, result),
            _OK,
            *([] if key else [("CALC:MARK:FUNC:POW:STAT OFF", None), _OK]),
        ],
    )
    if power:
        cp = sa.measure_channel_power(bandwidth_hz=1e5, timeout_ms=1200)
        assert cp.power_dbm == -17.5
        assert cp.bandwidth_hz == 100023
        measurement = cp.to_measurement_result()
        assert (float(measurement.values), measurement.units) == (-17.5, "dBm")
        assert measurement.envelope["bandwidth_hz"] == 100023
    else:
        obw = sa.measure_occupied_bandwidth(power_percent=98, timeout_ms=1200)
        assert obw.bandwidth_hz == 159.5
        assert obw.power_percent == 98.1
        measurement = obw.to_measurement_result()
        assert (float(measurement.values), measurement.units) == (159.5, "Hz")
        assert measurement.envelope["power_percent"] == 98.1
    assert measurement.envelope["acquisition"] == "fresh"
    assert measurement.envelope["timestamp_kind"] == "host_receipt"
    assert measurement.envelope["uncertainty_status"] == "not_evaluated"
    assert backend.history.count(init) == 1
    assert all(0 < ms <= 1200 for ms in backend.operation_timeouts)
    assert not backend.exchange


def test_native_result_does_not_fetch_when_completion_unconfirmed():
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_native_measurement_guard(_KEYSIGHT, False),
            ("OBW:PERC?", "99"),
            _OK,
            ("INIT:OBW", None),
            ("*OPC?", "0"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="completion"):
        sa.measure_occupied_bandwidth()
    with pytest.raises(InstrumentCommunicationError, match="uncertain"):
        sa.get_sweep_settings()
    assert not backend.exchange


def test_fsw_channel_power_rejects_linear_scale_before_sweep():
    sa, backend = _built(
        _FSW,
        [
            *_native_measurement_guard(_FSW, True),
            ("UNIT:POW?", "DBM"),
            ("DISP:TRAC:Y:SPAC?", "LIN"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="logarithmic"):
        sa.measure_channel_power()
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange


def test_fsw_external_frontend_refuses_internal_input_write():
    sa, backend = _built(_FSW, [*_setup(_FSW), ("*OPT?", "B3,K553"), ("EFR?", "1")])
    with pytest.raises(InstrumentDataError, match="external RF frontend"):
        sa.configure_rf_input(attenuation_db=20)
    assert not backend.exchange


@pytest.mark.parametrize("after_init", [False, True])
def test_fsw_channel_power_never_reads_density_as_dbm(after_init):
    before_density = [
        *_native_measurement_guard(_FSW, True),
        ("UNIT:POW?", "DBM"),
        ("DISP:TRAC:Y:SPAC?", "LOG"),
        ("POW:ACH:TXCH:COUN?", "1"),
        ("CALC:MARK:FUNC:POW:MODE?", "WRIT"),
        ("POW:TRAC 1", None),
        _OK,
        ("POW:ACH:BAND:CHAN1?", "100000"),
    ]
    density = "CALC:MARK:FUNC:POW:RES:PHZ?"
    if after_init:
        before_density += [(density, "0"), _OK, _INIT, ("*OPC?", "1")]
    sa, backend = _built(_FSW, [*before_density, (density, "1")])
    with pytest.raises(InstrumentDataError, match="power density"):
        sa.measure_channel_power()
    assert ("INIT:IMM" in backend.history) is after_init
    assert "CALC:MARK:FUNC:POW:RES? CPOW" not in backend.history
    assert not backend.exchange


@pytest.mark.parametrize("failure", ["frozen", "span_after_view"])
def test_keysight_marker_rejects_ambiguous_trace_domain(failure):
    # Trace 2 can be frozen in a previous zero span despite the current swept span.
    preflight = _marker_guard(_KEYSIGHT, channel=2)
    if failure == "frozen":
        preflight = [*preflight[:6], ("TRAC2:UPD?", "0")]
        message = "updating Clear/Write"
    else:
        preflight = [*preflight[:11], ("FREQ:SPAN?", "0")]
        message = "non-zero span"
    sa, backend = _built(_KEYSIGHT, preflight)
    with pytest.raises(InstrumentDataError, match=message):
        sa.set_marker(1e9, channel=2)
    assert not any(command.startswith("CALC:MARK") for command in backend.history)
    assert not backend.exchange


@pytest.mark.parametrize(("mode", "enabled"), [("VIEW", "1"), ("BLAN", "0")])
def test_fsw_frozen_or_blank_trace_is_not_updating(mode, enabled):
    sa, backend = _built(
        _FSW,
        [
            _mode(_FSW),
            ("DISP:TRAC2:MODE?", mode),
            ("DET2?", "SAMP"),
            ("DET2:AUTO?", "0"),
            ("SWE:COUN?", "1"),
            ("DISP:TRAC2:STAT?", enabled),
            _OK,
        ],
    )
    state = sa.get_trace_settings(2)
    assert state.mode == ("view" if mode == "VIEW" else "blank")
    assert state.updating is False
    assert not backend.exchange


_ACP_RESULT_QUERY = "FETC:ACP?"


def _acp_guard():
    return [
        _OK,
        ("CONF?", "ACP"),
        ("INST:NSEL?", "1"),
        ("INIT:CONT?", "0"),
        *_safe_source(_KEYSIGHT),
        _OK,
    ]


def _acp_mode():
    return [
        ("ACP:CARR:COUN?", "1"),
        ("RAD:STAN?", "NONE"),
        ("ACP:TYPE?", "TPR"),
        ("ACP:CARR:PREF:TYPE?", "RCAR"),
        ("ACP:METH?", "IBW"),
        ("ACP:OFFS:TYPE?", "CTOC"),
        ("ACP:OFFS:LIST:STAT?", "1,0,0,0,0,0"),
        ("ACP:OFFS:LIST:SIDE?", "BOTH,BOTH,BOTH,BOTH,BOTH,BOTH"),
        ("ACP:AVER:STAT?", "0"),
    ]


def _acp_geometry(adjacent="180000"):
    return [
        ("ACP:CARR:LIST:BAND:INT?", "150000"),
        ("ACP:OFFS:LIST:BAND:INT?", adjacent + ",200000,200000,200000,200000,200000"),
        ("ACP:OFFS:LIST:FREQ?", "300000,0,0,0,0,0"),
    ]


def _acp_before_initiate():
    return [("ACP:FREQ:SPAN?", "800000"), _OK]


def _acp_initiate():
    return [("INIT:ACP", None), ("*OPC?", "1")]


def test_native_adjacent_power_normalizes_radio_results_with_readback():
    set_adjacent = "ACP:OFFS:LIST:BAND:INT"
    payload = "-5,-38,-41"
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_acp_guard(),
            *_acp_mode(),
            *_acp_geometry(),
            _OK,
            (f"{set_adjacent} 175000", None),
            _OK,
            *_acp_mode(),
            *_acp_geometry("174999"),
            *_acp_before_initiate(),
            *_acp_initiate(),
            *_acp_mode(),
            _OK,
            (_ACP_RESULT_QUERY, payload),
            _OK,
        ],
    )
    assert sa.supports_operation("measure_adjacent_channel_power")
    result = sa.measure_adjacent_channel_power(adjacent_bandwidth_hz=175000, timeout_ms=1200)
    assert (
        result.carrier_power_dbm,
        result.lower_power_dbm,
        result.upper_power_dbm,
        result.lower_relative_dbc,
        result.upper_relative_dbc,
    ) == (-5, -43, -46, -38, -41)
    measurement = result.to_measurement_result()
    assert measurement.values.rows() == [
        ("carrier", None, 0.0, result.carrier_bandwidth_hz, -5.0, None),
        ("lower", 1, -result.spacing_hz, 174999.0, -43.0, -38.0),
        ("upper", 1, result.spacing_hz, 174999.0, -46.0, -41.0),
    ]
    assert (
        measurement.envelope["adjacent_power_source"] == "derived_from_carrier_and_relative_power"
    )
    assert (
        result.carrier_bandwidth_hz,
        result.adjacent_bandwidth_hz,
        result.spacing_hz,
    ) == (150000, 174999, 300000)
    assert all(0 < timeout <= 1200 for timeout in backend.operation_timeouts)
    assert not backend.exchange


@pytest.mark.parametrize(
    ("mode_end", "changed", "message"),
    [
        (2, ("ACP:TYPE?", "PSDR"), "Total Power Ref"),
        (6, ("ACP:OFFS:LIST:STAT?", "1,1,0,0,0,0"), "only Keysight ACP offset A"),
    ],
)
def test_native_adjacent_power_rejects_ambiguous_mode_before_sweep(mode_end, changed, message):
    sa, backend = _built(_KEYSIGHT, [*_acp_guard(), *_acp_mode()[:mode_end], changed])
    with pytest.raises(InstrumentDataError, match=message):
        sa.measure_adjacent_channel_power()
    assert not any(
        command.startswith("INIT:ACP") or command == "INIT:IMM" for command in backend.history
    )
    assert not backend.exchange


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ("-30,-999,-34", "did not return all three"),
        ("-30,-42,-45,-74,-76", "Expected 3 values"),
    ],
)
def test_native_adjacent_power_rejects_invalid_result_shape_and_sentinel(result, message):
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_acp_guard(),
            *_acp_mode(),
            *_acp_geometry(),
            *_acp_before_initiate(),
            *_acp_initiate(),
            *_acp_mode(),
            _OK,
            (_ACP_RESULT_QUERY, result),
            _OK,
        ],
    )
    with pytest.raises(InstrumentDataError, match=message):
        sa.measure_adjacent_channel_power()
    assert not backend.exchange


def test_native_adjacent_power_rejects_overlapping_requested_channels_before_writes():
    sa, backend = _built(
        _KEYSIGHT,
        [*_acp_guard(), *_acp_mode(), *_acp_geometry()],
    )
    with pytest.raises(InstrumentDataError, match="passbands overlap"):
        sa.measure_adjacent_channel_power(spacing_hz=150000)
    assert not backend.exchange


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_external_trigger_configures_input_threshold_edge_and_reads_actual(model):
    key = model == _KEYSIGHT
    source = "external_1" if key else "external_3"
    native_source = "EXT1" if key else "EXT3"
    level = "TRIG:EXT1:LEV" if key else "TRIG:LEV:EXT3"
    edge = "TRIG:EXT1:SLOP" if key else "TRIG:SLOP"
    direction = [] if key else [("OUTP:TRIG3:DIR?", "INP")]
    sa, backend = _built(
        model,
        [
            *_setup(model),
            ("INIT:CONT?", "0"),
            *direction,
            _OK,
            (f"TRIG:SOUR {native_source}", None),
            _OK,
            (f"{level} 1.5", None),
            _OK,
            (f"{edge} NEG", None),
            _OK,
            _mode(model),
            *direction,
            ("TRIG:SOUR?", native_source),
            (f"{level}?", "1.52"),
            (f"{edge}?", "NEGATIVE"),
            _OK,
        ],
    )
    sa.configure_external_trigger(source, level_v=1.5, slope="falling")
    state = sa.get_external_trigger_settings(source)
    assert state.source == source
    assert state.level_v == 1.52
    assert state.slope == "falling" and state.active
    assert not backend.exchange


@pytest.mark.parametrize("source", ["external_3", "EXTERNAL3"])
def test_fsw_external_trigger_refuses_output_direction_without_writes(source):
    sa, backend = _built(
        _FSW,
        [
            *_setup(_FSW),
            ("INIT:CONT?", "0"),
            ("OUTP:TRIG2:DIR?", "OUT"),
            *_setup(_FSW),
            ("OUTP:TRIG3:DIR?", "OUTP"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="connector to Input"):
        sa.configure_external_trigger("external_2", level_v=1.5)
    with pytest.raises(InstrumentDataError, match="connector to Input"):
        sa.configure_sweep_control(trigger_source=source)
    assert all(command.endswith("?") for command in backend.history)
    assert not backend.exchange


def test_n9000a_trigger_2_is_not_advertised_or_sent():
    sa, backend = _built(_KEYSIGHT, [])
    options = sa.list_operation_options("configure_sweep_control", "trigger_source")
    assert "external_1" in {option["value"] for option in options}
    assert "external_2" not in {option["value"] for option in options}
    with pytest.raises(InstrumentParameterError):
        sa.configure_sweep_control(trigger_source="external_2")
    with pytest.raises(InstrumentParameterError):
        sa.configure_external_trigger("external_2")
    assert not backend.history


def test_fsw_trigger_readback_does_not_assign_active_edge_to_inactive_port():
    sa, backend = _built(
        _FSW,
        [
            _mode(_FSW),
            ("OUTP:TRIG2:DIR?", "INPUT"),
            ("TRIG:SOUR?", "IMM"),
            ("TRIG:LEV:EXT2?", "1.4"),
            _OK,
        ],
    )
    state = sa.get_external_trigger_settings("external_2")
    assert not state.active and state.slope is None and state.level_v == 1.4
    assert not backend.exchange


def test_fsw_native_channel_power_requires_an_active_trace_before_initiating():
    preflight = _native_measurement_guard(_FSW, True)
    active = preflight.index(("DISP:TRAC1:STAT?", "1"))
    sa, backend = _built(_FSW, [*preflight[:active], ("DISP:TRAC1:STAT?", "0")])
    with pytest.raises(InstrumentDataError, match="active FSW Trace 1"):
        sa.measure_channel_power()
    with pytest.raises(InstrumentCommunicationError, match="uncertain"):
        sa.get_trace()
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange


def test_fsw_native_channel_power_quarantines_post_selection_mode_rejection():
    sa, backend = _built(
        _FSW,
        [*_native_measurement_guard(_FSW, True), ("UNIT:POW?", "DBUV")],
    )
    with pytest.raises(InstrumentDataError, match="dBm"):
        sa.measure_channel_power()
    with pytest.raises(InstrumentCommunicationError, match="uncertain"):
        sa.acquire_trace()
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange


def _multi_acp_initiate():
    return [*_acp_initiate(), ("CONF?", "ACP"), ("INST:NSEL?", "1")]


def _multi_acp_mode(count):
    mode = _acp_mode()
    mode[6] = ("ACP:OFFS:LIST:STAT?", ",".join(["1"] * count + ["0"] * (6 - count)))
    return mode


def _multi_acp_mode_and_geometry(count, *, second_spacing=600_000):
    widths = [175_000 + 5_000 * index for index in range(count)]
    spacings = [300_000, second_spacing, *(300_000 * index for index in range(3, count + 1))]
    return [
        *_multi_acp_mode(count),
        ("ACP:CARR:LIST:BAND:INT?", "150000"),
        ("ACP:OFFS:LIST:BAND:INT?", ",".join(map(str, widths + [0] * (6 - count)))),
        ("ACP:OFFS:LIST:FREQ?", ",".join(map(str, spacings + [0] * (6 - count)))),
    ]


_MULTI_ACP_SPAN = ("ACP:FREQ:SPAN?", "8000000")


def _keysight_acp_table(count, *, active_missing=False):
    carrier = -6
    groups = [
        (-24 - index, carrier - 24 - index, -31 - index, carrier - 31 - index)
        for index in range(count)
    ]
    if active_missing:
        groups[-1] = (-999, -999, *groups[-1][2:])
    return ",".join(
        map(
            str,
            [
                0,
                carrier,
                0,
                carrier,
                *(value for group in groups for value in group),
                *[-999] * (4 * (6 - count)),
            ],
        )
    )


@pytest.mark.parametrize("count", [2, 6])
def test_native_multiple_adjacent_pairs_keep_absolute_relative_and_geometry(count):
    state = _multi_acp_mode_and_geometry(count)
    payload = _keysight_acp_table(count)
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_acp_guard(),
            *state,
            _MULTI_ACP_SPAN,
            _OK,
            *_multi_acp_initiate(),
            *state,
            _OK,
            (_ACP_RESULT_QUERY, payload),
            _OK,
        ],
    )
    assert sa.supports_operation("measure_adjacent_channel_pairs")
    assert (
        sa.describe_operation("measure_adjacent_channel_pairs")["parameters"]["pair_count"][
            "constraints"
        ]["max"]
        == 6
    )
    result = sa.measure_adjacent_channel_pairs(count, timeout_ms=2_000)
    assert result.carrier_power_dbm == -6 and result.carrier_bandwidth_hz == 150_000
    assert len(result.pairs) == count
    for i, pair in enumerate(result.pairs):
        assert (pair.pair, pair.spacing_hz, pair.bandwidth_hz) == (
            i + 1,
            300_000 * (i + 1),
            175_000 + 5_000 * i,
        )
        assert (pair.lower_power_dbm, pair.upper_power_dbm) == (-30 - i, -37 - i)
        assert (pair.lower_relative_dbc, pair.upper_relative_dbc) == (-24 - i, -31 - i)
    measurement = result.to_measurement_result()
    assert measurement.values.height == 1 + 2 * count
    assert measurement.values["offset_hz"].to_list() == [
        0.0,
        *(offset for pair in result.pairs for offset in (-pair.spacing_hz, pair.spacing_hz)),
    ]
    assert measurement.values["relative_power_dbc"][0] is None
    assert measurement.envelope["column_units"]["relative_power_dbc"] == "dBc"
    assert measurement.envelope["adjacent_power_source"] == "instrument"
    assert not backend.exchange


def test_native_multiple_adjacent_pairs_enforces_model_bound_before_io():
    sa, backend = _built(_KEYSIGHT, [])
    with pytest.raises(InstrumentParameterError):
        sa.measure_adjacent_channel_pairs(7)
    assert not backend.history


def test_keysight_multiple_adjacent_pairs_rejects_gaps_before_initiate():
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_acp_guard(),
            *_multi_acp_mode(2)[:6],
            ("ACP:OFFS:LIST:STAT?", "1,0,1,0,0,0"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="with no gaps"):
        sa.measure_adjacent_channel_pairs(2)
    assert "INIT:ACP" not in backend.history
    assert not backend.exchange


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("-6,-24,-31", "Expected 28 values"),
        (_keysight_acp_table(2, active_missing=True), "all active"),
    ],
)
def test_native_multiple_adjacent_pairs_rejects_bad_array_or_missing_active_power(payload, message):
    state = _multi_acp_mode_and_geometry(2)
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_acp_guard(),
            *state,
            _MULTI_ACP_SPAN,
            _OK,
            *_multi_acp_initiate(),
            *state,
            _OK,
            (_ACP_RESULT_QUERY, payload),
            _OK,
        ],
    )
    with pytest.raises(InstrumentDataError, match=message):
        sa.measure_adjacent_channel_pairs(2)
    assert not backend.exchange


def test_keysight_multiple_adjacent_pairs_rejects_changed_geometry_before_fetch():
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_acp_guard(),
            *_multi_acp_mode_and_geometry(2),
            _MULTI_ACP_SPAN,
            _OK,
            *_multi_acp_initiate(),
            *_multi_acp_mode_and_geometry(2, second_spacing=700_000),
        ],
    )
    with pytest.raises(InstrumentDataError, match="geometry changed"):
        sa.measure_adjacent_channel_pairs(2)
    assert _ACP_RESULT_QUERY not in backend.history
    assert not backend.exchange


def test_keysight_multiple_adjacent_pairs_rejects_overlapping_geometry_before_initiate():
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_acp_guard(),
            *_multi_acp_mode_and_geometry(2, second_spacing=400_000),
        ],
    )
    with pytest.raises(InstrumentDataError, match="alternate passbands overlap"):
        sa.measure_adjacent_channel_pairs(2)
    assert "INIT:ACP" not in backend.history
    assert not backend.exchange


def test_fsw_acp_is_neither_advertised_nor_sent_without_verified_symmetric_layout():
    sa, backend = _built(_FSW, [])
    assert not sa.supports_operation("measure_adjacent_channel_power")
    assert not sa.supports_operation("measure_adjacent_channel_pairs")
    with pytest.raises(InstrumentConfigurationError):
        sa.measure_adjacent_channel_power()
    with pytest.raises(InstrumentConfigurationError):
        sa.measure_adjacent_channel_pairs(2)
    assert not backend.history


def _frame_selected(model, channels):
    if model == _KEYSIGHT:
        return [
            ("CALC:NTD?", "0"),
            *[
                setting
                for channel in channels
                for setting in (
                    (f"CALC:MATH? TRACE{channel}", "OFF,TRACE2,TRACE3,0,0"),
                    (f"TRAC{channel}:UPD?", "1"),
                )
            ],
            *[(f"TRAC{channel}:UPD?", "0") for channel in range(1, 7) if channel not in channels],
            *[(f"TRAC{channel}:TYPE?", "WRIT") for channel in channels],
        ]
    return [
        *[(f"DISP:TRAC{channel}:STAT?", "1") for channel in channels],
        *[(f"DISP:TRAC{channel}:MODE?", "WRIT") for channel in channels],
    ]


def _frame_state(model, meta):
    if model == _KEYSIGHT:
        return [*_held(model), *meta]
    return [
        _mode(model),
        ("INST:MODE?", "SAN"),
        ("LAY:CAT?", "'Spectrum, main',1"),
        ("LAY:WIND1:TYPE?", "DIAG"),
        *_held(model)[1:],
        *meta,
    ]


def _frame_before_initiate(model, channels, meta):
    selected = _frame_selected(model, channels)
    pre = [_OK, *_frame_state(model, meta), *_safe_source(model)]
    if model == _KEYSIGHT:
        return [*pre, *selected, _OK, ("DISP:VIEW NORM", None), *selected, _OK]
    return [*pre, ("SWE:COUN?", "1"), ("CALC:MATH:STAT?", "0"), *selected, _OK]


def _frame_after_initiate(model, channels, meta):
    selected = _frame_selected(model, channels)
    if model == _FSW:
        selected.insert(len(channels), ("CALC:MATH:STAT?", "0"))
    return [_INIT, ("*OPC?", "1"), _OK, *_frame_state(model, meta), *selected, _OK]


def _frame_payload(model, channel, axis, level):
    if model == _KEYSIGHT:
        return [(f"FETC:SAN{channel}?", ",".join(f"{x},{level}" for x in axis))]
    return [
        (f"TRAC:DATA:X? TRACE{channel}", ",".join(map(str, axis))),
        (f"TRAC:DATA? TRACE{channel}", ",".join([str(level)] * len(axis))),
    ]


@pytest.mark.parametrize(("model", "zero_span"), [(_KEYSIGHT, False), (_FSW, True)])
def test_synchronized_spectrum_frame_captures_selected_traces_in_one_sweep(model, zero_span):
    channels = (2, 1)
    meta = [("FREQ:SPAN?", "0"), *_META[1:]] if zero_span else _META
    axis = (
        tuple(index * 1e-6 - 2e-5 for index in range(101))
        if zero_span
        else tuple(range(100_000_000, 100_000_101))
    )
    sa, backend = _built(
        model,
        [
            *_frame_before_initiate(model, channels, meta),
            *_frame_after_initiate(model, channels, meta),
            *meta,
            *_frame_payload(model, 2, axis, -34),
            *meta,
            *_frame_payload(model, 1, axis, -16),
            _OK,
        ],
    )
    descriptor = next(
        item for item in sa.operation_descriptors() if item.operation_id == "acquire_traces"
    )
    assert descriptor.python_only
    assert sa.supports_operation("acquire_traces")
    frame = sa.acquire_traces(channels, timeout_ms=2_000)
    assert frame.channels == channels
    assert frame.axis == axis
    assert frame.axis_unit == ("s" if zero_span else "Hz")
    assert frame.amplitude_unit == "dBmV"
    assert [trace.peak().amplitude for trace in frame.traces] == [-34, -16]
    assert all(trace.acquisition == "fresh" and trace.sweep_count == 1 for trace in frame.traces)
    measurement = frame.to_measurement_result()
    axis_name = "time_s" if zero_span else "frequency_hz"
    assert measurement.values.columns == [axis_name, "trace_2", "trace_1"]
    assert measurement.values[axis_name].to_list() == list(axis)
    assert measurement.values["trace_2"].to_list() == [-34.0] * len(axis)
    assert measurement.values["trace_1"].to_list() == [-16.0] * len(axis)
    assert measurement.envelope["trace_order"] == [2, 1]
    assert measurement.envelope["traces"][0]["trace_mode"] == "clear_write"
    assert measurement.envelope["column_units"]["trace_2"] == "dBmV"
    assert measurement.timestamp >= frame.traces[-1].readout_timestamp
    assert all(0 < timeout <= 2_000 for timeout in backend.operation_timeouts)
    assert backend.history.count("INIT:IMM") == 1
    assert not backend.exchange


def test_fsw_synchronized_frame_rejects_inactive_trace_before_initiating():
    channels = (1, 2)
    guard = _frame_before_initiate(_FSW, channels, _META)
    index = guard.index(("DISP:TRAC2:STAT?", "1"))
    sa, backend = _built(_FSW, [*guard[:index], ("DISP:TRAC2:STAT?", "0")])
    with pytest.raises(InstrumentDataError, match="must be enabled"):
        sa.acquire_traces(channels)
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange


def test_synchronized_frame_rejects_disagreeing_axes_without_returning_partial_data():
    channels = (1, 2)
    axis = tuple(range(100, 201))
    different_axis = (*axis[:-1], axis[-1] + 1)
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_frame_before_initiate(_KEYSIGHT, channels, _META),
            *_frame_after_initiate(_KEYSIGHT, channels, _META),
            *_META,
            *_frame_payload(_KEYSIGHT, 1, axis, -25),
            *_META,
            *_frame_payload(_KEYSIGHT, 2, different_axis, -35),
        ],
    )
    with pytest.raises(InstrumentDataError, match="same coordinates"):
        sa.acquire_traces(channels)
    assert not backend.exchange


def test_synchronized_frame_quarantines_an_interrupted_second_trace_read():
    channels = (1, 2)
    axis = tuple(range(100, 201))
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_frame_before_initiate(_KEYSIGHT, channels, _META),
            *_frame_after_initiate(_KEYSIGHT, channels, _META),
            *_META,
            *_frame_payload(_KEYSIGHT, 1, axis, -25),
            *_META,
            ("FETC:SAN2?", TimeoutError("transfer timed out")),
        ],
    )
    with pytest.raises(InstrumentCommunicationError, match="transfer timed out"):
        sa.acquire_traces(channels, timeout_ms=2_000)
    with pytest.raises(InstrumentCommunicationError, match="uncertain"):
        sa.get_trace(1)
    assert backend.history.count("INIT:IMM") == 1
    assert not backend.exchange


@pytest.mark.parametrize("channels", [(), (1,), (1, 1), (1, True)])
def test_synchronized_frame_validates_trace_selection_before_io(channels):
    sa, backend = _built(_KEYSIGHT, [])
    with pytest.raises(InstrumentConfigurationError, match="[Tt]race index"):
        sa.acquire_traces(channels)
    assert not backend.history


def test_synchronized_frame_rejects_unit_change_before_second_transfer():
    channels = (1, 2)
    axis = tuple(range(100, 201))
    sa, backend = _built(
        _FSW,
        [
            *_frame_before_initiate(_FSW, channels, _META),
            *_frame_after_initiate(_FSW, channels, _META),
            *_META,
            *_frame_payload(_FSW, 1, axis, -25),
            *_META[:2],
            ("UNIT:POW?", "DBM"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="metadata changed before transfer"):
        sa.acquire_traces(channels)
    assert "TRAC:DATA:X? TRACE2" not in backend.history
    assert not backend.exchange


@pytest.mark.parametrize(
    ("layout_reply", "window_type", "message"),
    [
        ("'1',1,'2',2", None, "exactly one display window"),
        ("'2',2", None, "at index 1"),
        ("'1',1", "SGR", "Diagram window"),
        ("'1',1", "MTAB", "Diagram window"),
    ],
)
def test_fsw_synchronized_frame_rejects_other_layouts_before_initiating(
    layout_reply, window_type, message
):
    state = [_OK, _mode(_FSW), ("INST:MODE?", "SAN"), ("LAY:CAT?", layout_reply)]
    if window_type is not None:
        state.append(("LAY:WIND1:TYPE?", window_type))
    sa, backend = _built(_FSW, state)
    with pytest.raises(InstrumentDataError, match=message):
        sa.acquire_traces([1, 2])
    assert all(command.endswith("?") for command in backend.history)
    assert not backend.exchange


def test_fsw_synchronized_frame_rejects_layout_changed_after_sweep_before_fetch():
    channels = (1, 2)
    sa, backend = _built(
        _FSW,
        [
            *_frame_before_initiate(_FSW, channels, _META),
            _INIT,
            ("*OPC?", "1"),
            _OK,
            _mode(_FSW),
            ("INST:MODE?", "SAN"),
            ("LAY:CAT?", "'1',1,'2',2"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="exactly one display window"):
        sa.acquire_traces(channels)
    assert backend.history.count("INIT:IMM") == 1
    assert not any(command.startswith("TRAC:DATA") for command in backend.history)
    assert not backend.exchange


def _prepare_inspection(model, *, continuous="1", transfer="REAL,32"):
    result = [_OK, _mode(model), *_safe_source(model)]
    if model == _KEYSIGHT:
        result += _key_trace_checks()
    else:
        result += [
            ("INST:MODE?", "SAN"),
            ("LAY:CAT?", "'1',1"),
            ("LAY:WIND1:TYPE?", "DIAG"),
            ("SWE:COUN?", "0"),
            ("CALC:MATH:STAT?", "0"),
            ("DISP:TRAC1:STAT?", "1"),
            ("DISP:TRAC1:MODE?", "WRIT"),
        ]
    return [*result, ("INIT:CONT?", continuous), ("FORM:DATA?", transfer), *_META, _OK]


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_bench_spectrum_alias_prepares_and_captures_from_native_replay(monkeypatch, model):
    key = model == _KEYSIGHT
    ascii_reply = "ASC,8" if key else "ASC,0"
    axis = tuple(range(999_999_950, 1_000_000_051))
    exchange = [
        *_prepare_inspection(model),
        ("INIT:CONT OFF", None),
        _OK,
        ("INIT:CONT?", "0"),
        ("*OPC?", "1"),
        ("STAT:OPER:COND?", "0" if key else "4096"),
        _OK,
        ("FORM:DATA ASC", None),
        _OK,
        *([("DISP:VIEW NORM", None), _OK] if key else []),
        *_prepare_inspection(model, continuous="0", transfer=ascii_reply),
        ("STAT:OPER:COND?", "0" if key else "4096"),
        _OK,
        *[
            (
                command,
                ascii_reply
                if command == "FORM:DATA?"
                else "0"
                if not key and command == "SWE:COUN?"
                else reply,
            )
            for command, reply in _until_init(model)
        ],
        _INIT,
        ("*OPC?", "1"),
        _OK,
        *_META,
        *_frame_payload(model, 1, axis, -27),
        _OK,
    ]
    tape = [
        {"type": "write" if reply is None else "query", "command": command, "response": reply}
        for command, reply in exchange
    ]
    backend = ReplayBackend(tape, "spectrum")
    registry.ensure_builtin_registrations()
    monkeypatch.setattr(registry, "_backends", registry._backends.copy())
    register_backend("spectrum_prepare_replay", lambda _: backend)
    descriptor = {
        "bench_name": "Spectrum preparation replay",
        "instruments": {
            "spectrum": {
                "profile": model,
                "address": "TCPIP0::192.0.2.10::inst0::INSTR",
                "backend": {"type": "spectrum_prepare_replay"},
            },
        },
    }

    with Bench.open(descriptor, aliases={"spectrum"}, start_experiment=False) as bench:
        sa = bench.spectrum
        assert sa.supports_operation("prepare_sweep")
        ready = sa.prepare_sweep(stop_continuous=True)
        assert ready.continuous is False
        assert ready.transfer_format == "ascii"
        assert ready.trace_mode == "clear_write"
        assert ready.axis_unit == "Hz" and ready.sweep_points == 101
        assert ready.amplitude_unit == "dBmV"
        assert ready.display_evidence == ("normal_selected" if key else "diagram_verified")
        trace = sa.acquire_trace()
        assert trace.axis == axis
        assert trace.peak().amplitude == -27
        assert trace.acquisition == "fresh"

    assert backend._step == len(tape)


@pytest.mark.parametrize("model", [_KEYSIGHT, _FSW])
def test_prepare_sweep_refuses_unsupported_retained_view_or_trace_without_writes(model):
    inspection = _prepare_inspection(model)
    if model == _KEYSIGHT:
        index = inspection.index(("TRAC1:TYPE?", "WRIT"))
        unsafe = ("TRAC1:TYPE?", "AVER")
        message = "Clear/Write"
    else:
        index = inspection.index(("LAY:WIND1:TYPE?", "DIAG"))
        unsafe = ("LAY:WIND1:TYPE?", "SGR")
        message = "Diagram"
    sa, backend = _built(model, [*inspection[:index], unsafe])
    with pytest.raises(InstrumentDataError, match=message):
        sa.prepare_sweep()
    assert all(command.split()[0].endswith("?") for command in backend.history)
    assert not backend.exchange


def test_prepare_sweep_does_not_change_format_when_single_sweep_is_not_confirmed():
    sa, backend = _built(
        _KEYSIGHT,
        [
            *_prepare_inspection(_KEYSIGHT),
            ("INIT:CONT OFF", None),
            _OK,
            ("INIT:CONT?", "1"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="continuous"):
        sa.prepare_sweep(stop_continuous=True)
    assert "FORM:DATA ASC" not in backend.history
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange


def test_prepare_sweep_preserves_an_already_compatible_fsw_session():
    state = _prepare_inspection(_FSW, continuous="0", transfer="ASC,0")
    sa, backend = _built(
        _FSW,
        [
            *state,
            ("INIT:CONT?", "0"),
            ("*OPC?", "1"),
            ("STAT:OPER:COND?", "4096"),
            _OK,
            *state,
            ("STAT:OPER:COND?", "4096"),
            _OK,
        ],
    )
    assert sa.prepare_sweep().display_evidence == "diagram_verified"
    assert all(command.split()[0].endswith("?") for command in backend.history)
    assert not backend.exchange


def test_prepare_sweep_requires_explicit_permission_to_stop_an_active_run():
    sa, backend = _built(_KEYSIGHT, _prepare_inspection(_KEYSIGHT))
    with pytest.raises(InstrumentConfigurationError, match="stop_continuous=True"):
        sa.prepare_sweep()
    assert all(command.split()[0].endswith("?") for command in backend.history)
    assert not backend.exchange


def test_prepare_sweep_refuses_format_change_if_analyzer_is_busy_even_after_opc():
    sa, backend = _built(
        _FSW,
        [
            *_prepare_inspection(_FSW),
            ("INIT:CONT OFF", None),
            _OK,
            ("INIT:CONT?", "0"),
            ("*OPC?", "1"),
            ("STAT:OPER:COND?", "32"),
        ],
    )
    with pytest.raises(InstrumentDataError, match="still reports an active"):
        sa.prepare_sweep(stop_continuous=True)
    assert "FORM:DATA ASC" not in backend.history
    assert "INIT:IMM" not in backend.history
    assert not backend.exchange
