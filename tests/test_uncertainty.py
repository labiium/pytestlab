from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError
from uncertainties import ufloat

from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.loader import load_device_profile
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.results import MeasurementResult
from pytestlab.uncertainty import Distribution as UncertaintyDistribution
from pytestlab.uncertainty import Quantity as MeasurementQuantity
from pytestlab.uncertainty import UnitCompatibilityError
from pytestlab.uncertainty.specs import AccuracySpec
from pytestlab.uncertainty.specs import BandAccuracySpec
from pytestlab.uncertainty.specs import CompositeBudgetSpec
from pytestlab.uncertainty.specs import ExpressionAccuracySpec
from pytestlab.uncertainty.specs import MonteCarloAccuracySpec
from pytestlab.uncertainty.specs import RepeatabilityAccuracySpec
from pytestlab.uncertainty.specs import UncertaintyContext
from pytestlab.uncertainty.specs import evaluate_quantity as quantity_from_uncertainty_model

# from pytestlab import AutoInstrument # If testing end-to-end with a sim instrument

# Dummy config for an instrument that will use uncertainty
# This assumes the instrument's Pydantic config model (e.g., MultimeterConfig)
# now has a 'measurement_accuracy: Optional[dict[str, AccuracyModel]]' field.
UNC_DMM_CONFIG_DICT = {
    "device_type": "multimeter",
    "role": "measurement",
    "model": "UncertainDMM",
    "address": "SIM_ADDRESS_UNC_DMM",
    "measurement_accuracy": {
        "voltage_dc_10V": AccuracySpec(
            reading_percent=0.1, range_percent=0.1, offset=0.005
        ),  # 0.1% + 5mV
        "current_dc_1A": AccuracySpec(
            reading_percent=0.1, range_percent=0.1, offset=0.001
        ),  # 1mA fixed
    },
    # Add other mandatory fields for MultimeterConfig
}


def test_accuracy_spec_calculation():
    """Test the AccuracySpec.calculate_std_dev method."""
    spec = AccuracySpec(
        reading_percent=1.0,
        offset=0.1,
        distribution=UncertaintyDistribution.STANDARD,
    )
    reading = 10.0
    expected_sigma = ((0.01 * 10.0) ** 2 + 0.1**2) ** 0.5  # sqrt(0.1^2 + 0.1^2) = sqrt(0.02)
    assert spec.calculate_std_dev(reading) == pytest.approx(expected_sigma)

    spec_no_percent = AccuracySpec(offset=0.05, distribution=UncertaintyDistribution.STANDARD)
    assert spec_no_percent.calculate_std_dev(100.0) == 0.05

    spec_no_offset = AccuracySpec(
        reading_fraction=0.005,
        distribution=UncertaintyDistribution.STANDARD,
    )
    assert spec_no_offset.calculate_std_dev(20.0) == pytest.approx(0.005 * 20.0)

    spec_none = AccuracySpec()
    assert spec_none.calculate_std_dev(10.0) == 0.0


def test_driver_returns_measurement_quantity_with_sim():
    """Test that a driver method can return the PyTestLab uncertainty value object."""
    from unittest.mock import Mock
    from unittest.mock import patch

    from pytestlab import AutoInstrument
    from pytestlab.config.multimeter_config import MultimeterConfig

    # Create a mock config with measurement accuracy
    mock_config = MultimeterConfig(
        device_type="multimeter",
        role="measurement",
        manufacturer="TestCorp",
        model="UncertainDMM",
        address="SIM_ADDRESS_UNC_DMM",
        measurement_accuracy={
            "voltage_dc_10V": AccuracySpec(
                reading_percent=0.1,
                offset=0.005,
                distribution=UncertaintyDistribution.STANDARD,
            )
        },
    )

    # Mock the AutoInstrument to return our test instance
    with patch(
        "pytestlab.instruments.AutoInstrument.AutoInstrument.from_config"
    ) as mock_from_config:
        # Create a mock instrument that returns MeasurementQuantity values
        mock_dmm = Mock()
        expected_sigma = ((0.001 * 5.0) ** 2 + 0.005**2) ** 0.5
        mock_dmm.measure_voltage_dc.return_value = mock_config.measurement_accuracy[
            "voltage_dc_10V"
        ].quantity(5.0, unit="V")
        mock_dmm.config = mock_config
        mock_from_config.return_value = mock_dmm

        # Test the functionality
        dmm = AutoInstrument.from_config(mock_config, simulate=True)
        result = dmm.measure_voltage_dc(range="10V")

        # Verify the result is a MeasurementQuantity with correct values
        assert isinstance(result, MeasurementQuantity)
        assert result.nominal_value == pytest.approx(5.0)

        spec = mock_config.measurement_accuracy["voltage_dc_10V"]
        expected_sigma = spec.calculate_std_dev(5.0)
        assert result.std_dev == pytest.approx(expected_sigma, rel=1e-6)


