from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from importlib import import_module
from struct import pack

import pytest
from typer.testing import CliRunner

from pytestlab import Bench
from pytestlab import cli_typer
from pytestlab.config.loader import load_device_profile
from pytestlab.devices import register_backend
from pytestlab.devices import registry
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.PowerMeter import PowerAcquisition
from pytestlab.instruments.PowerMeter import PowerBuffer
from pytestlab.instruments.PowerMeter import PowerMeter
from pytestlab.instruments.PowerMeter import PowerReading
from pytestlab.instruments.self_test import InstrumentSelfTestResult


class _Transcript:
    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.events: list[tuple[str, str]] = []

    def connect(self):
        self.events.append(("connect", ""))

    def disconnect(self):
        pass

    def close(self):
        self.disconnect()

    def write(self, command: str):
        self.events.append(("write", command))

    def query(self, command: str, delay: float | None = None):
        if command == "SYST:ERR?":
            return '0,"No error"'
        self.events.append(("query", command))
        return self.responses[command]


_KEY = {
    "UNIT1:POW?": "DBM",
    "FORM:DATA?": "ASC",
    "INIT1:CONT?": "0",
    "SENS1:FREQ?": "+2.39900000E+09",
    "READ1:POW:AC?": "-2.00000000E+01",
    "STAT:QUES:POW:COND?": "0",
}
_RS = {
    "UNIT:POW?": "W",
    "FORM:DATA?": "ASC,0",
    "INIT:CONT?": "0",
    "SENS1:BUFF:STAT?": "0",
    "SENS1:FREQ?": "+2.39900000E+09",
    "FETC1:POW:AVG?": "1.00000000E-05",
    "STAT:QUES:POW:COND?": "0",
}


@pytest.mark.parametrize(
    ("profile", "responses", "settings", "acquire_commands"),
    [
        (
            "keysight/U2000A_PM",
            _KEY,
            ["SENS1:AVER:COUN 8"],
            [("query", "READ1:POW:AC?")],
        ),
        (
            "rohdeschwarz/NRP18AN",
            _RS,
            [
                "SENS1:POW:AVG:FAST OFF",
                "SENS1:AVER:COUN:AUTO OFF",
                "SENS1:AVER:COUN 8",
                "SENS1:AVER:TCON REP",
                "SENS1:AVER:STAT ON",
            ],
            [
                ("write", 'CALC:FEED "POWer:AVERage"'),
                ("write", "INIT"),
                ("write", "*WAI"),
                ("query", "FETC1:POW:AVG?"),
            ],
        ),
    ],
)
def test_same_bench_api_acquires_one_vendor_specific_scalar(
    monkeypatch, profile, responses, settings, acquire_commands
):
    backend = _Transcript(responses)
    registry.ensure_builtin_registrations()
    monkeypatch.setattr(registry, "_backends", registry._backends.copy())
    register_backend("rf_power_test", lambda _: backend)
    descriptor = {
        "bench_name": "RF transcript",
        "instruments": {
            "rf_meter": {
                "profile": profile,
                "address": "TCPIP::192.0.2.10::INSTR",
                "backend": {"type": "rf_power_test"},
            },
        },
    }
    with Bench.open(descriptor, aliases={"rf_meter"}, start_experiment=False) as bench:
        meter = bench.rf_meter
        assert meter.describe_operation("measure_power")["support"]["supported"]
        with pytest.raises(InstrumentParameterError):
            meter.measure_power(2)
        with pytest.raises(InstrumentParameterError):
            meter.configure_sensor(1, freq=24e9, averaging_count=8)
        assert not backend.events
        meter.configure_sensor(1, freq=2.4e9, averaging_count=8)
        reading = meter.measure_power(1, unit="mW")

    assert isinstance(reading, PowerReading)
    assert reading.value == pytest.approx(0.01)
    assert (reading.unit, reading.channel, reading.correction_frequency_hz) == ("mW", 1, 2.399e9)
    reply_commands = list(responses)
    before, power, quality = reply_commands[:-2], reply_commands[-2], reply_commands[-1]
    assert acquire_commands[-1] == ("query", power)
    assert backend.events == [
        ("connect", ""),
        ("write", "SENS1:FREQ 2400000000.0"),
        *(("write", command) for command in settings),
        *(("query", command) for command in before),
        *acquire_commands,
        ("query", quality),
    ]


@pytest.mark.parametrize("response", ["OVLD", "+9.9E37", "-9.91e37", "nan", "inf", "1.2,3.4"])
def test_invalid_power_counts_are_not_readings(response):
    backend = _Transcript({**_KEY, "READ1:POW:AC?": response})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentDataError, match="Invalid power reading"):
        meter.measure_power(1)


@pytest.mark.parametrize(
    ("reply", "failure", "message"),
    [
        ({"UNIT:POW?": "dBuV"}, InstrumentDataError, "absolute power unit"),
        ({"FORM:DATA?": "REAL,32"}, InstrumentConfigurationError, "Select ASCII"),
        ({"INIT:CONT?": "1"}, InstrumentConfigurationError, "continuous measurement"),
        ({"SENS1:BUFF:STAT?": "1"}, InstrumentConfigurationError, "buffered power"),
    ],
)
def test_incompatible_existing_state_does_not_start_sensor(reply, failure, message):
    backend = _Transcript({**_RS, **reply})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(failure, match=message):
        meter.measure_power(1)
    assert not any(action == "write" for action, _ in backend.events)


def test_questionable_result_is_not_accepted():
    backend = _Transcript({**_RS, "STAT:QUES:POW:COND?": "2"})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentDataError, match="questionable"):
        meter.measure_power(1)


class _VerifiedTranscript(_Transcript):
    def __init__(self, responses: dict[str, str]):
        super().__init__(responses)
        self.timeout = 35_000
        self.timeouts: list[int] = []
        self.failure_on: str | None = None
        self.error_on_init = False
        self.init_error_pending = False
        self.stale_fetch = True
        self.power = -20.0

    def get_timeout(self):
        return self.timeout

    def set_timeout(self, timeout_ms):
        self.timeout = timeout_ms
        self.timeouts.append(timeout_ms)

    def write(self, command):
        super().write(command)
        if command == "INIT" and self.error_on_init:
            self.init_error_pending = True
        elif command == "INIT":
            self.stale_fetch = False
            self.power -= 1

    def query(self, command, delay=None):
        if command == self.failure_on:
            self.events.append(("query", command))
            raise TimeoutError("missing trigger")
        if command == "SYST:ERR?":
            self.events.append(("query", command))
            if self.init_error_pending:
                self.init_error_pending = False
                return '-213,"Init ignored"'
            return '0,"No error"'
        if command == "FETC1:POW:AVG?":
            self.events.append(("query", command))
            return "123.0" if self.stale_fetch else str(self.power)
        return super().query(command, delay)


_MANUAL_COUNT = {
    "SENS1:AVER:STAT?": "1",
    "SENS1:AVER:COUN:AUTO?": "0",
    "SENS1:AVER:COUN?": "8",
    "TRIG:SOUR?": "IMM",
}
_KEY_VERIFIED = {
    **_KEY,
    **_MANUAL_COUNT,
    "SENS1:FREQ?": "2400000000",
    "SENS1:DET:FUNC?": "AVER",
    "CALC:FEED?": '"POW:AVER"',
    "SENS1:CORR:DCYC:STAT?": "0",
    "SENS1:MRAT?": "NORM",
    "TRIG:COUN?": "1",
}
_RS_VERIFIED = {
    **_RS,
    **_MANUAL_COUNT,
    "UNIT:POW?": "DBM",
    "SENS1:FREQ?": "2400000000",
    "SENS1:FUNC?": '"POWer:AVG"',
    "CALC:FEED?": '"POWer:AVERage"',
    "SENS1:POW:AVG:FAST?": "0",
    "SENS1:AUX?": "NONE",
    "SENS1:AVER:TCON?": "REP",
    "TRIG:COUN?": "1",
    "SENS1:POW:AVG:APER?": "0.02",
    "SENS1:CORR:DCYC:STAT?": "0",
    "TRIG:ATR:STAT?": "0",
    "TRIG:SEND:STAT?": "0",
    "TRIG:SYNC:STAT?": "0",
    "*OPC?": "1",
}
_GATED = {
    **_KEY_VERIFIED,
    "SENS1:DET:FUNC?": "NORM",
    "CALC:FEED?": '"POW:AVER ON SWEEP1"',
    "TRIG:SOUR?": "EXT",
    "TRIG:SLOP?": "POS",
    "TRIG:DEL:AUTO?": "0",
    "TRIG:DEL?": "+0.000E+00",
    "SENS1:SWE:OFFS:TIME?": "0.0002",
    "SENS1:SWE:TIME?": "0.0004",
    "READ1?": "-5",
}


