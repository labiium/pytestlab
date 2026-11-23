from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pytestlab import AutoInstrument
from pytestlab.cli import app
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.config.loader import load_device_profile
from pytestlab.devices.base import Device
from pytestlab.devices.factory import AutoDevice
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments import Multimeter
from pytestlab.instruments import Oscilloscope
from pytestlab.instruments import WaveformGenerator
from pytestlab.instruments.backends.sim_backend import SimBackend
from pytestlab.instruments.instrument import Instrument
from pytestlab.measurement_plan import prepare_declared_measurements


class CustomMultimeter(Multimeter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.constructor_ran = True


class NonInstrumentDevice(Device):
    pass


@pytest.mark.parametrize(
    "profile,driver,operation,parameter",
    [
        ("keysight/EDU34450A", Multimeter, "measure", "function"),
        ("keysight/EDU33212A", WaveformGenerator, "set_function", "function_type"),
        ("keysight/HD304MSO", Oscilloscope, "set_acquisition_type", "acq_type"),
    ],
)
def test_normal_factory_selects_driver_without_runtime_construction(
    monkeypatch, profile, driver, operation, parameter
):
    def forbidden(*args, **kwargs):
        pytest.fail("offline discovery attempted runtime construction or I/O")

    monkeypatch.setattr(AutoDevice, "_build_backend", forbidden)
    monkeypatch.setattr(SimBackend, "__init__", forbidden)
    monkeypatch.setattr(Instrument, "_query", forbidden)
    metadata = AutoInstrument.from_config(profile)
    assert isinstance(metadata, driver)
    assert metadata.list_operation_options(operation, parameter)
    assert metadata.describe_operation(operation)["support"]["supported"]


@pytest.mark.parametrize(
    "input_kind", ["path", "path_string", "mapping", "config", "profile_override"]
)
def test_normal_factory_accepts_normal_profile_inputs(tmp_path, input_kind):
    profile = yaml.safe_load(Path("pytestlab/profiles/keysight/EDU34450A.yaml").read_text())
    path = tmp_path / "meter.yaml"
    path.write_text(yaml.safe_dump(profile))
    inputs = {
        "path": path,
        "path_string": str(path),
        "mapping": profile,
        "config": load_device_profile(profile),
        "profile_override": {"profile": "keysight/EDU34450A", "model": "Local meter"},
    }
    metadata = AutoInstrument.from_config(inputs[input_kind])
    expected = AutoInstrument.from_config("keysight/EDU34450A")
    assert metadata.list_operation_options(
        "measure", "function"
    ) == expected.list_operation_options("measure", "function")
    if input_kind == "profile_override":
        assert metadata.config.model == "Local meter"


def test_normal_factory_honors_explicit_driver_before_registered_driver():
    metadata = AutoInstrument.from_config(
        {"profile": "keysight/EDU34450A", "driver": f"{__name__}:CustomMultimeter"}
    )
    assert isinstance(metadata, CustomMultimeter)
    assert metadata.constructor_ran


def test_normal_factory_rejects_non_instrument_driver():
    with pytest.raises(InstrumentConfigurationError, match="Instrument"):
        AutoInstrument.from_config(
            {"profile": "keysight/EDU34450A", "driver": f"{__name__}:NonInstrumentDevice"}
        )


def test_cli_and_bench_validation_use_normal_factory(monkeypatch):
    calls = []
    original = AutoInstrument.from_config

    def record(source):
        calls.append(source)
        return original(source)

    monkeypatch.setattr(AutoInstrument, "from_config", record)
    result = CliRunner().invoke(
        app, ["instrument", "list-options", "keysight/EDU34450A", "measure", "function"]
    )
    assert result.exit_code == 0
    assert len(calls) == 1 and calls[0].model == "EDU34450A"
    config = BenchConfigExtended.model_validate(
        {
            "bench_name": "validation",
            "instruments": {"meter": {"profile": "keysight/EDU34450A"}},
            "measurement_plan": [
                {
                    "name": "voltage",
                    "instrument": "meter",
                    "target": {"kind": "multimeter_function", "function": "voltage"},
                }
            ],
        }
    )
    assert prepare_declared_measurements(config).errors == []
    assert len(calls) == 2 and calls[-1].model == "EDU34450A"
