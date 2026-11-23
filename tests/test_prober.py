from __future__ import annotations

import pytest

from pytestlab.config.device_config import DeviceConfig
from pytestlab.config.device_config import DeviceRole
from pytestlab.prober import GenericProberDevice


class Wire:
    def __init__(self, response: str = "0 ok") -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def connect(self) -> None:
        self.calls.append(("connect", ""))

    def disconnect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, command: str) -> None:
        self.calls.append(("write", command))

    def query(self, command: str, delay: float | None = None) -> str:
        self.calls.append(("query", command))
        return self.response

    def set_timeout(self, timeout_ms: int) -> None:
        pass

    def get_timeout(self) -> int:
        return 1000


def make(spec: dict, wire: Wire | None = None) -> tuple[GenericProberDevice, Wire]:
    wire = Wire() if wire is None else wire
    config = DeviceConfig(
        manufacturer="Example",
        model="prober",
        device_type="prober",
        role=DeviceRole.DUT_CONTROL,
        motion=spec,
    )
    return GenericProberDevice(config, wire), wire


def spec() -> dict:
    bits = {
        "kind": "enum",
        "strict": True,
        "choices": [
            {"token": "1", "aliases": ["true", "on", "1"]},
            {"token": "0", "aliases": ["false", "off", "0"]},
        ],
    }
    return {
        "axes": [{"name": "x"}, {"name": "y"}],
        "supports": [
            "contact",
            "separate",
            "move_to_align",
            "move_to_load",
            "set_vacuum",
            "configure_chuck",
        ],
        "commands": {
            "contact": {"template": "37"},
            "separate": {"template": "39"},
            "move_to_align": {"template": "38"},
            "move_to_load": {"template": "3A"},
            "set_vacuum": {"template": "05 {enabled}", "parameters": {"enabled": bits}},
            "configure_chuck": {
                "template": "03 {overtravel} {auto_z} {interlock} {edge_sensor} 2",
                "parameters": {
                    "overtravel": bits,
                    "auto_z": bits,
                    "interlock": bits,
                    "edge_sensor": bits,
                },
            },
        },
    }


def test_native_actions_share_one_typed_surface() -> None:
    prober, wire = make(spec())
    prober.contact()
    prober.move_to_align()
    prober.separate()
    prober.move_to_load()
    prober.set_vacuum(True)
    prober.configure_chuck(True, True, True, False)
    assert [command for kind, command in wire.calls if kind == "write"] == [
        "37",
        "38",
        "39",
        "3A",
        "05 1",
        "03 1 1 1 0 2",
    ]


def test_second_protocol_uses_the_same_native_surface() -> None:
    settings = spec()
    settings["commands"] = {
        "contact": {"template": "PROBE CONTACT"},
        "separate": {"template": "PROBE SEPARATE"},
        "move_to_align": {"template": "PROBE ALIGN HEIGHT"},
        "move_to_load": {"template": "PROBE LOAD"},
        "set_vacuum": {
            "template": "VACUUM {enabled}",
            "parameters": settings["commands"]["set_vacuum"]["parameters"],
        },
        "configure_chuck": {
            "template": "CHUCK {overtravel} {auto_z} {interlock} {edge_sensor}",
            "parameters": settings["commands"]["configure_chuck"]["parameters"],
        },
    }
    prober, wire = make(settings)
    prober.contact()
    prober.set_vacuum(False)
    prober.configure_chuck(False, True, True, False)
    assert [command for kind, command in wire.calls if kind == "write"] == [
        "PROBE CONTACT",
        "VACUUM 0",
        "CHUCK 0 1 1 0",
    ]


def test_pa_profile_does_not_claim_alignment_action() -> None:
    prober, wire = make(spec())
    with pytest.raises(NotImplementedError, match="align"):
        prober.align()
    assert wire.calls == []


def test_full_recipe_metadata_failure_is_zero_io() -> None:
    settings = spec()
    settings["supports"] = ["move_absolute", "contact", "separate"]
    settings["commands"]["move_absolute"] = {"template": "MOVE {x} {y}"}
    prober, wire = make(settings)
    with pytest.raises(NotImplementedError, match="contact state"):
        prober.preflight_recipe()
    assert wire.calls == []


def test_static_preflight_checks_mapped_metadata_without_readback_io() -> None:
    settings = spec()
    settings["supports"] = ["move_absolute", "contact", "separate"]
    settings["commands"] = {
        "move_absolute": {"template": "MOVE {x} {y}"},
        "contact": {"template": "CONTACT"},
        "separate": {"template": "SEPARATE"},
    }
    settings["queries"] = {
        "contact_state": {
            "template": "CONTACT?",
            "response": {"type": "state_map", "values": {"0": False, "1": True}},
        },
        "settled": {
            "template": "SETTLED?",
            "response": {"type": "state_map", "values": {"0": False, "1": True}},
        },
    }
    prober, wire = make(settings)
    assert prober.preflight_recipe() == ("move_absolute", "contact", "separate")
    assert wire.calls == []


@pytest.mark.parametrize("values", [{}, {"1": "true"}])
def test_empty_or_non_bool_settled_map_fails_preflight_without_io(values) -> None:
    settings = spec()
    settings["supports"] = ["move_absolute", "contact", "separate"]
    settings["commands"] = {
        "move_absolute": {"template": "MOVE {x} {y}"},
        "contact": {"template": "CONTACT"},
        "separate": {"template": "SEPARATE"},
    }
    settings["queries"] = {
        "contact_state": {
            "template": "CONTACT?",
            "response": {"type": "state_map", "values": {"0": False, "1": True}},
        },
        "settled": {
            "template": "SETTLED?",
            "response": {"type": "state_map", "values": values},
        },
    }
    prober, wire = make(settings)
    with pytest.raises(NotImplementedError, match="settled"):
        prober.preflight_recipe()
    assert wire.calls == []


@pytest.mark.parametrize(
    "call",
    [
        lambda device: device.set_vacuum(1),
        lambda device: device.configure_chuck(True, 1, True, False),
    ],
)
def test_invalid_boolean_arguments_are_rejected_before_io(call) -> None:
    prober, wire = make(spec())
    with pytest.raises(TypeError):
        call(prober)
    assert wire.calls == []


def test_ack_only_profile_has_no_phantom_readbacks_or_full_recipe_claim() -> None:
    prober, wire = make(spec())
    with pytest.raises(NotImplementedError):
        prober.get_contact_state()
    with pytest.raises(NotImplementedError):
        prober.get_vacuum_state()
    with pytest.raises(NotImplementedError):
        prober.get_settled_state()
    with pytest.raises(NotImplementedError):
        prober.preflight_recipe()
    assert wire.calls == []