@pytest.mark.parametrize(
    ("profile", "responses", "native_value", "expected_setup", "expected_start", "aperture"),
    [
        (
            "keysight/U2000A_PM",
            _KEY_VERIFIED,
            -20,
            ["SENS1:DET:FUNC AVER", "INIT1:CONT OFF", "TRIG:SOUR IMM", 'CALC:FEED "POW:AVER"'],
            [("query", "READ1:POW:AC?")],
            None,
        ),
        (
            "rohdeschwarz/NRP18AN",
            _RS_VERIFIED,
            -21,
            ['SENS1:FUNC "POWer:AVG"', "INIT:CONT OFF", "TRIG:COUN 1", 'CALC:FEED "POWer:AVERage"'],
            [
                ("write", "ABOR"),
                ("write", "INIT"),
                ("query", "*OPC?"),
                ("query", "SYST:ERR?"),
                ("query", "FETC1:POW:AVG?"),
            ],
            0.02,
        ),
    ],
)
def test_verified_average_is_portable_and_reports_live_settings(
    profile, responses, native_value, expected_setup, expected_start, aperture
):
    backend = _VerifiedTranscript(responses)
    meter = PowerMeter(load_device_profile(profile), backend)
    for op in ("configure_power", "acquire_power"):
        assert meter.describe_operation(op)["support"]["supported"]
    assert not backend.events
    configured = meter.configure_power(frequency_hz=2.4e9, averaging_count=8)
    writes = [command for action, command in backend.events if action == "write"]
    assert all(command in writes for command in expected_setup)
    assert writes.index("SENS1:AVER:COUN:AUTO OFF") < writes.index("SENS1:AVER:COUN 8")
    assert "SENS1:AVER:STAT ON" in writes
    assert not any(command in ["*RST", "CAL:ZERO"] for command in writes)

    assert 0 < backend.timeouts[0] <= 5000
    backend.events.clear()
    backend.timeouts.clear()
    reading = meter.acquire_power(unit="mW", timeout_ms=1200)
    assert isinstance(reading, PowerAcquisition)
    assert (reading.value, reading.unit) == (pytest.approx(10 ** (native_value / 10)), "mW")
    assert reading.received_at_utc.tzinfo is UTC
    assert reading.settings == configured
    assert reading.settings.native_unit == "dBm"
    assert reading.settings.correction_frequency_hz == 2.4e9
    assert reading.settings.averaging_count == 8
    assert reading.settings.trigger_source == "immediate"
    assert reading.settings.aperture_s == aperture
    start = backend.events.index(expected_start[0])
    assert backend.events[start : start + len(expected_start)] == expected_start
    assert backend.timeout == 35_000
    assert 0 < backend.timeouts[0] <= 1200


def test_gated_average_mode_is_explicit_and_uses_verified_gate_readback():
    backend = _VerifiedTranscript(_GATED)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    options = meter.list_operation_options("acquire_power", "mode")
    assert any(option["value"] == "gated_average" for option in options)
    configured = meter.configure_power(
        frequency_hz=2.4e9, mode="gated_average", gate_offset_s=0.0002002, gate_duration_s=0.0004
    )
    commands = [command for action, command in backend.events if action == "write"]
    assert commands.index("SENS1:DET:FUNC NORM") < commands.index("TRIG:SOUR EXT")
    assert commands.index("TRIG:SOUR EXT") < commands.index('CALC:FEED "POW:AVER ON SWEEP"')
    assert configured.trigger_source == "external"
    assert configured.gate_offset_s == 0.0002  # sensor rounds to the nearest 1 us
    assert configured.gate_duration_s == 0.0004
    reading = meter.acquire_power(mode="gated_average")
    assert reading.value == -5
    assert reading.settings == configured
    arm = backend.events.index(("query", "READ1?"))
    assert backend.events[arm - 1] == ("write", "ABOR")
    assert ("query", "READ1:POW:AC?") not in backend.events


def test_wrong_detector_or_feed_is_never_substituted():
    backend = _VerifiedTranscript({**_GATED, "CALC:FEED?": '"POW:AVER"'})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentConfigurationError, match="detector"):
        meter.acquire_power()
    with pytest.raises(InstrumentConfigurationError, match="swept average feed"):
        meter.acquire_power(mode="gated_average")
    assert not any(command.startswith("READ") for _, command in backend.events)


def test_unsupported_or_incomplete_gate_fails_without_io():
    backend = _VerifiedTranscript(_RS_VERIFIED)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    options = meter.list_operation_options("acquire_power", "mode", include_unsupported=True)
    gated = next(option for option in options if option["value"] == "gated_average")
    assert not gated["supported"]
    assert "does not support" in gated["reason"]
    with pytest.raises(InstrumentParameterError, match="time-gated"):
        meter.acquire_power(mode="gated_average")
    assert backend.events == []

    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(ValueError, match="requires both"):
        meter.configure_power(frequency_hz=2.4e9, mode="gated_average", gate_duration_s=0.0004)
    with pytest.raises(InstrumentParameterError):
        meter.configure_power(
            frequency_hz=2.4e9, mode="gated_average", gate_offset_s=0, gate_duration_s=0.00009
        )
    assert backend.events == []


def test_configuration_acknowledgement_does_not_substitute_for_readback():
    backend = _VerifiedTranscript({**_RS_VERIFIED, "SENS1:AVER:COUN?": "4"})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentConfigurationError, match="averaging count"):
        meter.configure_power(frequency_hz=2.4e9, averaging_count=8)


def test_rs_rejects_failed_or_uncompleted_start_before_last_valid_fetch():
    backend = _VerifiedTranscript(_RS_VERIFIED)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    backend.error_on_init = True
    with pytest.raises(InstrumentCommunicationError, match="Init ignored"):
        meter.acquire_power()
    assert ("query", "FETC1:POW:AVG?") not in backend.events

    backend.error_on_init = False
    # A fresh completed acquisition updates the previously stale scalar each time.
    assert meter.acquire_power().value == -21
    assert meter.acquire_power().value == -22

    backend.events.clear()
    backend.responses = {**_RS_VERIFIED, "*OPC?": "0"}
    with pytest.raises(InstrumentDataError, match="did not complete"):
        meter.acquire_power()
    assert ("query", "FETC1:POW:AVG?") not in backend.events


def test_rs_timeout_at_completion_never_uses_last_valid_result():
    backend = _VerifiedTranscript(_RS_VERIFIED)
    backend.failure_on = "*OPC?"
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentCommunicationError, match="missing trigger"):
        meter.acquire_power(timeout_ms=100)
    assert ("query", "FETC1:POW:AVG?") not in backend.events
    assert backend.timeout == 35_000
    before_retry = list(backend.events)
    with pytest.raises(InstrumentCommunicationError, match="device clear"):
        meter.acquire_power()
    assert backend.events == before_retry


def test_missing_external_trigger_restores_transport_timeout_without_returning_a_reading():
    backend = _VerifiedTranscript(_GATED)
    backend.failure_on = "READ1?"
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentCommunicationError, match="missing trigger") as failure:
        meter.acquire_power(mode="gated_average", timeout_ms=75)
    assert "may still be armed" in failure.value.__notes__[0]
    assert backend.events[-1] == ("query", "READ1?")
    assert backend.timeout == 35_000
    assert all(0 < value <= 75 for value in backend.timeouts[::2])
    before_retry = list(backend.events)
    with pytest.raises(InstrumentCommunicationError, match="device clear"):
        meter.acquire_power(mode="gated_average")
    assert backend.events == before_retry

    # A late scalar would be syntactically valid for the legacy fetch, but
    # none of the compatibility methods may touch this quarantined stream.
    backend.responses = {**_GATED, "FETC1:POW:AC?": "-5"}
    for operation in (
        meter.read_power,
        lambda: meter.measure_power(1),
        lambda: meter.configure_sensor(freq=2.4e9),
    ):
        with pytest.raises(InstrumentCommunicationError, match="device clear"):
            operation()
    assert backend.events == before_retry


@pytest.mark.parametrize("failure_stage", ["write", "readback"])
def test_ambiguous_verified_setup_failure_quarantines_legacy_fetch(failure_stage):
    class _FailingSetup(_VerifiedTranscript):
        def write(self, command):
            super().write(command)
            if failure_stage == "write" and command == "SENS1:DET:FUNC AVER":
                raise TimeoutError("configuration write did not complete")

    backend = _FailingSetup({**_KEY_VERIFIED, "FETC1:POW:AC?": "-20"})
    if failure_stage == "readback":
        backend.failure_on = "SENS1:FREQ?"
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentCommunicationError) as failure:
        meter.configure_power(frequency_hz=2.4e9)
    assert isinstance(failure.value.__cause__, TimeoutError)
    assert "device clear" in failure.value.__notes__[0]
    events = list(backend.events)
    with pytest.raises(InstrumentCommunicationError, match="device clear"):
        meter.read_power()
    assert backend.events == events


def test_interrupt_during_gate_query_preserves_interrupt_and_quarantines_session():
    interrupted = KeyboardInterrupt("user canceled external arm")

    class _Interruptible(_VerifiedTranscript):
        def query(self, command, delay=None):
            if command == "READ1?":
                raise interrupted
            return super().query(command, delay)

    backend = _Interruptible(_GATED)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(KeyboardInterrupt) as failure:
        meter.acquire_power(mode="gated_average")
    assert failure.value is interrupted
    assert "device clear" in failure.value.__notes__[0]
    assert backend.timeout == 35_000
    with pytest.raises(InstrumentCommunicationError, match="device clear"):
        meter.read_power()


def test_late_transport_reply_cannot_return_a_reading(monkeypatch):
    import importlib

    module = importlib.import_module("pytestlab.instruments.PowerMeter")
    clock = iter([0.0, 0.0, 0.2])
    monkeypatch.setattr(module, "monotonic", lambda: next(clock))
    backend = _VerifiedTranscript(_KEY_VERIFIED)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentCommunicationError, match="exceeded"):
        meter.acquire_power(timeout_ms=100)
    assert backend.events[-1] == ("query", "FORM:DATA?")
    assert backend.timeout == 35_000


def test_native_device_clear_after_lost_gate_query_aborts_pending_read_and_allows_new_arm():
    class _Clearable(_VerifiedTranscript):
        def device_clear(self):
            self.events.append(("clear", "device"))
            self.failure_on = None

    backend = _Clearable(_GATED)
    backend.failure_on = "READ1?"
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentCommunicationError, match="missing trigger"):
        meter.acquire_power(mode="gated_average", timeout_ms=75)
    assert backend.events[-2:] == [("query", "READ1?"), ("clear", "device")]
    assert backend.timeouts[-2:] == [250, 35_000]
    assert meter.acquire_power(mode="gated_average").value == -5


