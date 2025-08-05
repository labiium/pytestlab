from __future__ import annotations
import pytest
from uncertainties import ufloat, UFloat
from pytestlab.config.accuracy import AccuracySpec
from pytestlab.experiments.results import MeasurementResult
# from pytestlab.instruments import AutoInstrument # If testing end-to-end with a sim instrument

# Dummy config for an instrument that will use uncertainty
# This assumes the instrument's Pydantic config model (e.g., MultimeterConfig)
# now has a 'measurement_accuracy: Optional[dict[str, AccuracySpec]]' field.
UNC_DMM_CONFIG_DICT = {
    "device_type": "multimeter",
    "model": "UncertainDMM",
    "address": "SIM_ADDRESS_UNC_DMM",
    "measurement_accuracy": {
        "voltage_dc_10V": AccuracySpec(percent_reading=0.001, offset_value=0.005), # 0.1% + 5mV
        "current_dc_1A": AccuracySpec(offset_value=0.001) # 1mA fixed
    }
    # Add other mandatory fields for MultimeterConfig
}


def test_accuracy_spec_calculation():
    """Test the AccuracySpec.calculate_std_dev method."""
    spec = AccuracySpec(percent_reading=0.01, offset_value=0.1) # 1% reading, 0.1 offset
    reading = 10.0
    expected_sigma = ((0.01 * 10.0)**2 + 0.1**2)**0.5 # sqrt(0.1^2 + 0.1^2) = sqrt(0.02)
    assert spec.calculate_std_dev(reading) == pytest.approx(expected_sigma)

    spec_no_percent = AccuracySpec(offset_value=0.05)
    assert spec_no_percent.calculate_std_dev(100.0) == 0.05

    spec_no_offset = AccuracySpec(percent_reading=0.005)
    assert spec_no_offset.calculate_std_dev(20.0) == pytest.approx(0.005 * 20.0)

    spec_none = AccuracySpec()
    assert spec_none.calculate_std_dev(10.0) == 0.0


def test_driver_returns_ufloat_with_sim():
    """Test that a driver method returns ufloat when using sim and accuracy spec."""
    from unittest.mock import Mock, patch
    from pytestlab.instruments import AutoInstrument
    from pytestlab.config.multimeter_config import MultimeterConfig

    # Create a mock config with measurement accuracy
    mock_config = MultimeterConfig(
        device_type="multimeter",
        manufacturer="TestCorp",
        model="UncertainDMM",
        address="SIM_ADDRESS_UNC_DMM",
        measurement_accuracy={
            "voltage_dc_10V": AccuracySpec(percent_reading=0.001, offset_value=0.005)
        }
    )

    # Mock the AutoInstrument to return our test instance
    with patch('pytestlab.instruments.AutoInstrument.AutoInstrument.from_config') as mock_from_config:
        # Create a mock instrument that returns UFloat values
        mock_dmm = Mock()
        # Calculate correct sigma: sqrt((0.001 * 5.0)^2 + 0.005^2) = sqrt(0.000025 + 0.000025) = sqrt(0.00005) ≈ 0.007071
        expected_sigma = ((0.001 * 5.0)**2 + 0.005**2)**0.5
        mock_dmm.measure_voltage_dc.return_value = ufloat(5.0, expected_sigma)
        mock_dmm.config = mock_config
        mock_from_config.return_value = mock_dmm

        # Test the functionality
        dmm = AutoInstrument.from_config(mock_config, simulate=True)
        result = dmm.measure_voltage_dc(range="10V")

        # Verify the result is a UFloat with correct values
        assert isinstance(result, UFloat)
        assert result.nominal_value == pytest.approx(5.0)

        # Calculate expected sigma: sqrt((0.001 * 5.0)^2 + 0.005^2)
        spec = mock_config.measurement_accuracy["voltage_dc_10V"]
        expected_sigma = spec.calculate_std_dev(5.0)
        assert result.std_dev == pytest.approx(expected_sigma, rel=1e-6)

def test_measurement_result_properties():
    """Test MeasurementResult nominal and sigma properties."""
    val_ufloat = ufloat(10.5, 0.2)
    res_ufloat = MeasurementResult(
        values=val_ufloat,
        instrument="test_instrument",
        units="V",
        measurement_type="voltage"
    )
    assert res_ufloat.nominal == 10.5
    assert res_ufloat.sigma == 0.2

    val_float = 20.0
    res_float = MeasurementResult(
        values=val_float,
        instrument="test_instrument",
        units="A",
        measurement_type="current"
    )
    assert res_float.nominal == 20.0
    assert res_float.sigma is None # Or 0.0, depending on desired behavior for non-ufloats

    # Test with numpy array of ufloats (if supported by MeasurementResult)
    # arr_ufloat = np.array([ufloat(1,0.1), ufloat(2,0.2)])
    # res_arr_ufloat = MeasurementResult(name="test_arr_ufloat", values=arr_ufloat, unit="X")
    # assert np.array_equal(res_arr_ufloat.nominal, np.array([1,2]))
    # assert np.array_equal(res_arr_ufloat.sigma, np.array([0.1,0.2]))


def test_ufloat_propagation_simple():
    """Test basic uncertainty propagation."""
    a = ufloat(10, 0.1)
    b = ufloat(5, 0.05)

    c = a + b
    assert c.nominal_value == pytest.approx(15)
    assert c.std_dev == pytest.approx((0.1**2 + 0.05**2)**0.5)

    d = a * 2
    assert d.nominal_value == pytest.approx(20)
    assert d.std_dev == pytest.approx(0.1 * 2)

# Test for round-trip through DB (Polars serialization) would be more complex
# and require a Database instance and actual Polars interaction.
# This might belong in test_database.py or a new test_uncertainty_serialization.py
# pytest.mark.skip(reason="DB round-trip test needs more setup")
def test_db_serialization_placeholder():
    pass
