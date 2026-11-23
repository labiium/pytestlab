import json
from dataclasses import replace
from typing import cast

import polars as pl
import pytest

from pytestlab import MeasurementSession
from pytestlab.config.loader import load_device_profile
from pytestlab.config.spectrum_analyzer_config import SpectrumAnalyzerConfig
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.instruments.SpectrumAnalyser import SpectrumAnalyser
from pytestlab.instruments.SpectrumAnalyser import SpectrumTrace
from pytestlab.instruments.SpectrumAnalyser import SpectrumTraceFrame


class TranscriptBackend:
    def __init__(self, transcript: list[tuple[str, str]]):
        self.transcript = list(transcript)
        self.calls: list[str] = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def query(self, command: str, delay: float | None = None) -> str:
        if command == "SYST:ERR?":
            return '0,"No error"'
        self.calls.append(command)
        expected, result = self.transcript.pop(0)
        assert command == expected
        return result

    def write(self, command: str) -> None:
        raise AssertionError(f"Unexpected settings change: {command}")


def _values(values: list[float]) -> str:
    return ",".join(map(str, values))


def _prefix(mode_cmd: str, *, points: int, span: int, unit: str) -> list[tuple[str, str]]:
    return [
        (mode_cmd, "SAN"),
        ("INIT:CONT?", "0"),
        ("*OPC?", "1"),
        ("FORM:DATA?", "ASC,0"),
        ("FREQ:SPAN?", str(span)),
        ("SWE:POIN?", str(points)),
        ("UNIT:POW?", unit),
    ]


@pytest.mark.parametrize("zero_span", [False, True])
@pytest.mark.parametrize("model", ["keysight/N9000A_SA", "rohdeschwarz/FSW26"])
def test_same_spectrum_api_for_two_vendor_transcripts(model, zero_span, tmp_path):
    points = 101
    # Preserve the instrument's uneven display coordinates, including negative
    # trigger-relative time, rather than generate a linspace from config.
    axis = (
        [-0.001 + i * i * 1e-6 for i in range(points)]
        if zero_span
        else [1.1e9 + i * i * 1000 for i in range(points)]
    )
    amplitude = [-60.0 + i / 10 for i in range(points)]
    keysight = model.startswith("keysight/")
    prefix = _prefix(
        "CONF?" if keysight else "INST:SEL?",
        points=points,
        span=0 if zero_span else 10_000_000,
        unit="DBMV" if zero_span else "DBM",
    )
    transcript = (
        prefix
        + [
            (
                "FETC:SAN2?",
                _values(
                    [component for pair in zip(axis, amplitude, strict=True) for component in pair]
                ),
            )
        ]
        if keysight
        else prefix
        + [
            ("TRAC:DATA:X? TRACE2", _values(axis)),
            ("TRAC:DATA? TRACE2", _values(amplitude)),
        ]
    )
    backend = TranscriptBackend(transcript)
    scope = cast(SpectrumAnalyser, AutoInstrument.from_config(model, backend_override=backend))
    assert scope.supports_operation("get_trace")
    result = scope.get_trace(channel=2)
    assert result.trace == 2
    assert result.acquisition == "held"
    assert result.axis == tuple(axis)
    assert result.amplitudes == tuple(amplitude)
    assert result.axis_kind == ("time" if zero_span else "frequency")
    assert result.axis_unit == ("s" if zero_span else "Hz")
    assert result.amplitude_unit == ("dBmV" if zero_span else "dBm")
    assert result.x == axis
    assert result.y == amplitude
    native = result.to_measurement_result()
    axis_name = "time_s" if zero_span else "frequency_hz"
    assert native.values.schema == {axis_name: pl.Float64, "amplitude": pl.Float64}
    assert native.values[axis_name].to_list() == axis
    assert native.values["amplitude"].to_list() == amplitude
    assert native.envelope["column_units"] == {
        axis_name: result.axis_unit,
        "amplitude": result.amplitude_unit,
    }
    assert native.envelope["uncertainty_status"] == "not_evaluated"
    assert native.envelope["timestamp_kind"] == "host_receipt"
    assert native.envelope["acquisition"] == "held"
    assert native.envelope["axis_source"] == "instrument"
    assert native.envelope["instrument_identity_source"] == "profile_model"
    assert native.instrument == scope.config.model
    assert native.timestamp == result.readout_timestamp == result.to_measurement_result().timestamp
    with MeasurementDatabase(tmp_path / "spectrum") as db:
        key = db.store_measurement(None, result)
        restored = db.retrieve_measurement(key)
    assert restored.values.equals(native.values)
    assert restored.envelope == native.envelope
    assert restored.timestamp == native.timestamp
    with MeasurementSession("spectrum", compliance=False) as session:
        session.parameter("point", [0])

        @session.acquire
        def spectrum():
            return result

        trial = session.run(show_progress=False)
    path = tmp_path / "spectrum.parquet"
    trial.save_parquet(str(path))
    saved = pl.read_parquet(path)
    assert saved["spectrum"][0].struct.unnest().equals(native.values)
    metadata = json.loads(saved["spectrum__measurement"][0])
    assert metadata["result"]["envelope"] == native.envelope
    assert metadata["result"]["timestamp"] == native.timestamp
    assert not backend.transcript