_IDLE = {
    "STAT:OPER:CAL:COND?": "0",
    "STAT:OPER:MEAS:COND?": "0",
    "STAT:OPER:TRIG:COND?": "0",
}
_ZERO_KEY = {
    **_KEY_VERIFIED,
    **_IDLE,
    "*IDN?": "Keysight Technologies,U2000A,MY12345678,A1.04.01",
    "CAL1:ZERO:TYPE?": "INT",
    "*OPC?": "1",
}
_ZERO_RS = {
    **_RS_VERIFIED,
    **_IDLE,
    "*IDN?": "Rohde&Schwarz,NRP18AN,123456,03.50",
    "SYST:SERR?": '0,"No error"',
}
_BUFFER = {
    **_RS_VERIFIED,
    "SENS1:BUFF:STAT?": "1",
    "SENS1:POW:AVG:BUFF:SIZE?": "3",
    "SENS1:POW:AVG:BUFF:COUN?": "3",
    "TRIG:COUN?": "3",
    "UNIT:POW?": "W",
    "FETC1:ARR:POW:AVG?": "1e-6,2e-6,3e-6",
}


def test_zero_selects_type_and_reports_only_completed_zero():
    backend = _VerifiedTranscript(_ZERO_KEY)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    result = meter.zero_sensor(mode="internal")
    assert (result.mode, result.channel, result.completed_at_utc.tzinfo) == ("internal", 1, UTC)
    assert backend.events[-6:] == [
        ("write", "CAL1:ZERO:TYPE INT"),
        ("query", "SYST:ERR?"),
        ("query", "CAL1:ZERO:TYPE?"),
        ("write", "CAL1:ZERO:AUTO ONCE"),
        ("query", "*OPC?"),
        ("query", "SYST:ERR?"),
    ]
    backend.responses = {**_ZERO_KEY, "CAL1:ZERO:TYPE?": "EXT"}
    assert meter.zero_sensor().mode == "external"
    assert backend.events[-6:] == [
        ("write", "CAL1:ZERO:TYPE EXT"),
        ("query", "SYST:ERR?"),
        ("query", "CAL1:ZERO:TYPE?"),
        ("write", "CAL1:ZERO:AUTO ONCE"),
        ("query", "*OPC?"),
        ("query", "SYST:ERR?"),
    ]
    backend.responses = {**_ZERO_KEY, "CAL1:ZERO:TYPE?": "EXT", "*OPC?": "0"}
    with pytest.raises(InstrumentDataError, match="zero did not complete") as failure:
        meter.zero_sensor()
    assert ("write", "CAL1:ZERO:TYPE EXT") in backend.events
    assert "Verify the sensor at the bench" in failure.value.__notes__[0]
    with pytest.raises(InstrumentCommunicationError, match="zero outcome is uncertain"):
        meter.read_power()


def test_rs_zero_uses_static_error_and_never_aborts_an_active_measurement():
    backend = _VerifiedTranscript({**_ZERO_RS, "STAT:OPER:TRIG:COND?": "+2"})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentParameterError, match="quiet RF"):
        meter.zero_sensor(mode="internal")
    assert not backend.events
    with pytest.raises(InstrumentConfigurationError, match="idle"):
        meter.zero_sensor()
    assert not any(action == "write" for action, _ in backend.events)

    backend.responses = {**_ZERO_RS, "SYST:SERR?": '-240,"Zero calibration failed"'}
    with pytest.raises(InstrumentCommunicationError, match="Zero calibration failed"):
        meter.zero_sensor()
    assert backend.events[-2:] == [("write", "CAL1:ZERO:AUTO ONCE"), ("query", "SYST:SERR?")]
    backend.responses = _ZERO_RS
    assert meter.zero_sensor().mode == "external"


@pytest.mark.parametrize("native_clear_works", [False, True])
def test_zero_timeout_quarantines_before_status_or_acquisition(native_clear_works):
    class _ClearableZero(_VerifiedTranscript):
        def device_clear(self):
            self.events.append(("clear", "device"))
            self.failure_on = None

    backend_cls = _ClearableZero if native_clear_works else _VerifiedTranscript
    backend = backend_cls(_ZERO_RS)
    backend.failure_on = "SYST:SERR?"
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentCommunicationError, match="missing trigger") as failure:
        meter.zero_sensor(timeout_ms=100)
    assert "Verify the sensor at the bench" in failure.value.__notes__[0]
    assert backend.timeout == 35_000
    assert (("clear", "device") in backend.events) is native_clear_works
    previous = list(backend.events)
    for operation in (meter.sensor_status, meter.acquire_power, meter.read_power):
        with pytest.raises(InstrumentCommunicationError, match="zero outcome is uncertain"):
            operation()
    assert backend.events == previous


@pytest.mark.parametrize(
    ("identity", "configured_serial", "error"),
    [
        ("Keysight Technologies,U2000B,MY12345678,A1.04.01", None, InstrumentConfigurationError),
        (
            "Keysight Technologies,U2000A,MY12345678,A1.04.01",
            "MY87654321",
            InstrumentConfigurationError,
        ),
        ("OtherVendor,U2000A,MY12345678,A1.04.01", "MY12345678", InstrumentConfigurationError),
        ("U2000A", None, InstrumentDataError),
    ],
)
def test_zero_requires_a_matching_live_model_and_optional_serial_before_any_write(
    identity, configured_serial, error
):
    profile = load_device_profile("keysight/U2000A_PM")
    profile.serial_number = configured_serial
    backend = _VerifiedTranscript({**_ZERO_KEY, "*IDN?": identity})
    meter = PowerMeter(profile, backend)
    with pytest.raises(error, match="identity|identification"):
        meter.zero_sensor(mode="internal")
    assert backend.events == [("connect", ""), ("query", "*IDN?")]


def test_keysight_native_agilent_personality_is_accepted_for_guarded_service():
    backend = _VerifiedTranscript(
        {**_ZERO_KEY, "*IDN?": "Agilent Technologies,U2000A,MY12345678,A1.04.01"}
    )
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    assert meter.zero_sensor(mode="internal").mode == "internal"


def test_status_has_real_sensor_identity_and_decodes_without_consuming_error_events():
    backend = _VerifiedTranscript(
        {
            "*IDN?": "Rohde&Schwarz,NRP18AN,123456,03.50",
            "STAT:QUES:POW:COND?": "+34",
            "STAT:QUES:CAL:COND?": "6",
        }
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    status = meter.sensor_status()
    assert (status.model, status.serial_number, status.firmware) == ("NRP18AN", "123456", "03.50")
    assert (status.power_condition, status.calibration_condition) == (34, 6)
    assert status.active_conditions == (
        "sensor measurement corrupt",
        "sensor zeroing needed",
        "sensor zero failed",
        "unknown calibration condition bit 2",
    )
    assert not status.measurement_ok
    assert backend.events == [
        ("connect", ""),
        ("query", "*IDN?"),
        ("query", "STAT:QUES:POW:COND?"),
        ("query", "STAT:QUES:CAL:COND?"),
    ]


def test_aperture_edge_and_automatic_averaging_are_verified_and_read_without_arming():
    backend = _VerifiedTranscript(
        {
            **_RS_VERIFIED,
            "TRIG:SOUR?": "EXT1",
            "TRIG:SLOP?": "NEG",
            "TRIG:DEL:AUTO?": "0",
            "TRIG:DEL?": "0",
            "SENS1:AVER:COUN:AUTO?": "1",
            "SENS1:POW:AVG:APER?": "0.0001",
        }
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    configured = meter.configure_power(
        frequency_hz=2.4e9,
        trigger_source="external_1",
        trigger_edge="falling",
        aperture_s=0.0001,
        averaging_mode="automatic",
    )
    assert (configured.trigger_source, configured.trigger_edge) == ("external_1", "falling")
    assert (configured.aperture_s, configured.averaging_mode) == (0.0001, "automatic")
    assert ("write", "SENS1:POW:AVG:APER 0.0001") in backend.events
    assert ("write", "TRIG:SOUR EXT1") in backend.events
    assert ("write", "TRIG:SLOP NEG") in backend.events
    writes = [cmd for kind, cmd in backend.events if kind == "write"]
    assert "SENS1:AVER:COUN:AUTO ON" in writes
    assert not any(cmd.startswith("SENS1:AVER:COUN ") for cmd in writes)

    backend.events.clear()
    assert configured == meter.read_power_settings()
    assert all(action == "query" for action, _ in backend.events)
    assert meter.acquire_power().settings == configured

    backend.events.clear()
    backend.responses = {**backend.responses, "TRIG:ATR:STAT?": "1"}
    with pytest.raises(InstrumentConfigurationError, match="automatic trigger"):
        meter.acquire_power()
    assert ("write", "INIT") not in backend.events


def test_rs_buffer_is_fresh_ordered_and_distinct_from_the_scalar_workflow():
    backend = _VerifiedTranscript(_BUFFER)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    configured = meter.configure_power(
        frequency_hz=2.4e9, native_unit="W", mode="buffered_average", sample_count=3
    )
    assert configured.sample_count == 3
    assert ("write", "SENS1:POW:AVG:BUFF:SIZE 3") in backend.events
    assert ("write", "TRIG:COUN 3") in backend.events

    backend.events.clear()
    with pytest.raises(InstrumentConfigurationError, match="buffering"):
        meter.acquire_power()
    assert not any(action == "write" for action, _ in backend.events)
    backend.events.clear()

    capture = meter.acquire_power_buffer(unit="uW")
    assert capture.values == pytest.approx((1.0, 2.0, 3.0))
    assert (capture.unit, capture.settings, capture.received_at_utc.tzinfo) == (
        "uW",
        configured,
        UTC,
    )
    arm = backend.events.index(("write", "INIT"))
    assert backend.events[arm - 2 : arm + 5] == [
        ("write", "ABOR"),
        ("write", "SENS1:POW:AVG:BUFF:CLE"),
        ("write", "INIT"),
        ("query", "*OPC?"),
        ("query", "SYST:ERR?"),
        ("query", "SENS1:POW:AVG:BUFF:COUN?"),
        ("query", "FETC1:ARR:POW:AVG?"),
    ]


@pytest.mark.parametrize(
    ("override", "message", "fetch"),
    [
        ({"SENS1:POW:AVG:BUFF:COUN?": "2"}, "fill the power buffer", False),
        ({"FETC1:ARR:POW:AVG?": "1e-6,2e-6"}, "Expected 3 power readings", True),
        ({"FETC1:ARR:POW:AVG?": "1e-6,9.91e37,3e-6"}, "Invalid power reading", True),
    ],
)
def test_buffer_rejects_partial_or_invalid_data(override, message, fetch):
    backend = _VerifiedTranscript({**_BUFFER, **override})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentDataError, match=message):
        meter.acquire_power_buffer()
    assert (("query", "FETC1:ARR:POW:AVG?") in backend.events) is fetch


def test_inapplicable_workflow_options_fail_before_io():
    backend = _VerifiedTranscript({})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentParameterError, match="buffered-average"):
        meter.configure_power(frequency_hz=2.4e9, mode="buffered_average", sample_count=3)
    with pytest.raises(ValueError, match="requires gated_average"):
        meter.configure_power(frequency_hz=2.4e9, trigger_source="external")
    assert not backend.events

    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentParameterError):
        meter.configure_power(frequency_hz=2.4e9, aperture_s=8e-6)
    with pytest.raises(ValueError, match="only valid with manual"):
        meter.configure_power(frequency_hz=2.4e9, averaging_count=2, averaging_mode="disabled")
    assert not backend.events


