import sqlite3

from pydantic import BaseModel

from pytestlab.config import BaseConfig
from pytestlab.config import Config
from pytestlab.config import ConfigLoader
from pytestlab.config import DeviceConfig
from pytestlab.config import InstrumentConfig
from pytestlab.experiments import DatabaseBackup
from pytestlab.experiments import MeasurementDatabase
from pytestlab.experiments import Sweep
from pytestlab.experiments.sweep import grid_sweep
from pytestlab.experiments.sweep import gwass
from pytestlab.experiments.sweep import monte_carlo_sweep


def test_configuration_bases_are_part_of_the_real_hierarchy() -> None:
    assert issubclass(BaseConfig, Config)
    assert issubclass(DeviceConfig, BaseConfig)
    assert issubclass(InstrumentConfig, DeviceConfig)
    assert issubclass(Config, BaseModel)


def test_config_serialization_and_loader_facade_are_functional() -> None:
    config = ConfigLoader.load("keysight/EDU36311A")

    assert config.device_type == "power_supply"
    assert ConfigLoader.resolve("keysight/EDU36311A").name == "EDU36311A.yaml"
    assert config.to_json()["model"] == "EDU36311A"


def test_database_backup_creates_readable_sqlite_snapshot(tmp_path) -> None:
    database = MeasurementDatabase(tmp_path / "source")

    backup_path = DatabaseBackup(database).create(tmp_path / "backup")

    with sqlite3.connect(backup_path) as backup:
        table_names = {
            row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    database.close()
    assert "measurements" in table_names
    assert "experiments" in table_names


def test_sweep_facade_exposes_the_functional_decorators() -> None:
    assert Sweep.grid is grid_sweep
    assert Sweep.monte_carlo is monte_carlo_sweep
    assert Sweep.adaptive is gwass
