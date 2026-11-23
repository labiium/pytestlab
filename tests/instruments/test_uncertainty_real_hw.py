from __future__ import annotations

import os
from typing import Any
from typing import cast

import pytest


@pytest.mark.requires_real_hw
def test_real_hardware_uncertainty_lane_is_opt_in():
    """Document the real-hardware uncertainty lane without making CI depend on instruments."""

    profile = os.environ.get("PYTESTLAB_UNCERTAINTY_HW_PROFILE")
    address = os.environ.get("PYTESTLAB_UNCERTAINTY_HW_ADDRESS")
    if not profile or not address:
        pytest.skip(
            "Set PYTESTLAB_UNCERTAINTY_HW_PROFILE and PYTESTLAB_UNCERTAINTY_HW_ADDRESS "
            "to run real-hardware uncertainty validation."
        )
    profile = cast(str, profile)

    from pytestlab.config.loader import load_device_profile

    config = load_device_profile(profile)
    assert config.address == address or config.address is None
    config_with_accuracy = cast(Any, config)
    assert config_with_accuracy.measurement_accuracy or getattr(
        config_with_accuracy, "measurement_functions", None
    )