def test_key_gated_falling_edge_without_averaging_reports_actual_settings():
    backend = _VerifiedTranscript({**_GATED, "TRIG:SLOP?": "NEG", "SENS1:AVER:STAT?": "0"})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    settings = meter.configure_power(
        frequency_hz=2.4e9,
        mode="gated_average",
        gate_offset_s=0.0002,
        gate_duration_s=0.0004,
        averaging_mode="disabled",
        trigger_edge="falling",
    )
    assert (settings.trigger_edge, settings.averaging_mode) == ("falling", "disabled")
    assert ("write", "TRIG:SLOP NEG") in backend.events
    assert ("write", "SENS1:AVER:STAT OFF") in backend.events
    assert meter.acquire_power(mode="gated_average").settings == settings


def test_configure_power_keeps_legacy_long_alias_placeholders():
    profile = load_device_profile("keysight/U2000A_PM")
    profile.scpi.commands["set_sensor_frequency"].template = "SENS{channel}:FREQ {frequency_hz}"
    sequence = profile.scpi.commands["configure_manual_averaging"].sequence
    sequence[1] = "SENS{channel}:AVER:COUN {averaging_count}"
    backend = _VerifiedTranscript(_KEY_VERIFIED)
    result = PowerMeter(profile, backend).configure_power(frequency_hz=2.4e9, averaging_count=8)
    assert (result.correction_frequency_hz, result.averaging_count) == (2.4e9, 8)
    assert ("write", "SENS1:FREQ 2400000000.0") in backend.events
    assert ("write", "SENS1:AVER:COUN 8") in backend.events


@pytest.mark.parametrize(
    ("profile_key", "responses", "read_command"),
    [
        (
            "keysight/U2000A_PM",
            {**_KEY_VERIFIED, "READ1?": "-15"},
            "READ1?",
        ),
        ("rohdeschwarz/NRP18AN", _RS_VERIFIED, "FETC1:POW:AVG?"),
    ],
)
def test_pulse_average_is_explicitly_set_verified_and_not_mislabeled(
    profile_key, responses, read_command
):
    backend = _VerifiedTranscript(
        {**responses, "SENS1:CORR:DCYC:STAT?": "1", "SENS1:CORR:DCYC?": "25"}
    )
    meter = PowerMeter(load_device_profile(profile_key), backend)
    configured = meter.configure_power(
        frequency_hz=2.4e9, mode="pulse_average", duty_cycle_percent=25
    )
    assert configured.duty_cycle_percent == 25
    assert ("write", "SENS1:CORR:DCYC 25PCT") in backend.events
    # A corrected reading must never be presented as a plain average.
    backend.events.clear()
    with pytest.raises(InstrumentConfigurationError, match="duty-cycle"):
        meter.acquire_power()
    assert not any(kind == "write" for kind, _ in backend.events)
    answer = meter.acquire_power(mode="pulse_average")
    assert answer.settings == configured
    assert ("query", read_command) in backend.events


@pytest.mark.parametrize(
    ("mode", "feed", "setting"),
    [
        ("peak", '"POWER:PEAK"', 'CALC:FEED "POWer:PEAK"'),
        ("random_sample", '"POW:RAND"', 'CALC:FEED "POWer:RANDom"'),
    ],
)
def test_rs_acquires_native_measurand_under_verified_sensor_feed(mode, feed, setting):
    backend = _VerifiedTranscript({**_RS_VERIFIED, "CALC:FEED?": feed})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    configured = meter.configure_power(frequency_hz=2.4e9, mode=mode)
    assert configured.mode == mode
    assert configured.feed == feed.strip('"')
    assert ("write", setting) in backend.events
    backend.events.clear()
    with pytest.raises(InstrumentConfigurationError, match="average feed"):
        meter.acquire_power()
    assert ("write", "INIT") not in backend.events
    assert meter.acquire_power(mode=mode).settings == configured
    assert ("write", "INIT") in backend.events
    assert ("query", "FETC1:POW:AVG?") in backend.events


_TRACE = {
    **_KEY_VERIFIED,
    "SENS1:DET:FUNC?": "NORM",
    "SENS1:AVER:STAT?": "0",
    "TRIG:SOUR?": "EXT",
    "TRIG:SLOP?": "POS",
    "TRIG:DEL:AUTO?": "0",
    "TRIG:DEL?": "0",
    "TRAC1:STAT?": "1",
    "SENS1:TRAC:UNIT?": "W",
    "SENS1:TRAC:OFFS:TIME?": "-0.00003",
    "SENS1:TRAC:TIME?": "0.0001",
    "SENS1:FREQ:STEP?": "0",
    "SENS1:BUFF:COUN?": "1",
    "*OPC?": "1",
}


def _trace_block(*values):
    payload = pack(f">{len(values)}f", *values)
    size = str(len(payload)).encode()
    return b"#" + str(len(size)).encode() + size + payload + b"\n"


class _TraceTranscript(_VerifiedTranscript):
    def __init__(self, responses):
        super().__init__(responses)
        self.trace_arm = 0
        self.bad_raw = None

    def write(self, command):
        super().write(command)
        if command == "INIT1":
            if self.error_on_init:
                self.init_error_pending = True
            else:
                self.trace_arm += 1

    def query_raw(self, command):
        self.events.append(("raw", command))
        return self.bad_raw or _trace_block(1e-6 * self.trace_arm, 2e-6, 3e-6)


def test_key_trace_arm_completion_and_raw_decode_use_verified_time_window_and_units():
    backend = _TraceTranscript(_TRACE)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    configured = meter.configure_power_trace(
        frequency_hz=2.4e9, duration_s=0.0001003, offset_s=-30e-6, native_unit="W"
    )
    assert configured.time_window_s == pytest.approx((-30e-6, 70e-6))
    assert configured.trigger_source == "external"
    assert ("write", "SENS1:TRAC:UNIT W") in backend.events
    assert ("write", "TRAC1:STAT ON") in backend.events

    backend.events.clear()
    result = meter.acquire_power_trace(unit="uW", timeout_ms=1200)
    assert result.settings == configured
    assert result.values == pytest.approx((1, 2, 3))
    assert result.sampled_peak == pytest.approx(3)
    assert result.received_at_utc.tzinfo is UTC
    arm = backend.events.index(("write", "INIT1"))
    assert backend.events[arm - 1 : arm + 4] == [
        ("write", "ABOR"),
        ("write", "INIT1"),
        ("query", "*OPC?"),
        ("query", "SYST:ERR?"),
        ("raw", "TRAC1:DATA? HRES"),
    ]
    assert meter.acquire_power_trace(unit="uW").values == pytest.approx((2, 2, 3))
    assert backend.timeout == 35_000


def test_key_trace_fails_closed_on_init_rejection_and_malformed_binary():
    backend = _TraceTranscript(_TRACE)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    backend.error_on_init = True
    with pytest.raises(InstrumentCommunicationError, match="Init ignored"):
        meter.acquire_power_trace()
    assert not any(kind == "raw" for kind, _ in backend.events)

    backend.error_on_init = False
    backend.bad_raw = _trace_block(1e-6, 2e-6)[:-2]
    with pytest.raises(InstrumentDataError, match="Invalid power trace block"):
        meter.acquire_power_trace()
    assert backend.timeout == 35_000
    with pytest.raises(InstrumentCommunicationError, match="device clear"):
        meter.acquire_power_trace()


def test_key_trace_missing_edge_cannot_fetch_a_stale_buffer_and_recovers_with_clear():
    class _ClearableTrace(_TraceTranscript):
        def device_clear(self):
            self.events.append(("clear", "device"))
            self.failure_on = None

    backend = _ClearableTrace(_TRACE)
    backend.failure_on = "*OPC?"
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentCommunicationError, match="missing trigger"):
        meter.acquire_power_trace(timeout_ms=100)
    assert not any(kind == "raw" for kind, _ in backend.events)
    assert backend.events[-2:] == [("query", "*OPC?"), ("clear", "device")]
    assert backend.timeout == 35_000
    assert meter.acquire_power_trace(unit="uW").values == pytest.approx((2, 2, 3))


