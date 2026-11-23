from __future__ import annotations

import json

import pytest

from pytestlab.motion import MotionDevice


def test_status_flattens_profile_details_and_keeps_raw_controller_text():
    status = MotionDevice._coerce_status(
        {
            "state": "unknown",
            "settled": False,
            "fault": False,
            "details": {"raw": "0 -233.000000 -3.500000 6685.750000 31"},
        }
    )

    assert status.state == "unknown"
    assert status.settled is False
    assert status.fault is False
    assert status.details == {"raw": "0 -233.000000 -3.500000 6685.750000 31"}
    assert json.loads(status.raw)["details"] == status.details


def test_status_details_preserve_controller_fields_without_status_duplicates():
    status = MotionDevice._coerce_status(
        {
            "state": "busy",
            "settled": False,
            "fault": False,
            "enabled": True,
            "controller_mode": "manual",
            "details": {"raw": "BUSY", "source": "controller"},
        }
    )

    assert status.details == {
        "controller_mode": "manual",
        "raw": "BUSY",
        "source": "controller",
    }
    assert status.enabled is True
    assert status.state == "busy"
    assert status.settled is False
    assert status.fault is False


def test_string_encoded_status_uses_same_flattened_details():
    status = MotionDevice._coerce_status(
        json.dumps({"state": "unknown", "settled": False, "details": {"raw": "0 31"}})
    )

    assert status.details == {"raw": "0 31"}
    assert status.settled is False
    assert status.fault is False


@pytest.mark.parametrize("details", [None, "raw status", ["raw status"], 1])
def test_malformed_status_details_fail_closed(details):
    with pytest.raises(ValueError, match="details must be an object"):
        MotionDevice._coerce_status(
            {"state": "unknown", "settled": False, "fault": False, "details": details}
        )
