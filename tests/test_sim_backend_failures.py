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