def test_key_trace_internal_level_and_resolution_validate_before_use():
    backend = _TraceTranscript(
        {**_TRACE, "TRIG:SOUR?": "INT", "TRIG:SLOP?": "NEG", "TRIG:LEV?": "-6.0"}
    )
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(ValueError, match="trigger_level_dbm"):
        meter.configure_power_trace(
            frequency_hz=2.4e9, duration_s=100e-6, trigger_source="internal"
        )
    assert not backend.events
    configured = meter.configure_power_trace(
        frequency_hz=2.4e9,
        duration_s=100e-6,
        offset_s=-30e-6,
        trigger_source="internal",
        trigger_edge="falling",
        trigger_level_dbm=-6.04,
        native_unit="W",
    )
    assert configured.trigger_level_dbm == -6.0
    assert ("write", "TRIG:LEV -6.04") in backend.events
    backend.bad_raw = _trace_block(*(1e-6 for _ in range(230)))
    reading = meter.acquire_power_trace(resolution="low")
    assert len(reading.values) == 230
    assert ("raw", "TRAC1:DATA? LRES") in backend.events


@pytest.mark.parametrize(
    ("profile", "family", "vendor"),
    [
        (
            "keysight/U2000A_PM",
            {
                "SENS1:CORR:GAIN2:STAT?": "1",
                "SENS1:CORR:GAIN2?": "-2.5",
                "SENS1:CORR:CSET2:STAT?": "1",
                "SENS1:CORR:CSET2:SEL?": '"Cable 1"',
            },
            ("Cable 1", None),
        ),
        (
            "rohdeschwarz/NRP18AN",
            {
                "SENS1:CORR:OFFS:STAT?": "1",
                "SENS1:CORR:OFFS?": "-2.5",
                "SENS1:CORR:SPD:STAT?": "1",
                "SENS1:CORR:SPD:SEL?": "3",
            },
            (None, 3),
        ),
    ],
)
def test_readback_exposes_model_specific_corrections_and_nonclearing_trigger_state(
    profile, family, vendor
):
    config = load_device_profile(profile)
    backend = _VerifiedTranscript(
        {
            **(_KEY_VERIFIED if config.model == "U2000A" else _RS_VERIFIED),
            **_IDLE,
            **family,
            "SENS1:CORR:DCYC?": "25",
            "STAT:OPER:TRIG:COND?": "2",
        }
    )
    meter = PowerMeter(config, backend)
    corrections = meter.read_power_corrections()
    assert (corrections.frequency_table_name, corrections.s_parameter_set) == vendor
    assert corrections.fixed_offset_enabled and corrections.fixed_offset_db == -2.5
    assert not corrections.duty_cycle_enabled and corrections.duty_cycle_percent == 25
    state = meter.read_power_trigger_state()
    assert state.waiting_for_trigger and not state.idle
    assert not state.continuous and not state.measuring and not state.calibrating
    assert all(kind == "query" and command != "SYST:ERR?" for kind, command in backend.events[1:])


def test_key_gate_can_use_internal_trigger_with_quantized_level():
    backend = _VerifiedTranscript(
        {**_GATED, "TRIG:SOUR?": "INT", "TRIG:SLOP?": "NEG", "TRIG:LEV?": "-8.0"}
    )
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    configured = meter.configure_power(
        frequency_hz=2.4e9,
        mode="gated_average",
        gate_offset_s=200e-6,
        gate_duration_s=400e-6,
        trigger_source="internal",
        trigger_edge="falling",
        trigger_level_dbm=-8.04,
    )
    assert (configured.trigger_source, configured.trigger_edge, configured.trigger_level_dbm) == (
        "internal",
        "falling",
        -8.0,
    )
    assert ("write", "TRIG:SOUR INT") in backend.events
    assert ("write", "TRIG:LEV -8.04") in backend.events
    assert meter.acquire_power(mode="gated_average").settings == configured


def test_rs_internal_trigger_is_dbm_and_does_not_enable_or_repurpose_trigger_output():
    state = {
        **_RS_VERIFIED,
        "TRIG:SOUR?": "INT",
        "TRIG:SLOP?": "POS",
        "TRIG:LEV?": "-20",
        "TRIG:LEV:UNIT?": "DBM",
        "TRIG:SEND:STAT?": "1",
        "TRIG:DEL?": "0",
        "TRIG:DEL:AUTO?": "0",
    }
    backend = _VerifiedTranscript(state)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentConfigurationError, match="Disable the trigger sender"):
        meter.configure_power(frequency_hz=2.4e9, trigger_source="internal", trigger_level_dbm=-20)
    assert backend.events == [("connect", ""), ("query", "TRIG:SEND:STAT?")]
    backend.responses = {**state, "TRIG:SEND:STAT?": "0"}
    configured = meter.configure_power(
        frequency_hz=2.4e9, trigger_source="internal", trigger_level_dbm=-20
    )
    level = backend.events.index(("write", "TRIG:LEV -20"))
    assert backend.events[level - 1] == ("write", "TRIG:LEV:UNIT DBM")
    assert configured.trigger_source == "internal" and configured.trigger_level_dbm == -20
    assert meter.acquire_power().settings == configured


@pytest.mark.parametrize(
    ("profile", "responses", "code"),
    [
        ("keysight/U2000A_PM", _ZERO_KEY, 0),
        ("rohdeschwarz/NRP18AN", _ZERO_RS, 1),
    ],
)
def test_sensor_self_test_checks_identity_and_exposes_native_result(profile, responses, code):
    backend = _VerifiedTranscript({**responses, "*TST?": str(code)})
    meter = PowerMeter(load_device_profile(profile), backend)
    result = meter.run_self_test()
    assert isinstance(result, InstrumentSelfTestResult)
    assert result.code == code and result.passed is (code == 0)
    assert result.raw_response == str(code)
    assert result.channel == 1
    assert (result.model, result.serial_number) == tuple(responses["*IDN?"].split(",")[1:3])
    assert result.completed_at_utc.tzinfo is UTC
    assert backend.events[1] == ("query", "*IDN?")
    assert backend.events[-1] == ("query", "*TST?")
    assert not any(
        command == "SYST:ERR?" or action == "write" for action, command in backend.events
    )


@pytest.mark.parametrize(
    ("replies", "reason"),
    [
        ({"*IDN?": "Keysight Technologies,U2000B,OTHER,A1.04.01"}, "identity"),
        ({"STAT:OPER:TRIG:COND?": "+2"}, "idle sensor"),
    ],
)
def test_run_self_test_does_not_dispatch_to_a_mismatched_or_busy_sensor(replies, reason):
    backend = _VerifiedTranscript({**_ZERO_KEY, **replies})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentConfigurationError, match=reason):
        meter.run_self_test()
    assert ("query", "*TST?") not in backend.events
    assert not any(action == "write" for action, _ in backend.events)


@pytest.mark.parametrize(
    ("timeout", "error", "reason"),
    [
        (False, InstrumentDataError, "Invalid sensor self-test result"),
        (True, InstrumentCommunicationError, "missing trigger"),
    ],
)
def test_unresolved_self_test_is_quarantined_even_after_a_device_clear(timeout, error, reason):
    class _ClearableSelfTest(_VerifiedTranscript):
        def device_clear(self):
            self.events.append(("clear", "device"))
            self.failure_on = None

    backend = _ClearableSelfTest({**_ZERO_KEY, "*TST?": "UNFINISHED"})
    backend.failure_on = "*TST?" if timeout else None
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(error, match=reason) as failure:
        meter.run_self_test(timeout_ms=200)
    assert backend.events[-2:] == [("query", "*TST?"), ("clear", "device")]
    assert backend.timeout == 35_000
    assert any("self-test" in note for note in failure.value.__notes__)
    with pytest.raises(InstrumentCommunicationError, match="self-test outcome is uncertain"):
        meter.read_power_trigger_state()


@pytest.mark.parametrize("buffered", [False, True])
def test_rs_verified_acquisition_will_not_arm_while_trigger_sender_is_enabled(buffered):
    replies = (
        {
            **_BUFFER,
            "TRIG:SOUR?": "EXT2",
            "TRIG:DEL?": "0",
            "TRIG:DEL:AUTO?": "0",
        }
        if buffered
        else _RS_VERIFIED
    )
    backend = _VerifiedTranscript({**replies, "TRIG:SEND:STAT?": "1"})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    acquire = meter.acquire_power_buffer if buffered else meter.acquire_power
    with pytest.raises(InstrumentConfigurationError, match="Disable the trigger sender"):
        acquire()
    assert ("query", "TRIG:SEND:STAT?") in backend.events
    assert not any(kind == "write" for kind, _ in backend.events)


def test_rs_sync_is_guarded_only_for_immediate_initiation():
    replies = {**_RS_VERIFIED, "TRIG:SYNC:STAT?": "1"}
    backend = _VerifiedTranscript(replies)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentConfigurationError, match="Disable immediate trigger sync"):
        meter.acquire_power()
    assert ("query", "TRIG:SYNC:STAT?") in backend.events
    assert not any(kind == "write" for kind, _ in backend.events)

    backend.events.clear()
    backend.responses = {
        **replies,
        "TRIG:SOUR?": "EXT2",
        "TRIG:DEL?": "0",
        "TRIG:DEL:AUTO?": "0",
    }
    assert meter.acquire_power().settings.trigger_source == "external_2"
    assert ("query", "TRIG:SYNC:STAT?") not in backend.events


