from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import cast
from unittest.mock import Mock

import pytest

from pytestlab.uncertainty import Quantity as MeasurementQuantity
from pytestlab.config.dc_active_load_config import DCActiveLoadConfig
from pytestlab.config.loader import load_device_profile
from pytestlab.config.multimeter_config import DMMFunction
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.config.oscilloscope_config import OscilloscopeConfig
from pytestlab.config.power_supply_config import PowerSupplyConfig
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.instruments.DCActiveLoad import DCActiveLoad
from pytestlab.instruments.Multimeter import Multimeter
from pytestlab.instruments.Oscilloscope import Oscilloscope
from pytestlab.instruments.PowerSupply import PowerSupply

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "uncertainty"


def backend_querying(reading: str = "5.0") -> Mock:
    backend = Mock()
    backend.connect = Mock()
    backend.disconnect = Mock()
    backend.write = Mock()
    backend.query = Mock(
        side_effect=lambda query, delay=None: '0,"No error"' if "SYSTem:ERRor" in query else reading
    )
    return backend


def test_dmm_fixture_profile_loads_drives_and_persists(tmp_path):
    config = load_device_profile(FIXTURE_DIR / "dmm_advanced.yaml")
    assert isinstance(config, MultimeterConfig)
    functions = config.measurement_functions
    assert functions is not None
    dc_voltage = functions.dc_voltage
    assert dc_voltage is not None
    accuracy = dc_voltage.ranges[0].accuracy
    assert accuracy is not None
    assert getattr(accuracy, "model", None) == "expression"

    dmm = Multimeter(config=config, backend=backend_querying("5.0"))
    object.__setattr__(dmm, "get_config", Mock(return_value=Mock(range_value=10.0)))
    dmm.scpi_engine = Mock(build=Mock(return_value=["READ?"]))

    measurement = dmm.measure(DMMFunction.VOLTAGE_DC)
    assert isinstance(measurement.values, MeasurementQuantity)
    assert measurement.values.u == pytest.approx(0.06)

    with MeasurementDatabase(tmp_path / "dmm_fixture") as db:
        key = db.store_measurement(None, measurement)
        restored = db.retrieve_measurement(key)
    assert isinstance(restored.values, MeasurementQuantity)
    assert restored.values.u == pytest.approx(measurement.values.u, rel=1e-9)
    assert restored.values.budget().entries[0].source is None


def test_psu_fixture_profile_loads_drives_and_persists(tmp_path):
    config = load_device_profile(FIXTURE_DIR / "psu_advanced.yaml")
    assert isinstance(config, PowerSupplyConfig)

    psu = PowerSupply(config=config, backend=backend_querying("5.0"))
    object.__setattr__(psu, "_error_check", Mock())
    psu.scpi_engine = Mock(build=Mock(return_value=["MEAS:VOLT?"]), parse=Mock(return_value="5.0"))

    reading = psu.read_voltage(1)
    assert isinstance(reading, MeasurementQuantity)
    assert reading.u == pytest.approx(0.1)

    with MeasurementDatabase(tmp_path / "psu_fixture") as db:
        key = db.store_measurement(None, _measurement(reading, "FixturePSU", "V", "voltage"))
        restored = db.retrieve_measurement(key)
    assert isinstance(restored.values, MeasurementQuantity)
    assert restored.values.nominal == pytest.approx(5.0)


def test_scope_fixture_profile_loads_drives_and_persists(tmp_path):
    config = load_device_profile(FIXTURE_DIR / "scope_advanced.yaml")
    assert isinstance(config, OscilloscopeConfig)

    scope = Oscilloscope(config=config, backend=backend_querying("5.0"))
    object.__setattr__(scope, "_error_check", Mock())
    scope.scpi_engine = Mock(build=Mock(return_value=["MEAS:VPP?"]), parse=Mock(return_value="5.0"))

    result = scope.measure_voltage_peak_to_peak(1)
    assert isinstance(result.values, MeasurementQuantity)
    assert result.values.u == pytest.approx(0.15)

    with MeasurementDatabase(tmp_path / "scope_fixture") as db:
        key = db.store_measurement(None, result)
        restored = db.retrieve_measurement(key)
    assert isinstance(restored.values, MeasurementQuantity)


def test_dc_load_fixture_profile_loads_drives_and_persists(tmp_path):
    config = load_device_profile(FIXTURE_DIR / "dc_load_advanced.yaml")
    assert isinstance(config, DCActiveLoadConfig)

    load = DCActiveLoad(config=config, backend=backend_querying("5.0"))
    load.current_mode = "CV"
    object.__setattr__(load, "_error_check", Mock())

    def build(command, **kwargs):
        return ["VOLT:RANG?"] if command == "mode_get_range" else ["MEAS:VOLT?"]

    def parse(command, response):
        return "10.2" if command == "mode_get_range" else "5.0"

    load.scpi_engine = Mock(build=Mock(side_effect=build), parse=Mock(side_effect=parse))

    result = load.measure_voltage()
    assert isinstance(result.values, MeasurementQuantity)
    assert result.values.u == pytest.approx(0.1)

    with MeasurementDatabase(tmp_path / "load_fixture") as db:
        key = db.store_measurement(None, result)
        restored = db.retrieve_measurement(key)
    assert isinstance(restored.values, MeasurementQuantity)


def _measurement(value: MeasurementQuantity, instrument: str, unit: str, measurement_type: str):
    from pytestlab.experiments.results import MeasurementResult

    value = cast(Any, value)
    return MeasurementResult(
        values=value,
        instrument=instrument,
        units=unit,
        measurement_type=measurement_type,
    )
