from __future__ import annotations

from typing import Any

from pytestlab.config.scpi_schema import CommandSpec
from pytestlab.config.scpi_schema import RangeValidator
from pytestlab.config.scpi_schema import ResponseSpec
from pytestlab.config.scpi_schema import SCPISection
from pytestlab.instruments.scpi_engine import SCPIEngine


def build_minimal_scpi_section() -> SCPISection:
    cmds: dict[str, CommandSpec] = {
        "set_voltage": CommandSpec(
            template=":VOLT {voltage}, (@{channel})",
            defaults={"channel": 1},
            validators={"voltage": RangeValidator(min=0.0, max=30.0)},
        ),
        "identify": CommandSpec(
            template="*IDN?",
            response=ResponseSpec(type="str"),
        ),
    }
    qs: dict[str, CommandSpec] = {
        "measure_voltage": CommandSpec(
            template=":MEAS:VOLT? (@{channel})",
            response=ResponseSpec(type="float"),
            defaults={"channel": 1},
        )
    }
    return SCPISection(commands=cmds, queries=qs)


def test_engine_accepts_pydantic_section_and_builds():
    scpi = build_minimal_scpi_section()
    eng = SCPIEngine(scpi)

    # names present
    names = eng.list_names()
    assert set(["set_voltage", "identify", "measure_voltage"]).issubset(set(names))

    # describe returns expected keys
    desc = eng.describe("set_voltage")
    assert "sequence" in desc and isinstance(desc["sequence"], list)
    assert ":VOLT {voltage}, (@{channel})" in desc["sequence"][0]
    assert "validators" in desc and "voltage" in desc["validators"]

    # build ok with defaults and provided param
    cmd_list = eng.build("set_voltage", voltage=5)
    assert len(cmd_list) == 1
    assert cmd_list[0].startswith(":VOLT 5")

    # parse float works
    val = eng.parse("measure_voltage", b"12.5")
    assert isinstance(val, float) and val == 12.5


def test_placeholder_introspection_and_validation_helpers():
    scpi = build_minimal_scpi_section()
    eng = SCPIEngine(scpi)

    # validate_presence
    presence = eng.validate_presence(["set_voltage", "nope"])
    assert presence == {"set_voltage": True, "nope": False}

    # validate_placeholders finds placeholders
    info: dict[str, Any] = eng.validate_placeholders(
        "set_voltage", required_params=["voltage", "channel"]
    )
    assert sorted(info["placeholders"]) == ["channel", "voltage"]
    assert info["missing_required"] == []
    assert info["extra_params"] == []