class _CorrectionTranscript(_VerifiedTranscript):
    def __init__(self, responses):
        super().__init__(responses)
        self.responses = dict(responses)
        self.ignore_selection = False

    def write(self, command):
        super().write(command)
        key, value = command.rsplit(" ", 1)
        if self.ignore_selection and key.endswith("SPD:SEL"):
            return
        if key == "SENS1:SGAM:PHAS":
            value = str((float(value) + 180) % 360 - 180)
        if key == "SENS1:CORR:GAIN2":
            self.responses["SENS1:CORR:GAIN2:STAT?"] = "1"
        self.responses[key + "?"] = value


@pytest.mark.parametrize(
    ("key", "responses", "vendor", "limit", "native_db"),
    [
        ("keysight/U2000A_PM", {**_ZERO_KEY, "SENS1:MRAT?": "DOUB"}, "GAIN2", 100, -12.5),
        ("rohdeschwarz/NRP18AN", _ZERO_RS, "OFFS", 200, 12.5),
    ],
)
def test_fixed_offset_roundtrips_native_sign_without_touching_other_corrections(
    key, responses, vendor, limit, native_db
):
    backend = _CorrectionTranscript(responses)
    meter = PowerMeter(load_device_profile(key), backend)
    with pytest.raises(ValueError, match="Provide offset_db"):
        meter.configure_power_offset(enabled=True)
    with pytest.raises(InstrumentParameterError):
        meter.configure_power_offset(enabled=True, offset_db=limit + 1)
    assert not backend.events

    result = meter.configure_power_offset(enabled=True, offset_db=native_db)
    assert result.enabled and result.offset_db == native_db
    assert backend.events[1] == ("query", "*IDN?")
    assert [command for kind, command in backend.events if kind == "write"] == [
        f"SENS1:CORR:{vendor} {native_db}",
        f"SENS1:CORR:{vendor}:STAT ON",
    ]

    backend.events.clear()
    disabled = meter.configure_power_offset(enabled=False)
    assert not disabled.enabled and disabled.offset_db == native_db
    assert [command for kind, command in backend.events if kind == "write"] == [
        f"SENS1:CORR:{vendor}:STAT OFF"
    ]


def test_correction_setup_refuses_busy_or_wrong_sensor_before_writing():
    backend = _CorrectionTranscript({**_ZERO_RS, "STAT:OPER:MEAS:COND?": "2"})
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentConfigurationError, match="idle"):
        meter.configure_power_offset(enabled=True, offset_db=-3)
    assert not any(kind == "write" for kind, _ in backend.events)
    backend.events.clear()
    backend.responses["*IDN?"] = "Rohde&Schwarz,NRP18SN,123456,03.50"
    with pytest.raises(InstrumentConfigurationError, match="identity"):
        meter.configure_power_offset(enabled=True, offset_db=-3)
    assert backend.events == [("query", "*IDN?")]
    backend.events.clear()
    backend.responses["*IDN?"] = "OtherVendor,NRP18AN,123456,03.50"
    with pytest.raises(InstrumentConfigurationError, match="manufacturer"):
        meter.configure_power_offset(enabled=True, offset_db=3)
    assert backend.events == [("query", "*IDN?")]


@pytest.mark.parametrize("enabled", [False, True])
def test_keysight_offset_fast_rate_refusal_does_not_modify_native_value(enabled):
    initial = {**_ZERO_KEY, "SENS1:MRAT?": "FAST", "SENS1:CORR:GAIN2?": "5"}
    backend = _CorrectionTranscript(initial)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentConfigurationError, match="Normal or Double rate"):
        meter.configure_power_offset(enabled=enabled, offset_db=-3 if enabled else None)
    assert ("query", "SENS1:MRAT?") in backend.events
    assert not any(kind == "write" for kind, _ in backend.events)
    assert backend.responses["SENS1:CORR:GAIN2?"] == "5"