@pytest.mark.parametrize(
    "payload",
    ["1,-42,2", "1,-42,,3", "1,NaN,2,-43", "1,-42,2,9.91e37", "1,-42,1,-43"],
)
def test_invalid_spectrum_trace_never_returns_partial_result(payload):
    transcript = _prefix("CONF?", points=2, span=100, unit="DBM") + [("FETC:SAN1?", payload)]
    analyser = AutoInstrument.from_config(
        "keysight/N9000A_SA", backend_override=TranscriptBackend(transcript)
    )
    with pytest.raises(InstrumentDataError):
        cast(SpectrumAnalyser, analyser).get_trace()


@pytest.mark.parametrize(
    "transcript",
    [
        [("CONF?", "ACP")],
        [("CONF?", "SAN"), ("INIT:CONT?", "1")],
        [("CONF?", "SAN"), ("INIT:CONT?", "0"), ("*OPC?", "0")],
        [("CONF?", "SAN"), ("INIT:CONT?", "0"), ("*OPC?", "1"), ("FORM:DATA?", "REAL,32")],
        _prefix("CONF?", points=40002, span=100, unit="DBM")[:-1],
        _prefix("CONF?", points=2, span=100, unit="UNSUPPORTED"),
    ],
)
def test_invalid_trace_state_fails_before_payload_query(transcript):
    backend = TranscriptBackend(transcript)
    analyser = AutoInstrument.from_config("keysight/N9000A_SA", backend_override=backend)
    with pytest.raises(InstrumentDataError):
        cast(SpectrumAnalyser, analyser).get_trace()
    assert not backend.transcript


def test_readback_requires_complete_profile_contract_before_io():
    config = cast(SpectrumAnalyzerConfig, load_device_profile("keysight/N9000A_SA"))
    config.operation_options.operations["get_trace"].transport.pop("trace_span")
    backend = TranscriptBackend([])
    analyser = SpectrumAnalyser(config, backend)
    with pytest.raises(InstrumentConfigurationError, match="missing the 'trace_span' binding"):
        analyser.get_trace()
    assert not backend.calls


def test_trace_only_profile_does_not_advertise_trusted_readback():
    config = cast(SpectrumAnalyzerConfig, load_device_profile("keysight/N9000A_SA"))
    config.trace_readback = None
    backend = TranscriptBackend([])
    analyser = SpectrumAnalyser(config, backend)
    assert not analyser.supports_operation("get_trace")
    with pytest.raises(InstrumentConfigurationError, match="does not implement"):
        analyser.get_trace()
    assert not backend.calls


def test_caller_created_spectrum_results_do_not_claim_a_driver_capture():
    trace = SpectrumTrace(2, (12.0, 13.0), (-40.0, -35.0), "frequency", "dBm", "fresh")
    result = trace.to_measurement_result()
    assert result.envelope["acquisition"] == "unknown"
    assert result.envelope["capture_origin"] == "caller"
    assert result.envelope["axis_source"] == "caller_supplied"
    assert result.envelope["timestamp_kind"] == "conversion_time"
    assert trace.peak().to_measurement_result().envelope["source_acquisition"] is None
    frame = SpectrumTraceFrame(
        (trace, replace(trace, trace=1, axis=(12.0, 14.0))),
        trace.axis,
        trace.axis_unit,
        trace.amplitude_unit,
    )
    with pytest.raises(ValueError, match="same axis"):
        frame.to_measurement_result()
