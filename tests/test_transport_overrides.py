from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from pytestlab import AutoDevice


def config_with(transport: dict[str, Any]) -> dict[str, Any]:
    return {
        "manufacturer": "Fixture",
        "model": "Test motion device",
        "device_type": "motion_stage",
        "role": "fixture",
        "transport": transport,
        "motion": {"axes": []},
    }


@pytest.mark.parametrize(
    "transport,override",
    [
        ({"message_io": {"read_termination": "\r\n"}}, "\n"),
        ({"read_termination": None}, "\n"),
        ({"read_termination": "\r\n"}, "\n"),
    ],
)
def test_bench_cannot_replace_declared_read_framing(transport, override):
    profile = config_with(transport)
    with pytest.raises(ValueError, match="cannot replace the profile's required termination"):
        AutoDevice.from_dict(
            profile,
            backend_override=object(),
            transport_override={"read_termination": override},
        )


def test_matching_nested_framing_override_preserves_original_profile():
    profile = config_with({"message_io": {"read_termination": "\r\n"}})
    original = deepcopy(profile)

    device = AutoDevice.from_dict(
        profile,
        backend_override=object(),
        transport_override={"read_termination": "\r\n"},
    )

    assert device.config.transport["read_termination"] == "\r\n"
    assert profile == original


def test_explicit_null_framing_can_only_be_overridden_with_null():
    profile = config_with({"message_io": {"read_termination": None}})

    device = AutoDevice.from_dict(
        profile,
        backend_override=object(),
        transport_override={"read_termination": None},
    )

    assert device.config.transport["read_termination"] is None


def test_nested_motion_and_switch_framing_are_profile_requirements():
    for section in ("motion", "switch"):
        profile = config_with({})
        profile[section] = {
            "message_io": {"read_termination": "\r\n"},
            "axes": [] if section == "motion" else None,
        }
        with pytest.raises(ValueError, match="cannot replace the profile's required termination"):
            AutoDevice.from_dict(
                profile,
                backend_override=object(),
                transport_override={"read_termination": "\n"},
            )
