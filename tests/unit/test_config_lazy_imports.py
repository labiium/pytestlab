from __future__ import annotations

import json
import subprocess
import sys

import pytestlab.config as config


def _imported_modules(statement: str) -> set[str]:
    script = (
        "import json, sys; "
        f"{statement}; "
        "print(json.dumps(sorted(name for name in sys.modules if name.startswith('pytestlab.'))))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(json.loads(completed.stdout))


def test_config_package_import_is_lazy() -> None:
    modules = _imported_modules("import pytestlab.config")

    assert not any(name.startswith("pytestlab.uncertainty") for name in modules)
    assert "pytestlab.config.power_supply_config" not in modules
    assert "pytestlab.config.oscilloscope_config" not in modules
    assert "pytestlab.config.multimeter_config" not in modules


def test_narrow_config_import_does_not_load_unrelated_models() -> None:
    modules = _imported_modules("from pytestlab.config.device_config import DeviceRole")

    assert "pytestlab.config.device_config" in modules
    assert not any(name.startswith("pytestlab.uncertainty") for name in modules)
    assert "pytestlab.config.power_supply_config" not in modules
    assert "pytestlab.config.oscilloscope_config" not in modules


def test_all_public_config_exports_remain_resolvable() -> None:
    for name in config.__all__:
        assert getattr(config, name) is not None

    assert config.MeasurementQuantity.__name__ == "Quantity"
    assert config.UncertaintyDistribution.__name__ == "Distribution"
    assert config.evaluate_uncertainty_model.__name__ == "evaluate_quantity"
    assert config.scpi_schema.__name__ == "pytestlab.config.scpi_schema"
