"""Packaged native presets and explicit legacy descriptor compatibility."""

from pathlib import Path

import pytest
import yaml

PROFILES = Path(__file__).resolve().parents[2] / "pytestlab" / "profiles"


@pytest.mark.parametrize(
    ("preset", "device_type"),
    [
        ("agilent/3458A", "multimeter"),
        ("hp/4142B", "source_measure"),
        ("hp/HP4084B", "switch_matrix"),
        ("suss/PA200", "prober"),
        ("touptek/E3CMOS12000KPA", "camera"),
    ],
)
def test_native_presets_have_no_site_specific_wiring(preset, device_type):
    data = yaml.safe_load((PROFILES / f"{preset}.yaml").read_text())
    assert data["device_type"] == device_type
    assert "address" not in data
    assert "backend" not in data
    assert "server_url" not in data


@pytest.mark.parametrize("preset", ["agilent/3458A", "hp/4142B", "hp/HP4084B", "suss/PA200"])
def test_legacy_presets_keep_generic_descriptor_driver(preset):
    data = yaml.safe_load((PROFILES / f"{preset}_legacy.yaml").read_text())
    assert data["device_type"] == "instrument"
    assert data["driver"] == "pytestlab.instruments.profile_instrument:ProfileInstrument"
    assert data["operation_options"]["operations"]


def test_modular_source_does_not_assume_installed_card_limits():
    data = yaml.safe_load((PROFILES / "hp/4142B.yaml").read_text())
    assert data["channels"] == []
    assert data["capabilities"]["channel_requirements"]["channel_ids"] == list(range(1, 9))


def test_prober_native_and_legacy_protocols_are_distinct():
    native = yaml.safe_load((PROFILES / "suss/PA200.yaml").read_text())
    legacy = yaml.safe_load((PROFILES / "suss/PA200_legacy.yaml").read_text())
    assert native["motion"]["queries"]["position"]["template"] == "31"
    assert legacy["scpi"]["queries"]["read_chuck_position"]["template"] == "ReadChuckPosition"
    assert "reset" not in native["motion"]["commands"]
    assert native["transport"]["write_termination"] is None
