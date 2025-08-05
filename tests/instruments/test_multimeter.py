"""
pytestlab/tests/instruments/test_multimeter.py

Comprehensive test suite for a real multimeter using the PyTestLab API.

This test covers all major features:
- Connection and identification
- DC/AC voltage measurements
- Resistance measurements
- Configuration retrieval
- Error handling
- Self-test

**NOTE:** This test requires a real multimeter connected and accessible via VISA.
Tests will be gracefully skipped if hardware is not available.

Run with:
    pytest -v pytestlab/tests/instruments/test_multimeter.py

Requires:
    pytest
    uncertainties
    pytestlab
"""

import pytest
from uncertainties.core import UFloat

from pytestlab.instruments import AutoInstrument
from pytestlab.config.multimeter_config import DMMFunction

# ------------------- CONFIGURE THESE FOR YOUR LAB -------------------
MM_CONFIG_KEY = "keysight/EDU34450A"
# --------------------------------------------------------------------

def check_hardware_available():
    """Check if multimeter hardware is available for testing."""
    try:
        mm = AutoInstrument.from_config(MM_CONFIG_KEY)
        mm.connect_backend()
        # Try to get IDN to verify connection
        idn = mm.id()
        mm.close()
        return True, None
    except Exception as e:
        return False, str(e)

@pytest.mark.requires_real_hw
def test_multimeter_instrument_identification():
    """Test instrument identification and connection."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        idn = mm.id()
        print(f"Instrument ID: {idn}")
        assert "KEYSIGHT" in idn.upper()
        assert "EDU34450A" in idn.upper()
        print("IDN Check: PASS")
    finally:
        mm.close()

@pytest.mark.requires_real_hw
def test_multimeter_dc_voltage_measurement():
    """Test DC voltage measurement with autorange."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        measurement = mm.measure(DMMFunction.VOLTAGE_DC)
        print(f"Measured DC Voltage: {measurement.values} {measurement.units}")
        assert isinstance(measurement.values, UFloat)
        assert measurement.units == "V"
        print("DC Voltage Measurement: PASS")
    finally:
        mm.close()

@pytest.mark.requires_real_hw
def test_multimeter_ac_voltage_measurement():
    """Test AC voltage measurement with fixed range."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        measurement = mm.measure(DMMFunction.VOLTAGE_AC, range_val="1")
        print(f"Measured AC Voltage: {measurement.values} {measurement.units}")
        assert isinstance(measurement.values, UFloat)
        assert measurement.units == "V"
        assert abs(measurement.values.n) <= 1.0
        print("AC Voltage Measurement: PASS")
    finally:
        mm.close()

@pytest.mark.requires_real_hw
def test_multimeter_resistance_measurement():
    """Test 4-wire resistance measurement."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        measurement = mm.measure(DMMFunction.FRESISTANCE)
        print(f"Measured Resistance: {measurement.values} {measurement.units}")
        assert isinstance(measurement.values, UFloat)
        assert measurement.units == "Ω"
        print("Resistance Measurement: PASS")
    finally:
        mm.close()

@pytest.mark.requires_real_hw
def test_multimeter_configuration_retrieval():
    """Test retrieving structured configuration."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        # Set a known state first
        mm.configure_measurement(DMMFunction.CURRENT_DC, range_val="0.1", resolution="MAX")
        config = mm.get_config()
        print(f"Current Configuration:\n{config}")
        assert config.measurement_mode == "Current"
        assert config.range_value == 0.1
        assert config.units == "A"
        print("Get Config: PASS")
    finally:
        mm.close()

@pytest.mark.requires_real_hw
def test_multimeter_error_handling():
    """Test system error checking."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        errors = mm.get_all_errors()
        print(f"System Error Query Response: {errors}")
        assert isinstance(errors, list) and len(errors) == 0
        print("Error Check: PASS")
    finally:
        mm.close()

@pytest.mark.requires_real_hw
def test_multimeter_self_test():
    """Test instrument self-test."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        result = mm.run_self_test()
        print(f"Self-test result: '{result}'")
        assert result == "Passed"
        print("Self-Test: PASS")
    finally:
        mm.close()

@pytest.mark.requires_real_hw
def test_multimeter_full_workflow():
    """Test complete multimeter workflow with multiple measurements."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Multimeter hardware not available: {error_msg}")

    mm = AutoInstrument.from_config(MM_CONFIG_KEY)
    mm.connect_backend()

    try:
        # Test sequence of different measurement types
        measurements = []

        # DC Voltage
        dc_v = mm.measure(DMMFunction.VOLTAGE_DC)
        measurements.append(("DC Voltage", dc_v))

        # AC Voltage
        ac_v = mm.measure(DMMFunction.VOLTAGE_AC, range_val="10")
        measurements.append(("AC Voltage", ac_v))

        # Resistance
        res = mm.measure(DMMFunction.RESISTANCE)
        measurements.append(("Resistance", res))

        # Verify all measurements
        for name, measurement in measurements:
            print(f"{name}: {measurement.values} {measurement.units}")
            # Handle both UFloat and float (for overload/open circuit conditions)
            assert isinstance(measurement.values, (UFloat, float))
            assert measurement.units in ["V", "Ω", "A"]

        # Check no errors accumulated
        errors = mm.get_all_errors()
        assert len(errors) == 0

        print("Full workflow test: PASS")
    finally:
        mm.close()