def test_s_parameter_correction_never_enables_until_selected_index_matches():
    backend = _CorrectionTranscript(
        {**_ZERO_RS, "SENS1:CORR:SPD:STAT?": "1", "SENS1:CORR:SPD:SEL?": "1"}
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    backend.ignore_selection = True
    with pytest.raises(InstrumentConfigurationError, match="requested S-parameter"):
        meter.configure_power_s_parameter(enabled=True, data_set=3)
    assert backend.responses["SENS1:CORR:SPD:STAT?"] == "OFF"
    assert ("write", "SENS1:CORR:SPD:STAT ON") not in backend.events
    backend.ignore_selection = False
    backend.events.clear()

    result = meter.configure_power_s_parameter(enabled=True, data_set=3)
    assert result.enabled and result.data_set == 3
    off = backend.events.index(("write", "SENS1:CORR:SPD:STAT OFF"))
    select = backend.events.index(("write", "SENS1:CORR:SPD:SEL 3"))
    check = backend.events.index(("query", "SENS1:CORR:SPD:SEL?"))
    on = backend.events.index(("write", "SENS1:CORR:SPD:STAT ON"))
    assert off < select < check < on


def test_source_reflection_accepts_equivalent_phase_and_verifies_known_coefficient():
    backend = _CorrectionTranscript(_ZERO_RS)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(ValueError, match="Provide magnitude and phase"):
        meter.configure_power_source_reflection(enabled=True, magnitude=0.25)
    with pytest.raises(InstrumentParameterError):
        meter.configure_power_source_reflection(enabled=True, magnitude=1.05, phase_deg=0)
    assert not backend.events

    result = meter.configure_power_source_reflection(enabled=True, magnitude=0.25, phase_deg=190)
    assert result.enabled and result.magnitude == 0.25 and result.phase_deg == -170
    assert ("write", "SENS1:SGAM:PHAS 190") in backend.events
    last_programming = backend.events.index(("write", "SENS1:SGAM:CORR:STAT ON"))
    assert ("query", "SENS1:SGAM:PHAS?") in backend.events[:last_programming]
    assert meter.read_power_source_reflection() == result
    disabled = meter.configure_power_source_reflection(enabled=False)
    assert not disabled.enabled
    assert (disabled.magnitude, disabled.phase_deg) == (0.25, -170)


@pytest.mark.parametrize("shifted", [False, True])
def test_input_reflection_has_sensor_reported_uncertainty_and_reference_plane(shifted):
    backend = _VerifiedTranscript(
        {
            **_RS_VERIFIED,
            "SENS1:CORR:SPD:STAT?": "1" if shifted else "0",
            "SENS1:CORR:SPD:SEL?": "3",
            "SENS1:IGAM:MAGN?": "1.739179E-02",
            "SENS1:IGAM:PHAS?": "-1.327654E+02",
            "SENS1:IGAM:EUNC?": "5.000000E-03",
        }
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    result = meter.read_power_input_reflection()
    assert result.magnitude == pytest.approx(0.01739179)
    assert result.phase_deg == pytest.approx(-132.7654)
    assert (
        result.expanded_magnitude_uncertainty == 0.005 and result.uncertainty_coverage_factor == 2
    )
    assert result.frequency_hz == 2.4e9
    assert result.reference_plane == ("s_parameter_device_input" if shifted else "sensor_input")
    assert result.s_parameter_set == (3 if shifted else None)
    assert not any(kind == "write" for kind, _ in backend.events)
    assert (("query", "SENS1:CORR:SPD:SEL?") in backend.events) is shifted


def test_reflection_reference_plane_change_is_not_returned_as_a_valid_snapshot():
    class _ChangedPlane(_VerifiedTranscript):
        def query(self, command, delay=None):
            if command == "SENS1:IGAM:EUNC?":
                self.responses["SENS1:CORR:SPD:STAT?"] = "0"
            return super().query(command, delay)

    backend = _ChangedPlane(
        {
            **_RS_VERIFIED,
            "SENS1:CORR:SPD:STAT?": "1",
            "SENS1:CORR:SPD:SEL?": "3",
            "SENS1:IGAM:MAGN?": "0.02",
            "SENS1:IGAM:PHAS?": "-20",
            "SENS1:IGAM:EUNC?": "0.005",
        }
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentConfigurationError, match="reference plane or frequency changed"):
        meter.read_power_input_reflection()


def test_rs_reference_plane_operations_are_not_advertised_on_keysight():
    backend = _VerifiedTranscript({})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    offset = meter.describe_operation("configure_power_offset")
    assert offset["group"] == "correction" and offset["scope"] == "family"
    for op in (
        "configure_power_s_parameter",
        "configure_power_source_reflection",
        "read_power_source_reflection",
        "read_power_input_reflection",
    ):
        spec = meter.describe_operation(op)
        assert spec["group"] == "correction" and spec["scope"] == "model"
        assert not spec["support"]["supported"]
    assert not backend.events


class _TimingTranscript(_TraceTranscript):
    def __init__(self, responses, *, keysight=False):
        super().__init__(responses)
        self.responses = dict(responses)
        self.keysight = keysight

    def write(self, command):
        super().write(command)
        name, sep, value = command.partition(" ")
        if sep and name in {
            "TRIG:DEL:AUTO",
            "TRIG:DEL",
            "TRIG:SEQ:HOLD",
            "TRIG:SEQ:HYST",
            "TRIG:HOLD",
            "TRIG:HYST",
            "TRIG:DTIM",
        }:
            if self.keysight and name in {"TRIG:DEL", "TRIG:SEQ:HOLD"}:
                value = str(round(float(value), 6))
            if self.keysight and name == "TRIG:SEQ:HYST":
                value = str(round(float(value), 1))
            self.responses[name + "?"] = value


@pytest.mark.parametrize("trace", [False, True])
def test_key_timing_accepts_supported_quantization_and_references_window_to_detected_edge(trace):
    responses = {
        **(_TRACE if trace else _GATED),
        **_IDLE,
        "*IDN?": _ZERO_KEY["*IDN?"],
        "TRIG:SEQ:HOLD?": "1e-6",
    }
    backend = _TimingTranscript(responses, keysight=True)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    result = meter.configure_power_trigger_timing(delay_s=-50.3e-6, holdoff_s=75.4e-6)
    assert result.source == "external"
    assert result.delay_s == -50e-6 and result.holdoff_s == 75e-6
    assert result.delay_auto is False
    assert result.hysteresis_db is None and result.dropout_s is None
    assert [command for kind, command in backend.events if kind == "write"] == [
        "TRIG:DEL:AUTO OFF",
        "TRIG:DEL -5.03e-05",
        "TRIG:SEQ:HOLD 7.54e-05",
    ]
    assert meter.read_power_trigger_timing() == result
    if trace:
        capture = meter.acquire_power_trace()
        assert capture.settings.trigger_delay_s == -50e-6
        assert capture.settings.time_window_s == pytest.approx((-80e-6, 20e-6))
    else:
        capture = meter.acquire_power(mode="gated_average")
        assert capture.settings.trigger_delay_s == -50e-6
        assert capture.settings.gate_window_s == pytest.approx((150e-6, 550e-6))


def test_trigger_hysteresis_and_dropout_are_model_and_source_specific():
    backend = _TimingTranscript({**_ZERO_KEY, "TRIG:SOUR?": "EXT"}, keysight=True)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentParameterError, match="dropout-time"):
        meter.configure_power_trigger_timing(dropout_s=0.1)
    assert not backend.events
    with pytest.raises(InstrumentConfigurationError, match="require an internal RF trigger"):
        meter.configure_power_trigger_timing(hysteresis_db=1)
    assert not any(kind == "write" for kind, _ in backend.events)

    backend = _TimingTranscript(
        {
            **_ZERO_RS,
            "TRIG:SOUR?": "INT",
            "TRIG:SLOP?": "NEG",
            "TRIG:DEL:AUTO?": "1",
            "TRIG:DEL?": "0",
            "TRIG:HOLD?": "0",
            "TRIG:HYST?": "0",
            "TRIG:DTIM?": "0",
        }
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentParameterError):
        meter.configure_power_trigger_timing(delay_s=-0.1)
    assert not backend.events
    result = meter.configure_power_trigger_timing(
        holdoff_s=0.02, hysteresis_db=2.5, dropout_s=0.004
    )
    assert (result.source, result.edge, result.delay_auto) == ("internal", "falling", True)
    assert (result.holdoff_s, result.hysteresis_db, result.dropout_s) == (0.02, 2.5, 0.004)
    assert [cmd for kind, cmd in backend.events if kind == "write"] == [
        "TRIG:HOLD 0.02",
        "TRIG:HYST 2.5",
        "TRIG:DTIM 0.004",
    ]


def test_r_s_delay_integrates_with_external_buffer_without_changing_outputs():
    backend = _TimingTranscript(
        {
            **_BUFFER,
            **_IDLE,
            "*IDN?": _ZERO_RS["*IDN?"],
            "TRIG:SOUR?": "EXT2",
            "TRIG:DEL?": "0",
            "TRIG:DEL:AUTO?": "1",
            "TRIG:HOLD?": "0",
        }
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    timing = meter.configure_power_trigger_timing(delay_s=0.25)
    assert timing.source == "external_2" and timing.delay_auto is False
    assert timing.delay_s == 0.25 and timing.edge is None
    assert meter.read_power_trigger_timing() == timing
    capture = meter.acquire_power_buffer()
    assert capture.settings.trigger_delay_s == 0.25
    assert capture.settings.trigger_edge is None
    assert not any(command.startswith("TRIG:SLOP") for _, command in backend.events)
    assert not any(
        kind == "write" and command.startswith(("TRIG:SEND", "TRIG:SYNC", "TRIG:SOUR"))
        for kind, command in backend.events
    )


def test_trigger_timing_does_not_set_any_field_while_armed():
    backend = _TimingTranscript({**_ZERO_KEY, "STAT:OPER:TRIG:COND?": "2"})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    with pytest.raises(InstrumentConfigurationError, match="idle"):
        meter.configure_power_trigger_timing(delay_s=0.01)
    assert not any(kind == "write" for kind, _ in backend.events)


def test_key_internal_trigger_hysteresis_returns_actual_quantized_value():
    backend = _TimingTranscript(
        {
            **_ZERO_KEY,
            "TRIG:SOUR?": "INT",
            "TRIG:SLOP?": "POS",
            "TRIG:DEL?": "0",
            "TRIG:DEL:AUTO?": "0",
            "TRIG:SEQ:HOLD?": "1e-6",
            "TRIG:SEQ:HYST?": "0",
        },
        keysight=True,
    )
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    setup = meter.describe_operation("configure_power_trigger_timing")
    assert setup["group"] == "trigger" and setup["scope"] == "family"
    timing = meter.configure_power_trigger_timing(hysteresis_db=1.54)
    assert timing.hysteresis_db == 1.5
    assert [(kind, cmd) for kind, cmd in backend.events if kind == "write"] == [
        ("write", "TRIG:SEQ:HYST 1.54")
    ]


def test_rs_smb_trigger_reports_no_edge_and_never_uses_slope_command():
    backend = _VerifiedTranscript(
        {**_RS_VERIFIED, "TRIG:SOUR?": "EXT2", "TRIG:DEL?": "0", "TRIG:DEL:AUTO?": "0"}
    )
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    for edge in ("rising", "falling"):
        with pytest.raises(ValueError, match="trigger_edge is not available"):
            meter.configure_power(
                frequency_hz=2.4e9, trigger_source="external_2", trigger_edge=edge
            )
    assert not backend.events
    configured = meter.configure_power(frequency_hz=2.4e9, trigger_source="external_2")
    assert configured.trigger_source == "external_2" and configured.trigger_edge is None
    assert ("write", "TRIG:SOUR EXT2") in backend.events
    assert meter.read_power_settings() == configured
    assert meter.acquire_power().settings == configured
    assert not any(command.startswith("TRIG:SLOP") for _, command in backend.events)


class _ScopedPowerTranscript(_VerifiedTranscript):
    def __init__(self, responses):
        super().__init__({**responses, **_IDLE})
        self.armed = False
        self.complete = False
        self.readiness_polls = 0
        self.never_ready = False
        self.trigger_count = int(responses.get("TRIG:COUN?", "1"))

    def write(self, command):
        super().write(command)
        if command == "ABOR":
            self.armed = False
            self.complete = False
        if command == "INIT" and not self.error_on_init:
            self.armed = True
            self.complete = False
            self.readiness_polls = 0
            self.stale_fetch = True

    def query(self, command, delay=None):
        if command == "STAT:OPER:TRIG:COND?":
            self.events.append(("query", command))
            if not self.armed:
                return "0"
            self.readiness_polls += 1
            return "2" if self.readiness_polls >= 2 and not self.never_ready else "4"
        if command == "*OPC?" and not self.complete:
            self.events.append(("query", command))
            raise TimeoutError("No trigger completed this arm.")
        return super().query(command, delay)

    def deliver_triggers(self, count):
        assert self.armed and self.readiness_polls >= 2
        self.events.append(("external", f"{count} trigger(s)"))
        if count == self.trigger_count:
            self.armed = False
            self.complete = True
            self.stale_fetch = False

    def device_clear(self):
        self.events.append(("clear", "device"))
        self.armed = False


_SCOPED_SCALAR = {
    **_RS_VERIFIED,
    "TRIG:SOUR?": "EXT1",
    "TRIG:SLOP?": "POS",
    "TRIG:DEL?": "0",
    "TRIG:DEL:AUTO?": "0",
}
_SCOPED_BUFFER = {
    **_BUFFER,
    "TRIG:SOUR?": "EXT2",
    "TRIG:DEL?": "0",
    "TRIG:DEL:AUTO?": "0",
}


@pytest.mark.parametrize("buffered", [False, True])
def test_scoped_power_arm_observes_live_readiness_before_separate_source(monkeypatch, buffered):
    backend = _ScopedPowerTranscript(_SCOPED_BUFFER if buffered else _SCOPED_SCALAR)
    registry.ensure_builtin_registrations()
    monkeypatch.setattr(registry, "_backends", registry._backends.copy())
    register_backend("rf_power_armed_test", lambda _: backend)
    descriptor = {
        "bench_name": "Ready power transcript",
        "instruments": {
            "rf_meter": {
                "profile": "rohdeschwarz/NRP18AN",
                "address": "TCPIP::192.0.2.10::INSTR",
                "backend": {"type": "rf_power_armed_test"},
            },
        },
    }
    with Bench.open(descriptor, aliases={"rf_meter"}, start_experiment=False) as bench:
        meter = bench.rf_meter
        operation = meter.describe_operation("arm_power")
        assert operation["support"]["supported"]
        assert (operation["group"], operation["scope"]) == ("trigger", "model")
        with meter.arm_power(mode="buffered_average" if buffered else "average") as armed:
            assert armed.ready_at_utc.tzinfo is UTC
            assert backend.readiness_polls == 2
            assert not any(command.startswith(("FETC", "*OPC?")) for _, command in backend.events)
            with pytest.raises(InstrumentConfigurationError, match="active power arm handle"):
                meter.read_power_trigger_state()
            backend.deliver_triggers(3 if buffered else 1)
            result = armed.fetch()
            with pytest.raises(RuntimeError, match="no longer available"):
                armed.fetch()
        with pytest.raises(RuntimeError, match="no longer available"):
            armed.fetch()

    assert isinstance(result, PowerBuffer if buffered else PowerAcquisition)
    assert result.settings.trigger_source == ("external_2" if buffered else "external_1")
    assert result.received_at_utc >= armed.ready_at_utc
    arm = backend.events.index(("write", "INIT"))
    edge = backend.events.index(("external", f"{3 if buffered else 1} trigger(s)"))
    finish = backend.events.index(("query", "*OPC?"))
    assert arm < edge < finish
    assert backend.events[arm + 1 : edge] == [
        ("query", "SYST:ERR?"),
        ("query", "STAT:OPER:TRIG:COND?"),
        ("query", "STAT:OPER:TRIG:COND?"),
    ]
    assert not any(action == "clear" for action, _ in backend.events)


def test_scoped_power_aborts_if_caller_leaves_without_fetch_and_preserves_error():
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(RuntimeError, match="separate trigger controller failed"):
        with meter.arm_power() as armed:
            assert backend.armed
            raise RuntimeError("separate trigger controller failed")
    assert not backend.armed
    assert [event for event in backend.events if event == ("write", "ABOR")] == [
        ("write", "ABOR"),
        ("write", "ABOR"),
    ]
    assert backend.events[-1] == ("query", "STAT:OPER:TRIG:COND?")
    assert not any(command.startswith(("FETC", "*OPC?")) for _, command in backend.events)
    with pytest.raises(RuntimeError, match="no longer available"):
        armed.fetch()


def test_scoped_power_failed_fetch_uses_clear_even_when_caller_catches_error():
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with meter.arm_power() as armed:
        with pytest.raises(InstrumentCommunicationError, match="No trigger completed"):
            armed.fetch()
        with pytest.raises(RuntimeError, match="no longer available"):
            armed.fetch()
    assert backend.events[-2:] == [("query", "*OPC?"), ("clear", "device")]
    assert not backend.armed
    assert not any(command.startswith("FETC") for _, command in backend.events)


def test_scoped_power_requires_readiness_and_never_accepts_init_ack_alone():
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    backend.never_ready = True
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with (
        pytest.raises(InstrumentCommunicationError, match="timeout"),
        meter.arm_power(timeout_ms=60),
    ):
        pytest.fail("The context must not yield without observing wait-for-trigger.")
    assert ("write", "INIT") in backend.events
    assert backend.events[-1] == ("clear", "device")
    assert not any(command.startswith(("FETC", "*OPC?")) for _, command in backend.events)


def test_scoped_power_refuses_init_rejection_and_requires_external_source():
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    backend.error_on_init = True
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentCommunicationError, match="Init ignored"), meter.arm_power():
        pytest.fail("A rejected INIT must not yield an armed handle.")
    assert not any(command.startswith(("FETC", "*OPC?")) for _, command in backend.events)

    backend = _ScopedPowerTranscript(_RS_VERIFIED)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentConfigurationError, match="EXT1 or EXT2"), meter.arm_power():
        pytest.fail("An immediate acquisition has no external ready barrier.")
    assert not any(action == "write" for action, _ in backend.events)


