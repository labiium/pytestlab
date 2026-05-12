from __future__ import annotations

from pathlib import Path

import pytest

from pytestlab.config.loader import get_model_registry
from pytestlab.config.loader import load_profile

PROFILE_ROOT = Path("pytestlab/profiles")
PROFILE_PATHS = sorted(PROFILE_ROOT.glob("*/*.yaml"))


@pytest.mark.parametrize("profile_path", PROFILE_PATHS, ids=lambda path: path.as_posix())
def test_all_packaged_profiles_load_with_registered_model(profile_path: Path):
    registry = get_model_registry()

    config = load_profile(profile_path)

    assert config.device_type in registry
    assert isinstance(config.manufacturer, str)
    assert isinstance(config.model, str)
