from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from pytestlab import AutoDevice
from pytestlab import AutoInstrument
from pytestlab.camera import Camera
from pytestlab.devices.switch_matrix import SwitchMatrixDevice
from pytestlab.instruments.instrument import Instrument
from pytestlab.motion import MotionDevice

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
    data = yaml.safe_load(profile_path.read_text())
    backend = None
    if data.get("device_type") == "camera":
        backend = Mock(
            spec=["connect", "disconnect", "close", "capture", "is_simulated"],
            is_simulated=True,
        )
    instrument = AutoDevice.from_file(profile_path, simulate=True, backend_override=backend)
    # Contract inspection must not allocate a backend or require simulator data.
    if isinstance(instrument, Camera):
        assert instrument.get_capabilities().formats
        return
    if isinstance(instrument, MotionDevice):
        capabilities = instrument.get_capabilities()
        assert capabilities.axes
        assert capabilities.supports
        assert capabilities.frames
        return
    if isinstance(instrument, SwitchMatrixDevice):
        protocol = instrument.config.switch
        assert protocol is not None
        assert {"connect", "open", "clear"} <= set(protocol.get("commands", {}))
        assert protocol.get("crosspoint", {}).get("pattern")
        return
    assert isinstance(instrument, Instrument)
    report = instrument.validate_operation_contract(include_unsupported=True)

    assert isinstance(report, dict)
    for operation_id, operation_report in report.items():
        assert operation_report["operation_id"] == operation_id
        assert "supported" in operation_report
        assert "missing_required_aliases" not in operation_report


def test_hd304mso_profile_covers_declared_feature_aliases() -> None:
    instrument = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    report = instrument.validate_operation_contract(include_unsupported=True)

    assert "wave_generator_basic" in report
    assert report["wave_generator_basic"]["supported"] is True
    assert report["fft"]["supported"] is True
