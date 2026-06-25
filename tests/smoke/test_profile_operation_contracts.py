from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pytestlab import AutoInstrument

PROFILES_DIR = Path(__file__).resolve().parents[2] / "pytestlab" / "profiles"


def _runtime_profile_paths() -> list[Path]:
    paths: list[Path] = []
    for path in sorted(PROFILES_DIR.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        if data.get("device_type") and "accessories" not in path.parts:
            paths.append(path)
    return paths


@pytest.mark.parametrize(
    "profile_path", _runtime_profile_paths(), ids=lambda p: str(p.relative_to(PROFILES_DIR))
)
def test_all_runtime_profiles_expose_operation_contract_reports(profile_path: Path) -> None:
    instrument = AutoInstrument.from_config(str(profile_path), simulate=True)

    report = instrument.validate_operation_contract(include_unsupported=True)

    assert isinstance(report, dict)
    for operation_id, operation_report in report.items():
        assert operation_report["operation_id"] == operation_id
        assert "supported" in operation_report
        assert "missing_required_aliases" in operation_report


def test_contract_catches_hd304mso_feature_alias_drift() -> None:
    instrument = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    report = instrument.validate_operation_contract(include_unsupported=True)

    assert "wave_generator_basic" in report
    assert {"wgen_set_freq", "wgen_set_volt"}.issubset(
        report["wave_generator_basic"]["missing_required_aliases"]
    )
    assert "fft_display" in report["fft"]["missing_required_aliases"]
