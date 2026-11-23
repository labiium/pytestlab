from __future__ import annotations

import pytest
import yaml

from pytestlab.instruments.backends.sim_backend import SCPIError
from pytestlab.instruments.backends.sim_backend import SimBackend


def _write_profile(tmp_path, **profile):
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile))
    return path


def test_sim_backend_unknown_query_queues_undefined_header(tmp_path) -> None:
    backend = SimBackend(_write_profile(tmp_path, simulation={"scpi": {}}))

    assert backend.query(":BOGus:HEADer?") == ""
    assert backend.query("SYST:ERR?") == '-113,"Undefined header"'
    assert backend.query("SYST:ERR?") == '+0,"No error"'


def test_sim_backend_unknown_raw_query_queues_undefined_header(tmp_path) -> None:
    backend = SimBackend(_write_profile(tmp_path, simulation={"scpi": {}}))

    assert backend.query_raw(":BOGus:BINary?") == b""
    assert backend.query("SYST:ERR?") == '-113,"Undefined header"'


def test_sim_backend_regex_header_matches_optional_leading_colon(tmp_path) -> None:
    backend = SimBackend(_write_profile(tmp_path, simulation={"scpi": {":DIGitize.*": {}}}))

    backend.write("DIGitize CHANnel1")

    assert backend.query("SYST:ERR?") == '+0,"No error"'


def test_sim_backend_declared_literal_write_command_is_not_undefined(tmp_path) -> None:
    path = _write_profile(
        tmp_path,
        identification="Declared,Backend,001,1.0",
        scpi={
            "commands": {
                "arm": {"template": ":ARM"},
                "bad_idn": {"template": "*IDN?"},
                "bad_cls": {"template": "*CLS"},
                "bad_opc": {"template": "*OPC?"},
                "bad_query": {"template": ":DECLared?"},
            }
        },
        simulation={"scpi": {}},
    )
    backend = SimBackend(path)

    backend.write(":ARM")

    assert backend.query("SYST:ERR?") == '+0,"No error"'

    assert backend.query("*IDN?") == "Declared,Backend,001,1.0"
    backend.query(":BOGus?")
    assert backend.query("SYST:ERR?") == '-113,"Undefined header"'
    backend.write("*CLS")
    assert backend.query("SYST:ERR?") == '+0,"No error"'
    assert backend.query("*OPC?") == "1"

    assert backend.query(":DECLared?") == ""
    assert backend.query("SYST:ERR?") == '-113,"Undefined header"'

    backend.write(":UNDefined")
    backend.query(":UNDefined?")
    assert backend.query("SYST:ERR?") == '-113,"Undefined header"'
    assert backend.query("SYST:ERR?") == '-113,"Undefined header"'
    assert backend.query("SYST:ERR?") == '+0,"No error"'


def test_sim_backend_missing_state_mapping_raises_scpi_error(tmp_path) -> None:
    backend = SimBackend(
        _write_profile(
            tmp_path,
            simulation={
                "initial_state": {"voltage": 3.3},
                "scpi": {
                    ":VOLT?": {"get": "voltage"},
                    ":CURR?": {"get": "current"},
                },
            },
        )
    )

    assert backend.query(":VOLT?") == "3.3"
    assert backend.query("SYST:ERR?") == '+0,"No error"'

    with pytest.raises(SCPIError, match="state mapping 'current' is undefined"):
        backend.query(":CURR?")


def test_edu34450a_trigger_source_state_round_trips_and_unknown_tokens_fail_closed() -> None:
    from pathlib import Path

    import pytestlab

    profile = Path(pytestlab.__file__).resolve().parent / "profiles/keysight/EDU34450A.yaml"
    backend = SimBackend(profile)
    assert backend.query("TRIG:SOUR?") == "IMM"
    for source in ["IMM", "EXT", "BUS"]:
        backend.write(f"TRIG:SOUR {source}")
        assert backend.query(":TRIGGER:SOURCE?") == source
        assert backend.query("SYST:ERR?") == '+0,"No error"'
    backend.write("TRIG:SOUR UNKNOWN")
    assert backend.query("TRIG:SOUR?") == "BUS"
    assert backend.query("SYST:ERR?") == '-113,"Undefined header"'
    assert backend.query("SYST:ERR?") == '+0,"No error"'
    backend.write("*RST")
    assert backend.query("TRIG:SOUR?") == "IMM"
    assert backend.query("SYST:ERR?") == '+0,"No error"'