def test_measurement_result_properties():
    """Test MeasurementResult nominal and sigma properties."""
    val_ufloat = ufloat(10.5, 0.2)
    res_ufloat = MeasurementResult(
        values=val_ufloat, instrument="test_instrument", units="V", measurement_type="voltage"
    )
    assert res_ufloat.nominal == 10.5
    assert res_ufloat.sigma == 0.2

    val_float = 20.0
    res_float = MeasurementResult(
        values=val_float, instrument="test_instrument", units="A", measurement_type="current"
    )
    assert res_float.nominal == 20.0
    assert res_float.sigma is None  # Or 0.0, depending on desired behavior for non-ufloats

    val_quantity = AccuracySpec(
        offset=0.2,
        distribution=UncertaintyDistribution.STANDARD,
    ).quantity(10.5, unit="V")
    res_quantity = MeasurementResult(
        values=val_quantity, instrument="test_instrument", units="V", measurement_type="voltage"
    )
    assert res_quantity.nominal == 10.5
    assert res_quantity.sigma == 0.2

    # Test with numpy array of ufloats (if supported by MeasurementResult)
    # arr_ufloat = np.array([ufloat(1,0.1), ufloat(2,0.2)])
    # res_arr_ufloat = MeasurementResult(name="test_arr_ufloat", values=arr_ufloat, unit="X")
    # assert np.array_equal(res_arr_ufloat.nominal, np.array([1,2]))
    # assert np.array_equal(res_arr_ufloat.sigma, np.array([0.1,0.2]))


def test_measurement_quantity_propagation_simple():
    """Test basic uncertainty propagation through MeasurementQuantity."""
    a = AccuracySpec(offset=0.1, distribution=UncertaintyDistribution.STANDARD).quantity(
        10, unit="V"
    )
    b = AccuracySpec(offset=0.05, distribution=UncertaintyDistribution.STANDARD).quantity(
        5, unit="V"
    )

    c = a + b
    assert c.nominal == pytest.approx(15)
    assert c.u == pytest.approx((0.1**2 + 0.05**2) ** 0.5)

    d = a * 2
    assert d.nominal == pytest.approx(20)
    assert d.u == pytest.approx(0.1 * 2)


def test_measurement_quantity_uses_unit_algebra_for_compound_units():
    voltage = AccuracySpec(
        offset=0.1,
        distribution=UncertaintyDistribution.STANDARD,
    ).quantity(2.0, unit="V")
    current = AccuracySpec(
        offset=0.01,
        distribution=UncertaintyDistribution.STANDARD,
    ).quantity(3.0, unit="A")

    power = voltage * current
    assert power.nominal == pytest.approx(6.0)
    assert "volt" in power.unit
    assert "ampere" in power.unit
    # Both offset atoms propagate through the product into the budget.
    entries = power.budget().entries
    assert len(entries) == 2
    assert {entry.label for entry in entries} == {"offset"}

    zero_voltage = AccuracySpec(
        offset=0.1,
        distribution=UncertaintyDistribution.STANDARD,
    ).quantity(0.0, unit="V")
    zero_power = zero_voltage * current
    assert zero_power.nominal == 0.0
    assert zero_power.u == pytest.approx(0.3)

    ratio = voltage / voltage
    assert ratio.unit == ""

    millivolts = AccuracySpec(
        offset=1.0,
        distribution=UncertaintyDistribution.STANDARD,
    ).quantity(1000.0, unit="mV")
    scaled_ratio = voltage / millivolts
    assert scaled_ratio.nominal == pytest.approx(2.0)
    assert scaled_ratio.unit == ""

    millivolt_sum = voltage + millivolts
    assert millivolt_sum.nominal == pytest.approx(3.0)
    assert millivolt_sum.unit == "V"

    with pytest.raises(UnitCompatibilityError):
        _ = voltage + current


def test_strict_accuracy_spec_rejects_ambiguous_percent_fields():
    with pytest.raises(ValidationError):
        AccuracySpec(percent_reading=0.01)


