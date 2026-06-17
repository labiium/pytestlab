from __future__ import annotations

from pytestlab import AutoInstrument
from pytestlab.common.enums import TriggerSlope


def test_mxr404a_profile_exposes_core_scpi_aliases():
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)

    assert scope.config.trigger.slopes == ["POS", "NEG", "EITH"]
    assert scope.scpi_engine.build("identify") == ["*IDN?"]
    assert scope.scpi_engine.build("clear") == ["*CLS"]
    assert scope.scpi_engine.build("header_off") == [":SYSTem:HEADer OFF"]
    assert scope.scpi_engine.build("set_channel_axis", channel=1, scale=1.0, offset=0.0) == [
        ":CHANnel1:SCALe 1.0",
        ":CHANnel1:OFFSet 0.0",
    ]
    assert scope.scpi_engine.build("probe_set", channel=1, scale=10) == [
        ":CHANnel1:PROBe:ATTenuation 10"
    ]
    assert scope.scpi_engine.build("probe_get", channel=1) == [
        ":CHANnel1:PROBe:ATTenuation?"
    ]
    assert scope.scpi_engine.build(
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
    assert scope.scpi_engine.build("acquire_sample_rate") == [":ACQuire:SRATe:ANALog?"]
    assert scope.scpi_engine.build("acquire_points") == [":ACQuire:POINts:ANALog?"]
    assert scope.scpi_engine.build("wave_preamble") == [":WAVeform:PREamble?"]
    assert scope.scpi_engine.build("measure_vrms", channel=1) == [
        ":MEASure:VRMS? CYCLe,AC,CHANnel1"
    ]

    assert scope.scpi_engine.parse("measure_vpp", "1.00000E+00,RAT") == 1.0
    assert scope.scpi_engine.parse("get_channel_scale", ":CHANnel1:SCALe 5.000E-1") == 0.5


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
