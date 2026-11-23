from __future__ import annotations

import pytest
from pydantic import ValidationError

from pytestlab import AutoInstrument
from pytestlab.config.operation_options import ProfileOperationParameter


@pytest.mark.parametrize(
    ("profile", "impedance", "scale", "expected"),
    [
        ("DSOX1204G", 1_000_000, 2.0, 20.0),
        ("DSOX1204G", 1_000_000, 2.01, 1000.0),
        ("MXR404A", 50, 0.55, 8.0),
        ("MXR404A", 50, 0.551, 16.0),
        ("MXR404A", 50, 1.21, 16.0),
        ("MXR404A", 50, 1.22, 32.0),
        ("MXR404A", 50, 2.61, 32.0),
        ("MXR404A", 50, 2.62, 40.0),
        ("MXR404A", 1_000_000, 0.099, 50.0),
        ("MXR404A", 1_000_000, 0.1, 200.0),
        ("MXR404A", 1_000_000, 2.0, 200.0),
        ("MXR404A", 1_000_000, 2.001, 400.0),
    ],
)
def test_offset_discovery_uses_verified_scale_bands_at_ten_times_probe_factor(
    profile, impedance, scale, expected
):
    instrument = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    description = instrument.describe_operation(
        "channel_axis",
        context={"scale": scale, "probe_attenuation": 10, "input_impedance": impedance},
    )
    constraints = description["parameters"]["offset"]["constraints"]
    assert constraints["min"] == pytest.approx(-expected)
    assert constraints["max"] == pytest.approx(expected)


@pytest.mark.parametrize(
    "predicate",
    [
        {"minimum": 1},
        {"min": float("nan")},
        {"max": float("inf")},
        {"min": 2, "max": 1},
        {"exclusive_min": True},
        {"min": 1, "max": 1, "exclusive_max": True},
    ],
)
def test_invalid_profile_band_conditions_fail_at_load_time(predicate):
    with pytest.raises(ValidationError):
        ProfileOperationParameter(
            kind="range",
            contextual_ranges=[{"when": {"scale": predicate}, "min": -1, "max": 1}],
        )