def test_profile_entry_points_accept_all_uncertainty_model_types():
    from pytestlab.config import dc_active_load_config
    from pytestlab.config import multimeter_config
    from pytestlab.config import power_supply_config
    from pytestlab.config import waveform_generator_config

    multimeter_range = multimeter_config.RangeSpec(
        accuracy={
            "model": "band_table",
            "variable": "reading",
            "bands": [{"min": 0.0, "max": 1.0, "reading_percent": 0.1}],
        }
    )
    assert isinstance(multimeter_range.accuracy, BandAccuracySpec)

    psu_range = power_supply_config.RangeSpec(
        min=0.0,
        max=10.0,
        accuracy={"model": "expression", "expression": "0.01*reading + 0.001*range"},
    )
    assert isinstance(psu_range.accuracy, ExpressionAccuracySpec)

    load_readback = dc_active_load_config.ReadbackAccuracySpec(
        voltage_accuracy={
            "model": "repeatability",
            "observations": [4.99, 5.01, 5.00],
            "unit": "V",
        }
    )
    assert isinstance(load_readback.voltage_accuracy, RepeatabilityAccuracySpec)

    waveform_range = waveform_generator_config.RangeSpec(
        min=0.0,
        max=10.0,
        accuracy={
            "model": "monte_carlo",
            "components": [{"model": "linear", "offset": 0.1}],
            "samples": 100,
            "seed": 1,
        },
    )
    assert isinstance(waveform_range.accuracy, MonteCarloAccuracySpec)

    instrument = InstrumentConfig(
        manufacturer="Test",
        model="Advanced",
        device_type="generic",
        role="measurement",
        measurement_accuracy={
            "vpp_ch1": {
                "model": "composite",
                "components": [
                    {"model": "linear", "offset": 0.02},
                    {"model": "expression", "expression": "0.01*reading"},
                ],
            }
        },
    )
    assert isinstance(instrument.measurement_accuracy["vpp_ch1"], CompositeBudgetSpec)


def test_generic_uncertainty_helper_evaluates_advanced_model():
    model = ExpressionAccuracySpec(
        expression="0.01*reading + 0.001*range",
        distribution=UncertaintyDistribution.STANDARD,
    )
    context = UncertaintyContext(reading=5.0, unit="V", range_value=10.0, range_unit="V")

    quantity = quantity_from_uncertainty_model(model, context)
    assert isinstance(quantity, MeasurementQuantity)
    assert quantity.u == pytest.approx(0.06)
    assert any(entry.label == "expression" for entry in quantity.budget().entries)


def test_power_supply_driver_uses_range_context_for_uncertainty_models():
    from unittest.mock import Mock

    from pytestlab.config.power_supply_config import ChannelSpec
    from pytestlab.config.power_supply_config import PowerSupplyConfig
    from pytestlab.config.power_supply_config import RangeSpec
    from pytestlab.instruments.PowerSupply import PowerSupply

    backend = Mock()
    backend.connect = Mock()
    backend.disconnect = Mock()
    backend.query = Mock(return_value="5.0")

    config = PowerSupplyConfig(
        manufacturer="Test",
        model="PSU",
        device_type="power_supply",
        role="stimulus",
        channels=[
            ChannelSpec(
                description="CH1",
                voltage_range=RangeSpec(min=0.0, max=10.0),
                current_limit_range=RangeSpec(min=0.0, max=1.0),
            )
        ],
        measurement_accuracy={
            "read_voltage_ch1": {
                "model": "linear",
                "range_percent": 1.0,
                "distribution": "standard",
            }
        },
    )
    psu = PowerSupply(config=config, backend=backend)
    psu._error_check = Mock()
    psu.scpi_engine = Mock(
        build=Mock(return_value=["MEAS:VOLT?"]),
        parse=Mock(return_value="5.0"),
    )

    reading = psu.read_voltage(1)

    assert isinstance(reading, MeasurementQuantity)
    assert reading.u == pytest.approx(0.1)


