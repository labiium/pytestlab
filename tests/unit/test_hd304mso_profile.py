from __future__ import annotations

import pytest

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.scpi_engine import ValidationError


def _ascii_binblock(payload: str) -> bytes:
    encoded = payload.encode("ascii")
    length = str(len(encoded)).encode("ascii")
    return b"#" + str(len(length)).encode("ascii") + length + encoded + b"\n"


def test_hd304mso_profile_declares_every_oscilloscope_operation_alias() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    assert scope.config.memory == 20_000_000
    assert scope.config.sampling_rate == 3_200_000_000

    report = scope.validate_operation_contract(include_unsupported=True)

    assert report["frequency_response_analysis"]["supported"] is True
    assert report["frequency_response_analysis"]["missing_parameters"] == []


def test_hd304mso_profile_uses_documented_core_commands() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    assert scope._scpi_engine.build("set_channel_coupling", channel=1, coupling="DC") == [
        ":CHANnel1:COUPling DC"
    ]
    assert scope._scpi_engine.build("set_trigger_coupling", mode="EDGE", coupling="DC") == [
        ":TRIGger:EDGE:COUPling DC"
    ]
    assert scope._scpi_engine.build("acq_set_mode", value="RTIMe") == [":ACQuire:MODE RTIMe"]
    assert scope._scpi_engine.build("set_wave_points_max") == [":WAVeform:POINts:MODE MAXimum"]
    assert scope._scpi_engine.build("screenshot") == [":DISPlay:DATA? PNG"]
    assert scope._scpi_engine.build("system_lock", state="ON") == [":SYSTem:LOCK ON"]


def test_hd304mso_profile_maps_fft_wavegen_and_fra_tokens() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    assert scope._scpi_engine.build("fft_window", window="Blackman-Harris") == [
        ":FFT:WINDow BHARris"
    ]
    assert scope._scpi_engine.build("fft_vtype", units="dBm") == [":FFT:VTYPe DECibel"]
    assert scope._scpi_engine.build("wgen_set_func", func="SIN") == [":WGEN:FUNCtion SINusoid"]
    assert scope._scpi_engine.build("wgen_set_freq", frequency=1_000.0) == [
        ":WGEN:FREQuency 1000.0"
    ]
    assert scope._scpi_engine.build("fran_load", value="onemeg") == [":FRANalysis:WGEN:LOAD ONEMeg"]


def test_acquisition_type_maps_hd_numeric_status_values(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    assert scope._scpi_engine.describe("acq_get_type")["response"]["numeric_map"] == {
        "0": "NORMAL",
        "1": "PEAK",
        "2": "AVERAGE",
    }

    monkeypatch.setattr(scope, "_query", lambda _query: "0")
    assert scope.acquisition.get_acquisition_type() == "NORMAL"

    monkeypatch.setattr(scope, "_query", lambda _query: "+1")
    assert scope.acquisition.get_acquisition_type() == "PEAK"

    monkeypatch.setattr(scope, "_query", lambda _query: "2")
    assert scope.acquisition.get_acquisition_type() == "AVERAGE"


def test_trigger_mode_is_profile_validated_before_scpi_interpolation() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    with pytest.raises(ValidationError):
        scope._scpi_engine.build(
            "set_trigger_coupling",
            mode="EDGE;:OUTPut ON",
            coupling="DC",
        )

    with pytest.raises(InstrumentParameterError):
        scope.configure_trigger(
            channel=1,
            level=0.0,
            source="CHAN1",
            mode="EDGE;:OUTPut ON",
        )


def test_probe_readback_accepts_keysight_numeric_status_suffix(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    monkeypatch.setattr(scope, "_query", lambda _query: "1.00000E+00,RAT")

    assert scope.get_probe_attenuation(1) == "1:1"


def test_franalysis_sweep_binds_sources_runs_before_fetch_and_disables(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)
    commands: list[str] = []

    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(
        scope,
        "_query_raw",
        lambda _query: _ascii_binblock("100,1,0,0\n1000,1,0,0\n"),
    )

    result = scope.franalysis_sweep(
        input_channel=1,
        output_channel=2,
        start_freq=100,
        stop_freq=1000,
        amplitude=1,
        points=2,
    )

    assert commands[:2] == [
        ":FRANalysis:ENABle ON",
        ":FRANalysis:SOURce:INPut CHANnel1",
    ]
    assert ":FRANalysis:SOURce:OUTPut CHANnel2" in commands
    assert ":FRANalysis:RUN" in commands
    assert commands[-1] == ":FRANalysis:ENABle OFF"
    assert result.values.columns == [
        "Frequency (Hz)",
        "Amplitude (Vpp)",
        "Gain (dB)",
        "Phase (deg)",
    ]


def test_franalysis_sweep_reports_malformed_binary_response(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    monkeypatch.setattr(scope, "_send_command", lambda _command: None)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query_raw", lambda _query: b"not-a-binary-block")

    with pytest.raises(InstrumentDataError, match="Invalid FRA binary response"):
        scope.franalysis_sweep(
            input_channel=1,
            output_channel=2,
            start_freq=100,
            stop_freq=1000,
            amplitude=1,
            points=2,
        )


def test_franalysis_legacy_two_column_payload_is_not_inferred_as_four_columns(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    monkeypatch.setattr(scope, "_send_command", lambda _command: None)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query", lambda _query: "100,1,1000,2")
    monkeypatch.setattr(scope._scpi_engine, "describe", lambda _alias: {"response": {"fields": []}})

    result = scope.franalysis_sweep(
        input_channel=1,
        output_channel=2,
        start_freq=100,
        stop_freq=1000,
        amplitude=1,
        points=2,
    )

    assert result.values.columns == ["Frequency (Hz)", "Magnitude"]
