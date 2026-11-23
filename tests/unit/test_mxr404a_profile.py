from __future__ import annotations

from pytestlab import AutoInstrument
from pytestlab.common.enums import TriggerSlope


def _ascii_binblock(payload: str) -> bytes:
    encoded = payload.encode("ascii")
    length = str(len(encoded)).encode("ascii")
    return b"#" + str(len(length)).encode("ascii") + length + encoded + b"\n"


def test_mxr404a_profile_exposes_core_scpi_aliases():
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)

    assert scope.config.fft is not None
    assert scope.config.function_generator is not None
    assert scope.config.trigger.slopes == ["POS", "NEG", "EITH"]
    assert scope._scpi_engine.build("identify") == ["*IDN?"]
    assert scope._scpi_engine.build("clear") == ["*CLS"]
    assert scope._scpi_engine.build("get_error") == [":SYSTem:ERRor?"]
    assert scope._scpi_engine.build("header_off") == [":SYSTem:HEADer OFF"]
    assert scope._scpi_engine.build("set_channel_axis", channel=1, scale=1.0, offset=0.0) == [
        ":CHANnel1:SCALe 1.0",
        ":CHANnel1:OFFSet 0.0",
    ]
    assert scope._scpi_engine.build("probe_set", channel=1, scale=10) == [
        ":CHANnel1:PROBe:USER VOLTage,RATio,10"
    ]
    assert scope._scpi_engine.build("probe_get", channel=1) == [":CHANnel1:PROBe?"]
    assert scope._scpi_engine.build(
        "configure_trigger",
        source="CHANnel1",
        channel=1,
        level=0.5,
        slope=TriggerSlope.POSITIVE.value,
        mode="EDGE",
    ) == [
        ":TRIGger:MODE EDGE",
        ":TRIGger:EDGE:SOURce CHANnel1",
        ":TRIGger:LEVel CHANnel1,0.5",
        ":TRIGger:EDGE:SLOPe POS",
    ]
    assert scope._scpi_engine.build("acquire_sample_rate") == [":ACQuire:SRATe:ANALog?"]
    assert scope._scpi_engine.build("acquire_points") == [":ACQuire:POINts:ANALog?"]
    assert scope._scpi_engine.build("wave_preamble") == [":WAVeform:PREamble?"]
    assert scope._scpi_engine.build("measure_vrms", channel=1) == [
        ":MEASure:VRMS? CYCLe,AC,CHANnel1"
    ]
    assert scope._scpi_engine.build("screenshot") == [":DISPlay:DATA? PNG"]
    assert scope._scpi_engine.build("set_wave_points_max") == [":ACQuire:POINts:ANALog MAX"]

    assert scope._scpi_engine.parse("measure_vpp", "1.00000E+00,RAT") == 1.0
    assert scope._scpi_engine.parse("get_channel_scale", ":CHANnel1:SCALe 5.000E-1") == 0.5


def test_mxr404a_profile_maps_documented_fft_and_wgen_commands():
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)

    assert scope._scpi_engine.build("wgen_output", state=True) == [":WGEN:OUTPut ON"]
    assert scope._scpi_engine.build("wgen_output", state=False) == [":WGEN:OUTPut OFF"]
    assert scope._scpi_engine.build("fft_source", channel=1) == [":FUNCtion1:FFTMagnitude CHANnel1"]
    assert scope._scpi_engine.build("fft_window", window="HANNing") == [
        ":FUNCtion1:FFT:WINDow HANNing"
    ]
    assert scope._scpi_engine.build("fft_vtype", units="DECibel") == [":FUNCtion1:FFT:VUNits DB"]
    assert scope._scpi_engine.build("fft_scale", scale=64) == [":FUNCtion1:VERTical:RANGe 64"]
    assert scope._scpi_engine.build("function_display", state="OFF") == [":FUNCtion1:DISPlay OFF"]
    assert scope._scpi_engine.build("wgen_set_func", func="SIN") == [":WGEN:FUNCtion SINusoid"]
    assert scope._scpi_engine.build("wgen_set_square_duty", duty=50) == [
        ":WGEN:FUNCtion:SQUare:DCYCle 50"
    ]

    report = scope.validate_operation_contract(include_unsupported=True)
    assert report["wave_generator_basic"]["supported"] is True
    for operation in ("wave_generator_shapes", "fft", "frequency_response_analysis"):
        assert "missing_required_aliases" not in report[operation]
        assert report[operation]["supported"] is True
        assert report[operation]["missing_parameters"] == []
    assert report["function_display"]["supported"] is True
    assert scope._scpi_engine.build("fran_mode", mode="sweep") == [
        ":POWer:CLResponse:FREQuency:MODE SWEep"
    ]
    assert scope._scpi_engine.build("fran_input_source", channel=2) == [
        ":POWer:CLResponse:SOURce:INPut CHANnel2"
    ]
    assert scope._scpi_engine.build("fran_run") == [":POWer:CLResponse:APPLy"]
    assert scope._scpi_engine.build("fran_select") == [":POWer:ANALysis CLResponse"]
    assert scope._scpi_engine.build("fran_fetch") == [":POWer:CLResponse:DATA? SWEep"]