def test_oscilloscope_driver_uses_channel_context_for_uncertainty_models():
    from unittest.mock import Mock

    from pytestlab.config.base import Range
    from pytestlab.config.oscilloscope_config import Channel
    from pytestlab.config.oscilloscope_config import OscilloscopeConfig
    from pytestlab.config.oscilloscope_config import Timebase
    from pytestlab.config.oscilloscope_config import Trigger
    from pytestlab.instruments.Oscilloscope import Oscilloscope

    backend = Mock()
    backend.connect = Mock()
    backend.disconnect = Mock()
    backend.query = Mock(return_value="5.0")
    timebase = Timebase(range=Range(min_val=1e-9, max_val=1.0), horizontal_resolution=1e-9)

    config = OscilloscopeConfig(
        manufacturer="Test",
        model="Scope",
        device_type="oscilloscope",
        role="measurement",
        trigger=Trigger(types=["edge"], modes=["auto"], slopes=["rising"]),
        channels=[
            Channel(
                description="CH1",
                channel_range=Range(min_val=-5.0, max_val=5.0),
                input_coupling=["DC"],
                input_impedance=1e6,
                probe_attenuation=[1],
                timebase=timebase,
            )
        ],
        bandwidth=100e6,
        sampling_rate=1e9,
        memory=1e6,
        waveform_update_rate=1000.0,
        measurement_accuracy={
            "vpp_ch1": {
                "model": "expression",
                "expression": "0.01*reading + 0.001*bandwidth/1e6",
                "distribution": "standard",
            }
        },
    )
    scope = Oscilloscope(config=config, backend=backend)
    scope._error_check = Mock()
    scope.scpi_engine = Mock(
        build=Mock(return_value=["MEAS:VPP?"]),
        parse=Mock(return_value="5.0"),
    )

    result = scope.measure_voltage_peak_to_peak(1)

    assert isinstance(result.values, MeasurementQuantity)
    assert result.values.u == pytest.approx(0.15)


def test_dc_active_load_driver_uses_readback_range_for_uncertainty_models():
    from unittest.mock import Mock

    from pytestlab.config.dc_active_load_config import DCActiveLoadConfig
    from pytestlab.config.dc_active_load_config import ModeSpec
    from pytestlab.config.dc_active_load_config import OperatingModesSpec
    from pytestlab.config.dc_active_load_config import RangeSpec
    from pytestlab.config.dc_active_load_config import ReadbackAccuracySpec
    from pytestlab.instruments.DCActiveLoad import DCActiveLoad

    backend = Mock()
    backend.connect = Mock()
    backend.disconnect = Mock()
    backend.query = Mock(return_value="5.0")

    config = DCActiveLoadConfig(
        manufacturer="Test",
        model="Load",
        device_type="dc_active_load",
        role="measurement",
        operating_modes=OperatingModesSpec(
            constant_voltage_CV=ModeSpec(
                ranges=[
                    RangeSpec(
                        min=0.0,
                        max=10.0,
                        max_voltage_V=10.0,
                        readback_accuracy=ReadbackAccuracySpec(
                            voltage_accuracy={
                                "model": "linear",
                                "range_percent": 1.0,
                                "distribution": "standard",
                            }
                        ),
                    )
                ]
            )
        ),
    )
    load = DCActiveLoad(config=config, backend=backend)
    load.current_mode = "CV"
    load._error_check = Mock()

    def build(command, **kwargs):
        if command == "measure":
            return ["MEAS:VOLT?"]
        if command == "mode_get_range":
            return ["VOLT:RANG?"]
        raise AssertionError(command)

    def parse(command, response):
        if command == "measure":
            return "5.0"
        if command == "mode_get_range":
            return "10.2"
        raise AssertionError(command)

    load.scpi_engine = Mock(build=Mock(side_effect=build), parse=Mock(side_effect=parse))

    result = load.measure_voltage()

    assert isinstance(result.values, MeasurementQuantity)
    assert result.values.u == pytest.approx(0.1)