def test_edu33212a_ascii_waveform_upload_retains_samples_points_and_reset() -> None:
    from pathlib import Path

    import pytestlab
    from pytestlab import AutoInstrument

    profile = Path(pytestlab.__file__).resolve().parent / "profiles/keysight/EDU33212A.yaml"
    backend = SimBackend(profile)
    backend.write("SOUR1:DATA:ARBitrary:DAC NATIVECASE,0,-32768,32767")
    assert backend.query("SOUR1:FUNC:ARB:POINts?") == "3"
    assert backend.query("SOUR1:FUNC:ARBitrary?") == "NATIVECASE"
    assert backend._state["waveform_ch1"]["values"] == [0, -32768, 32767]
    backend.write("SOUR2:DATA:ARBitrary NORMAL,-1,0.125,1")
    assert backend._state["waveform_ch2"]["values"] == [-1.0, 0.125, 1.0]
    assert backend.query("SYST:ERR?") == '+0,"No error"'
    backend.write("*RST")
    assert backend.query("SOUR1:FUNC:ARB:POINts?") == "0"
    assert backend._state["waveform_ch2"]["values"] == []
    awg = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    try:
        awg.download_arbitrary_waveform_data(
            channel=1,
            arb_name="NATIVECASE",
            data_points=[0],
            data_type="dac",
            use_binary=False,
            is_dual_channel_data=False,
        )
        assert awg.get_arbitrary_waveform_points(1) == 1
        assert awg._query("SOUR1:FUNC:ARBitrary?") == "NATIVECASE"
        assert awg._backend._state["waveform_ch1"]["values"] == [0]
    finally:
        awg.close()


@pytest.mark.parametrize("invalid", ["", "32768", "-32769", "0.5", "NaN", "0,", "not-a-number"])
def test_ascii_waveform_invalid_dac_keeps_previous_state_and_queued_error(invalid) -> None:
    from pathlib import Path

    import pytestlab

    profile = Path(pytestlab.__file__).resolve().parent / "profiles/keysight/EDU33212A.yaml"
    backend = SimBackend(profile)
    backend.write("SOUR1:DATA:ARBitrary:DAC ORIGINAL,1,2")
    backend.write(f"SOUR1:DATA:ARBitrary:DAC INVALID,{invalid}")
    assert backend.query("SOUR1:FUNC:ARBitrary?") == "ORIGINAL"
    assert backend.query("SOUR1:FUNC:ARB:POINts?") == "2"
    assert backend._state["waveform_ch1"]["values"] == [1, 2]
    assert backend.query("SYST:ERR?") == '-222,"Data out of range"'
    assert backend.query("SYST:ERR?") == '+0,"No error"'


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "1.01", "-1.01", "0,"])
def test_ascii_waveform_invalid_normalized_keeps_previous_state(invalid) -> None:
    from pathlib import Path

    import pytestlab

    profile = Path(pytestlab.__file__).resolve().parent / "profiles/keysight/EDU33212A.yaml"
    backend = SimBackend(profile)
    backend.write("SOUR1:DATA:ARBitrary ORIGINAL,0.125")
    backend.write(f"SOUR1:DATA:ARBitrary INVALID,{invalid}")
    assert backend._state["waveform_ch1"]["values"] == [0.125]
    assert backend.query("SYST:ERR?") == '-222,"Data out of range"'


def test_declared_waveform_point_capacity_rejects_without_state_mutation(tmp_path) -> None:
    profile = _write_profile(
        tmp_path,
        simulation={
            "scpi": {
                r"UPLOAD ([^,]+),(.*)": {
                    "store_waveform": {
                        "channel": "1",
                        "name": "$1",
                        "format": "DAC",
                        "data": "$2",
                        "max_points": 2,
                    }
                },
            }
        },
    )
    backend = SimBackend(profile)
    backend.write("UPLOAD ORIGINAL,1,2")
    backend.write("UPLOAD INVALID,1,2,3")
    assert backend._state["waveform_ch1"]["values"] == [1, 2]
    assert backend.query("SYST:ERR?") == '-222,"Data out of range"'