def test_read_fft_data_forwards_timeout_to_waveform_acquisition(monkeypatch):
    import numpy as np
    import polars as pl

    from pytestlab.experiments import MeasurementResult
    from pytestlab.instruments.Oscilloscope import ChannelReadingResult

    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    calls = []

    def fake_read_channels(channel, **kwargs):
        calls.append((channel, kwargs))
        return ChannelReadingResult(
            values=pl.DataFrame(
                {
                    "Time (s)": np.array([0.0, 1.0e-6, 2.0e-6]),
                    "Channel 1 (V)": np.array([0.0, 1.0, 0.0]),
                }
            ),
            instrument=scope.config.model,
            units="V",
            measurement_type="channel_reading",
        )

    monkeypatch.setattr(scope, "read_channels", fake_read_channels)

    result = scope.read_fft_data(1, timeout_ms=300_000)

    assert isinstance(result, MeasurementResult)
    assert calls == [(1, {"timeout_ms": 300_000})]


def test_mxr404a_profile_uses_supported_word_transfer_commands() -> None:
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)

    assert scope._scpi_engine.build("set_wave_format_word") == [":WAVeform:FORMat WORD"]
    assert scope._scpi_engine.build("set_wave_byteorder_lsb") == [":WAVeform:BYTeorder LSBFirst"]
    assert "set_wave_points_mode_normal" not in scope._scpi_engine.list_names()
    assert scope._scpi_engine.build("set_wave_points_mode_raw") == [":WAVeform:VIEW ALL"]


def test_read_channels_configures_format_before_reading_preamble(monkeypatch) -> None:
    import numpy as np

    from pytestlab.instruments.Oscilloscope import Preamble

    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    monkeypatch.setattr(scope, "_uncertainty_source_key", lambda: "test-mxr-waveform")
    monkeypatch.setattr(scope, "_query_profile_alias", lambda *_args, **_kwargs: "1")
    order = []
    monkeypatch.setattr(scope, "_send_command", lambda _cmd, **_kwargs: None)
    monkeypatch.setattr(scope, "get_sampling_rate", lambda: 1.0e9)
    monkeypatch.setattr(
        scope,
        "_configure_waveform_transfer",
        lambda source, waveform_format: order.append(("configure", source, waveform_format)),
    )
    monkeypatch.setattr(scope, "_read_current_waveform_byteorder", lambda: "little")
    monkeypatch.setattr(
        scope,
        "_read_preamble",
        lambda: (
            order.append(("preamble",))
            or Preamble(
                format="1",
                type="1",
                points=2,
                xinc=1.0e-9,
                xorg=0.0,
                xref=0.0,
                yinc=0.01,
                yorg=0.0,
                yref=0.0,
            )
        ),
    )

    def read_data(source, *, preamble, waveform_format, byteorder=None):
        order.append(("data", source, waveform_format, preamble.yinc, byteorder))
        return np.array([-1, 1], dtype=np.int16)

    monkeypatch.setattr(scope, "_read_wave_data", read_data)

    result = scope.read_channels(1, waveform_format="word")

    assert order == [
        ("configure", "CHANnel1", "word"),
        ("preamble",),
        ("data", "CHANnel1", "word", 0.01, "little"),
    ]
    assert result.values["Channel 1 (V)"].to_list() == [-0.01, 0.01]


def test_mxr404a_acquire_setup_falls_back_to_documented_individual_queries(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    responses = {
        ":ACQuire:AVERage?": "0",
        ":ACQuire:MODE?": "RTIM",
        ":ACQuire:COUNt?": "1",
        ":ACQuire:POINts:ANALog?": "16001",
        ":ACQuire:SRATe:ANALog?": "1.6E10",
    }

    original_build = scope._scpi_engine.build

    def build(alias, **kwargs):
        if alias == "acquire_setup":
            raise KeyError(alias)
        return original_build(alias, **kwargs)

    monkeypatch.setattr(scope._scpi_engine, "build", build)
    monkeypatch.setattr(scope, "_query", lambda query: responses[query])

    assert scope.acquisition.get_acquire_setup() == {
        "type": "0",
        "mode": "RTIM",
        "count": "1",
        "points": "16001",
        "sample_rate": "1.6E10",
    }


def test_mxr404a_acquisition_numeric_mapping_is_profile_declared(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)

    monkeypatch.setattr(scope, "_query", lambda _query: "1")
    assert scope.acquisition.get_acquisition_type() == "AVERAGE"

    monkeypatch.setattr(scope, "_query", lambda _query: "0")
    assert scope.acquisition.get_acquisition_type() == "NORMAL"


def test_mxr404a_control_loop_response_uses_profile_aliases(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []

    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(
        scope,
        "_query_raw",
        lambda _query: _ascii_binblock("100,0,0\n1000,0,0\n"),
    )

    result = scope.franalysis_sweep(
        input_channel=2,
        output_channel=1,
        start_freq=100,
        stop_freq=1000,
        amplitude=0.1,
        points=2,
        load="fifty",
    )

    assert commands[:5] == [
        ":POWer:ANALysis CLResponse",
        ":POWer:CLResponse:FREQuency:MODE SWEep",
        ":POWer:CLResponse:SOURce:INPut CHANnel2",
        ":POWer:CLResponse:SOURce:OUTPut CHANnel1",
        ":POWer:CLResponse:FREQuency:STARt 100.0",
    ]
    assert ":POWer:CLResponse:APPLy" in commands
    assert result.values.columns == ["Frequency (Hz)", "Gain (dB)", "Phase (deg)"]
