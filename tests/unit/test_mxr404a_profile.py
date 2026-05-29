from __future__ import annotations

from pytestlab import AutoInstrument
from pytestlab.common.enums import TriggerSlope


def test_mxr404a_profile_exposes_core_scpi_aliases():
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)

    assert scope.config.trigger.slopes == ["POS", "NEG", "EITH"]
    assert scope.scpi_engine.build("identify") == ["*IDN?"]
    assert scope.scpi_engine.build("clear") == ["*CLS"]
    assert scope.scpi_engine.build("set_channel_axis", channel=1, scale=1.0, offset=0.0) == [
        ":CHANnel1:SCALe 1.0",
        ":CHANnel1:OFFSet 0.0",
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