def test_profile_to_driver_to_database_uncertainty_round_trip(tmp_path):
    from unittest.mock import Mock

    from pytestlab.config.multimeter_config import DMMFunction
    from pytestlab.config.multimeter_config import MultimeterConfig
    from pytestlab.instruments.Multimeter import Multimeter

    profile_path = tmp_path / "profile_dmm.yaml"
    profile_path.write_text(
        yaml.safe_dump(
            {
                "device_type": "multimeter",
                "role": "measurement",
                "manufacturer": "Test",
                "model": "ProfileDMM",
                "measurement_functions": {
                    "dc_voltage": {
                        "ranges": [
                            {
                                "nominal_V": 10.0,
                                "resolution": 0.001,
                                "accuracy": {
                                    "model": "expression",
                                    "expression": "0.01*reading + 0.001*range",
                                    "distribution": "standard",
                                },
                            }
                        ]
                    }
                },
            }
        )
    )

    config = load_device_profile(profile_path)
    assert isinstance(config, MultimeterConfig)

    backend = Mock()
    backend.connect = Mock()
    backend.disconnect = Mock()
    backend.write = Mock()
    backend.query = Mock(
        side_effect=lambda query, delay=None: '0,"No error"' if "SYSTem:ERRor" in query else "5.0"
    )
    dmm = Multimeter(config=config, backend=backend)
    dmm.get_config = Mock(return_value=Mock(range_value=10.0))
    dmm.scpi_engine = Mock(build=Mock(return_value=["READ?"]))

    measurement = dmm.measure(DMMFunction.VOLTAGE_DC)
    assert isinstance(measurement.values, MeasurementQuantity)
    assert any(entry.label == "expression" for entry in measurement.values.budget().entries)

    with MeasurementDatabase(tmp_path / "profile_driver_db") as db:
        key = db.store_measurement(None, measurement)
        restored = db.retrieve_measurement(key)

    assert isinstance(restored.values, MeasurementQuantity)
    assert restored.values.nominal == pytest.approx(5.0)
    assert restored.values.u == pytest.approx(0.06)
    assert restored.values.unit == "V"
    assert restored.values.budget().entries[0].label == "expression"


def test_monte_carlo_model_is_reproducible():
    from pytestlab.uncertainty import AtomRegistry
    from pytestlab.uncertainty.montecarlo import monte_carlo

    # A rectangular offset (half-width 0.1) -> standard uncertainty 0.1/sqrt(3).
    reg = AtomRegistry()
    x = AccuracySpec(offset=0.1).quantity(
        UncertaintyContext(reading=10.0, unit="V"), reg
    )
    r1 = monte_carlo(lambda x: x, {"x": x}, samples=200_000, seed=42, registry=reg)
    r2 = monte_carlo(lambda x: x, {"x": x}, samples=200_000, seed=42, registry=reg)
    assert r1.std == r2.std  # identical seed -> reproducible
    assert r1.std == pytest.approx(0.1 / (3**0.5), rel=0.05)


def test_repeatability_and_composite_budget_models():
    context = UncertaintyContext(reading=10.0, unit="V")
    repeatability = RepeatabilityAccuracySpec(observations=[9.98, 10.01, 10.00], unit="V")
    composite = CompositeBudgetSpec(
        components=[
            AccuracySpec(offset=0.03, distribution=UncertaintyDistribution.STANDARD),
            repeatability,
        ]
    )
    budget = composite.evaluate(context)
    assert {entry.label for entry in budget.entries} == {"offset", "repeatability"}
    assert budget.effective_degrees_of_freedom is not None


def test_budget_coverage_factor_uses_effective_degrees_of_freedom():
    context = UncertaintyContext(reading=10.0, unit="V")
    repeatability = RepeatabilityAccuracySpec(observations=[9.98, 10.01, 10.00], unit="V")
    budget = repeatability.evaluate(context)

    assert budget.effective_degrees_of_freedom == pytest.approx(2.0)
    assert budget.coverage_factor_for(0.95) > 2.0


def test_db_serializes_measurement_quantity(tmp_path):
    quantity = AccuracySpec(
        reading_percent=1.0,
        offset=0.1,
        distribution=UncertaintyDistribution.STANDARD,
    ).quantity(10.0, unit="V")
    measurement = MeasurementResult(
        values=quantity, instrument="test_instrument", units="V", measurement_type="voltage"
    )
    with MeasurementDatabase(tmp_path / "uncertainty") as db:
        key = db.store_measurement(None, measurement)
        restored = db.retrieve_measurement(key)
    assert isinstance(restored.values, MeasurementQuantity)
    assert restored.values.nominal == pytest.approx(10.0)
    assert restored.values.u == pytest.approx(quantity.u)


def test_db_serializes_legacy_ufloat_values(tmp_path):
    measurement = MeasurementResult(
        values=ufloat(1.2, 0.03),
        instrument="test_instrument",
        units="V",
        measurement_type="voltage",
    )

    with MeasurementDatabase(tmp_path / "ufloat_uncertainty") as db:
        key = db.store_measurement(None, measurement)
        restored = db.retrieve_measurement(key)

    assert restored.values.nominal_value == pytest.approx(1.2)
    assert restored.values.std_dev == pytest.approx(0.03)