def test_scoped_power_is_not_inferred_on_the_keysight_profile():
    backend = _VerifiedTranscript({})
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    assert not meter.describe_operation("arm_power")["support"]["supported"]
    assert not backend.events


def test_scoped_power_never_accepts_completion_token_while_still_armed():
    class _EarlyCompletion(_ScopedPowerTranscript):
        def query(self, command, delay=None):
            if command == "*OPC?":
                self.events.append(("query", command))
                return "1"
            return super().query(command, delay)

    backend = _EarlyCompletion(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with meter.arm_power() as armed:
        with pytest.raises(InstrumentConfigurationError, match="Scoped fetch requires an idle"):
            armed.fetch()
    assert backend.events[-1] == ("clear", "device")
    assert not any(command.startswith("FETC") for _, command in backend.events)


def test_scoped_power_handle_cannot_do_transport_work_from_another_thread():
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with meter.arm_power() as armed, ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(armed.fetch)
        with pytest.raises(RuntimeError, match="thread that owns"):
            future.result(timeout=1)
        backend.deliver_triggers(1)
        assert isinstance(armed.fetch(), PowerAcquisition)


def test_scoped_power_failed_abort_preserves_caller_failure_and_quarantines_without_clear():
    class _AbortFailed(_ScopedPowerTranscript):
        device_clear = None

        def write(self, command):
            if command == "ABOR" and self.armed:
                self.events.append(("write", command))
                raise TimeoutError("abort failed")
            return super().write(command)

    backend = _AbortFailed(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(RuntimeError, match="trigger client failed") as failure:
        with meter.arm_power():
            raise RuntimeError("trigger client failed")
    assert any("Could not verify scoped power abort" in note for note in failure.value.__notes__)
    assert any("reopen the bench" in note for note in failure.value.__notes__)
    last_events = list(backend.events)
    with pytest.raises(InstrumentCommunicationError, match="device clear"):
        meter.acquire_power()
    assert backend.events == last_events


def test_scoped_power_blocks_same_object_reentrant_abort_and_maintenance():
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with meter.arm_power() as arm:
        events = list(backend.events)
        for bypass in (
            lambda: meter.write("ABOR"),
            lambda: meter.query("ABOR;*OPC?"),
            lambda: meter.query_raw("ABOR;FETC1:POW:AVG?"),
            meter.read,
            meter.read_raw,
            meter.read_status_byte,
            meter.reset,
            meter.clear_status,
            meter.get_error,
            meter.run_self_test,
            meter.attempt_error_recovery,
            meter.close,
        ):
            with pytest.raises(InstrumentConfigurationError, match="active power arm handle"):
                bypass()
        assert backend.events == events
        backend.deliver_triggers(1)
        result = arm.fetch()
        assert isinstance(result, PowerAcquisition)
        assert result.value != 123.0  # Prior memory in this fake is deliberately plausible.

    assert meter.query("*OPC?") == "1"
    meter.write("ABOR")
    assert backend.events[-2:] == [("query", "*OPC?"), ("write", "ABOR")]


def test_scoped_power_reentrant_abort_attempt_never_causes_a_stale_fetch():
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with pytest.raises(InstrumentConfigurationError, match="active power arm handle"):
        with meter.arm_power() as arm:
            meter.write("ABOR")
            arm.fetch()
    assert [cmd for action, cmd in backend.events if action == "write"] == ["ABOR", "INIT", "ABOR"]
    assert not any(command.startswith(("FETC", "*OPC?")) for _, command in backend.events)


def test_scoped_power_overlong_caller_work_takes_verified_abort_without_query_or_clear(monkeypatch):
    now = 0.0
    implementation = import_module("pytestlab.instruments.PowerMeter")
    monkeypatch.setattr(implementation, "monotonic", lambda: now)
    backend = _ScopedPowerTranscript(_SCOPED_SCALAR)
    meter = PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend)
    with meter.arm_power(timeout_ms=100) as arm:
        now = 0.5
        with pytest.raises(InstrumentCommunicationError, match="SCPI I/O timeout"):
            arm.fetch()
        with pytest.raises(RuntimeError, match="no longer available"):
            arm.fetch()
    assert [cmd for action, cmd in backend.events if action == "write"] == ["ABOR", "INIT", "ABOR"]
    assert backend.events[-1] == ("query", "STAT:OPER:TRIG:COND?")
    assert not any(
        cmd.startswith(("FETC", "*OPC?")) or action == "clear" for action, cmd in backend.events
    )


@pytest.mark.parametrize("profile", ["keysight/U2000A_PM", "rohdeschwarz/NRP18AN"])
def test_rf_maintenance_is_excluded_from_generic_and_bulk_operations(profile, monkeypatch):
    backend = _VerifiedTranscript({})
    meter = PowerMeter(load_device_profile(profile), backend)

    def unexpected_service(*args, **kwargs):
        pytest.fail("Generic dispatch must not run RF sensor maintenance")

    monkeypatch.setattr(cli_typer, "_operation_instrument", lambda *args, **kwargs: meter)
    for op in ("zero_sensor", "run_self_test"):
        info = meter.describe_operation(op)
        assert info["support"]["supported"]
        assert info["python_only"]
        assert "input_quiet" not in info["parameters"]
        monkeypatch.setattr(meter, op, unexpected_service)
        result = CliRunner().invoke(cli_typer.app, ["instrument", "execute-operation", profile, op])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error"]["code"] == "python_only_operation"
    assert not backend.events

    operation_rows, *_ = cli_typer._semantic_operation_rows(meter, include_writes=True)
    service = {
        row["alias"]: row["status"]
        for row in operation_rows
        if row["alias"] in {"zero_sensor", "run_self_test"}
    }
    assert service == {"zero_sensor": "skip", "run_self_test": "skip"}


@pytest.mark.parametrize("profile", ["keysight/U2000A_PM", "rohdeschwarz/NRP18AN"])
@pytest.mark.parametrize("include_writes", [False, True])
def test_rf_live_bulk_scpi_omits_native_maintenance(profile, include_writes, monkeypatch):
    meter = PowerMeter(load_device_profile(profile), _VerifiedTranscript({}))
    wire = []

    def capture(command):
        normalized = command.upper()
        if normalized == "*TST?" or (":ZERO:" in normalized and not normalized.endswith("?")):
            pytest.fail(f"Bulk diagnostics issued maintenance transport: {command}")
        wire.append(command)
        return "0"

    monkeypatch.setattr(meter, "query", capture)
    monkeypatch.setattr(meter, "write", capture)
    _, rows, *_ = cli_typer._profile_scpi_command_rows(
        profile, device=meter, include_writes=include_writes, strict_response=True
    )
    by_alias = {row["alias"]: row for row in rows}
    for alias in ("zero_once", "native_power_self_test"):
        assert by_alias[alias]["status"] == "skip"
        assert "direct Python operation" in by_alias[alias]["detail"]
    if profile.startswith("keysight/"):
        assert by_alias["set_zero_type"]["status"] == "skip"
    assert "*IDN?" in wire
    assert by_alias["identify"]["status"] == "ok"
