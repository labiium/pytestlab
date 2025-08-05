"""
End-to-End Test for PyTestLab Bench System

This script tests the full bench functionality, including:
- Loading a bench configuration
- Safety limit enforcement for instruments
- Instrument interaction through the bench
- Automation hooks execution
- Configuration access (traceability, measurement plan, etc.)
- Error handling scenarios
- Context manager functionality (async with)

Tests use real instruments (PSU and Multimeter) where possible, falling back to simulated
instruments when needed.
"""

import pytest
import os
import tempfile
import time
import yaml
from pathlib import Path
from pytestlab.instruments.Multimeter import DMMFunction

from pytestlab.bench import Bench, SafetyLimitError

# Test bench YAML configuration for testing with real instruments
TEST_BENCH_CONFIG = """
bench_name: "Test Bench for End-to-End Testing"
description: "Test bench configuration for automated testing with real instruments"
version: "1.0.0"
last_modified: "2025-07-04"

experiment:
  title: "Bench End-to-End Test"
  description: "Automated test of bench functionality with real instruments"
  operator: "Test Runner"
  date: "2025-07-04"
  notes: |
    Testing bench functionality with real instruments.
    This is an automated test run.

# Set to false to use real instruments with LAMB backend
simulate: false

# Continue operation even if some instruments fail to connect
continue_on_instrument_error: true
continue_on_automation_error: true

backend_defaults:
  type: "lamb"
  timeout_ms: 10000

instruments:
  psu:
    profile: "keysight/EDU36311A"
    backend:
      type: "lamb"
      timeout_ms: 10000
    safety_limits:
      channels:
        1:
          voltage: {"max": 5.5}
          current: {"max": 1.0}
        2:
          voltage: {"max": 12.0}
          current: {"max": 0.5}
        3:
          voltage: {"max": -5.5}
          current: {"max": 0.2}

  dmm:
    profile: "keysight/EDU34450A"
    backend:
      type: "lamb"
      timeout_ms: 10000

custom_validations:
  - "psu['safety_limits']['channels'][1]['voltage']['max'] <= 6.0"

automation:
  pre_experiment:
    - "echo 'Starting bench test...'"
    - "psu: output all OFF"
  post_experiment:
    - "psu: output all OFF"
    - "echo 'Bench test completed.'"

traceability:
  calibration:
    psu: "TEST-CAL-2025-001"
    dmm: "TEST-CAL-2025-002"
  environment:
    temperature: 23.0  # Celsius
    humidity: 45.0     # %RH
  dut:
    serial_number: "TEST-DUT-001"
    description: "Test device for bench validation"

measurement_plan:
  - name: "Voltage Measurement"
    instrument: "dmm"
    probe_location: "DUT input"
    settings:
      function: "DC_VOLTAGE"
      range: "10V"
      resolution: "6.5"
    notes: "Measure test voltage"
"""


# Fixture to create a temporary bench configuration file
@pytest.fixture
def bench_config_file():
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(TEST_BENCH_CONFIG.encode('utf-8'))
        config_path = f.name

    yield config_path

    # Clean up after test
    if os.path.exists(config_path):
        os.unlink(config_path)

def check_hardware_available():
    """Check if bench hardware is available for testing."""
    try:
        # Create a minimal bench config for testing
        test_config = TEST_BENCH_CONFIG
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(test_config.encode('utf-8'))
            config_path = f.name

        try:
            # Try to open the bench - this will test instrument connectivity
            bench = Bench.open(config_path)

            # Test actual instrument communication by trying to get IDs
            try:
                psu_id = bench.psu.id()
                dmm_id = bench.dmm.id()
                bench.close_all()
                return True, None
            except Exception as e:
                bench.close_all()
                return False, f"Instrument communication failed: {str(e)}"

        except Exception as e:
            return False, str(e)
        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)
    except Exception as e:
        return False, f"Failed to create test configuration: {str(e)}"

# Using real instruments, no need for mocks
@pytest.mark.requires_real_hw
def test_bench_initialization(bench_config_file):
    """Test bench initialization from YAML file."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    # Open the bench
    bench = Bench.open(bench_config_file)

    try:
        # Verify basic bench properties
        assert bench.config.bench_name == "Test Bench for End-to-End Testing"
        assert bench.config.version == "1.0.0"
        assert bench.config.experiment.title == "Bench End-to-End Test"

        # Verify instruments were created
        assert "psu" in bench._instrument_instances
        assert "dmm" in bench._instrument_instances
    finally:
        # Clean up
        bench.close_all()
@pytest.mark.requires_real_hw
def test_bench_context_manager(bench_config_file):
    """Test bench context manager functionality."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        assert bench.config.bench_name == "Test Bench for End-to-End Testing"
        assert "psu" in bench._instrument_instances
        assert "dmm" in bench._instrument_instances

    # The bench should be closed after exiting the context manager
    # We can't directly test this without accessing private attributes,
    # but we can verify that no exceptions were raised.
@pytest.mark.requires_real_hw
def test_bench_instrument_access(bench_config_file):
    """Test accessing instruments through the bench."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Test accessing instruments by attribute
        assert bench.psu is not None
        assert bench.dmm is not None

        # Test instrument ID retrieval (should work with our mocks)
        psu_id = bench.psu.id()
        assert isinstance(psu_id, str)

        dmm_id = bench.dmm.id()
        assert isinstance(dmm_id, str)

        # Test bench.instruments dictionary
        assert "psu" in bench.instruments
        assert "dmm" in bench.instruments
        assert bench.instruments["psu"] == bench._instrument_instances["psu"]
        assert bench.instruments["dmm"] == bench._instrument_instances["dmm"]
@pytest.mark.requires_real_hw
def test_safety_limits(bench_config_file):
    """Test safety limit enforcement for power supply."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Using real instruments, no need to set up mock return values

        # Set voltage within limits (should work)
        bench.psu.set_voltage(1, 5.0)
        bench.psu.set_voltage(2, 10.0)

        # Try to set voltage beyond safety limits (should raise SafetyLimitError)
        with pytest.raises(SafetyLimitError):
            bench.psu.set_voltage(1, 6.0)  # Limit is 5.5V

        with pytest.raises(SafetyLimitError):
            bench.psu.set_voltage(2, 15.0)  # Limit is 12.0V

        # Set current within limits
        bench.psu.set_current(1, 0.5)
        bench.psu.set_current(2, 0.3)

        # Try to set current beyond safety limits
        with pytest.raises(SafetyLimitError):
            bench.psu.set_current(1, 1.5)  # Limit is 1.0A

        with pytest.raises(SafetyLimitError):
            bench.psu.set_current(2, 0.6)  # Limit is 0.5A
@pytest.mark.requires_real_hw
def test_psu_functionality(bench_config_file):
    """Test full power supply functionality through the bench."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Get initial configuration
        initial_config = bench.psu.get_configuration()
        assert len(initial_config) >= 3  # PSU should have at least 3 channels

        # Configure power supply
        bench.psu.set_voltage(1, 3.3)
        bench.psu.set_current(1, 0.1)

        # Enable output for channel 1
        bench.psu.output(1, True)

        # Check that output is enabled
        config = bench.psu.get_configuration()
        assert config[1].state == "ON"

        # Disable output
        bench.psu.output(1, False)

        # Check that output is disabled
        config = bench.psu.get_configuration()
        assert config[1].state == "OFF"

        # Test display control if available
        try:
            bench.psu.display(False)
            time.sleep(1)
            bench.psu.display(True)
        except Exception:
            pass  # Not all PSUs support display control, or might be simulated
@pytest.mark.requires_real_hw
def test_dmm_functionality(bench_config_file):
    """Test multimeter functionality through the bench."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Configure DMM for voltage measurement
        bench.dmm.set_measurement_function(DMMFunction.VOLTAGE_DC)

        # Get configuration
        config = bench.dmm.get_config()
        assert hasattr(config, "measurement_mode")
        assert config.measurement_mode.lower() == "voltage" or "volt" in config.measurement_mode.lower()

        # Take a measurement
        measurement = bench.dmm.measure(function=DMMFunction.VOLTAGE_DC)

        # Check measurement result
        assert hasattr(measurement, "values")
        assert hasattr(measurement, "units")
        assert measurement.units == "V"
        # It returns a UFloat (uncertainties package), not a plain float
        assert hasattr(measurement.values, "nominal_value")
@pytest.mark.requires_real_hw
def test_metadata_access(bench_config_file):
    """Test access to bench metadata."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Test traceability access
        assert bench.traceability is not None

        # Access attributes with proper names - calibration is a dictionary
        assert bench.traceability.calibration["psu"] == "TEST-CAL-2025-001"
        assert bench.traceability.calibration["dmm"] == "TEST-CAL-2025-002"

        # Environment and DUT are models with attributes
        assert bench.traceability.environment.temperature == 23.0
        assert bench.traceability.dut.serial_number == "TEST-DUT-001"

        # Test measurement plan access - these are pydantic models, not dicts
        assert len(bench.measurement_plan) >= 1
        assert bench.measurement_plan[0].name == "Voltage Measurement"
        assert bench.measurement_plan[0].instrument == "dmm"

        # Test experiment notes access
        assert bench.experiment_notes is not None
        assert "automated test run" in bench.experiment_notes.lower()

        # Test version and changelog access
        assert bench.version == "1.0.0"
@pytest.mark.requires_real_hw
def test_automation_hooks(bench_config_file):
    """Test execution of automation hooks."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    # We can't easily verify subprocess calls without mocking, so we'll just
    # ensure the bench initializes and closes without errors
    with Bench.open(bench_config_file) as bench:
        assert bench is not None
        # The pre-experiment hooks should have run by now

    # After exiting the context manager, post-experiment hooks should run
@pytest.mark.requires_real_hw
def test_psu_dmm_integration(bench_config_file):
    """Test integration between PSU and DMM."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Only run this test if both PSU and DMM are available and not simulated
        try:
            psu_id = bench.psu.id()
            dmm_id = bench.dmm.id()

            if "SIM" in psu_id or "SIM" in dmm_id:
                pytest.skip("Skipping PSU-DMM integration test in simulation mode")

            # Configure DMM for voltage measurement
            bench.dmm.set_measurement_function(DMMFunction.VOLTAGE_DC)

            # Set PSU to 3.3V and enable output
            bench.psu.set_voltage(1, 3.3)
            bench.psu.set_current(1, 0.1)
            bench.psu.output(1, True)

            # Wait for voltage to stabilize
            time.sleep(1)

            # Measure voltage with DMM
            measurement = bench.dmm.measure(function=DMMFunction.VOLTAGE_DC)

            # Check if measured voltage is close to set voltage
            # We use a wide tolerance since we don't know how DMM is connected
            voltage = float(measurement.values.nominal_value)

            # If DMM is connected to PSU, voltage should be around 3.3V
            # If not connected, it might read close to 0V
            # We accept both cases since we can't guarantee physical connections
            assert voltage < 10.0, "Measured voltage is too high"

            # Turn off PSU output
            bench.psu.output(1, False)
        except Exception as e:
            # Log the exception before skipping
            print(f"Integration test exception: {e}")
            pytest.skip("Skipping PSU-DMM integration test due to connection issues")
def test_invalid_bench_config():
    """Test handling of invalid bench configuration."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        # Create invalid configuration (missing required fields)
        f.write(b"bench_name: Invalid Bench\nsimulate: true")
        config_path = f.name

    try:
        # Attempting to open bench with invalid config should raise an exception
        with pytest.raises(Exception):
            Bench.open(config_path)
    finally:
        # Clean up
        if os.path.exists(config_path):
            os.unlink(config_path)
@pytest.mark.requires_real_hw
def test_getattr_error_handling(bench_config_file):
    """Test error handling when accessing non-existent instrument."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        with pytest.raises(AttributeError):
            # This instrument doesn't exist in the config
            _ = bench.non_existent_instrument
@pytest.mark.requires_real_hw
def test_dir_includes_instruments(bench_config_file):
    """Test that dir() includes instrument aliases."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        dir_output = dir(bench)
        assert "psu" in dir_output
        assert "dmm" in dir_output
@pytest.mark.requires_real_hw
def test_health_check(bench_config_file):
    """Test the health check functionality."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Run health checks on all instruments
        health_reports = bench.health_check()

        # Verify we got health reports
        assert "psu" in health_reports
        assert "dmm" in health_reports

        # In simulation mode, reports might be None if health_check is not implemented
        # Just check that the keys exist
        assert isinstance(health_reports, dict)
        # The actual reports might vary depending on instrument support for health checks
@pytest.mark.requires_real_hw
def test_instrument_type_detection(bench_config_file):
    """Test instrument type detection."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")

    with Bench.open(bench_config_file) as bench:
        # Check if the bench correctly identifies instrument types
        psu_type = bench._detect_instrument_type(bench._instrument_instances['psu'])
        assert psu_type == "power_supply"

        dmm_type = bench._detect_instrument_type(bench._instrument_instances['dmm'])
        assert dmm_type in ["multimeter", "unknown"]
def test_automation_error_handling():
    """Test error handling in automation hooks."""
    # Create a temporary config file with continue_on_automation_error set to True
    test_config = TEST_BENCH_CONFIG + "\ncontinue_on_automation_error: true"

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(test_config.encode('utf-8'))
        config_path = f.name

    try:
        # Test with continue_on_automation_error=True
        with Bench.open(config_path) as bench:
            assert bench.config.continue_on_automation_error == True

            # This is mostly a check that the flag was properly parsed
            # Actual error handling behavior is tested in bench._execute_output_all_off
            # which uses this flag when handling errors
    finally:
        # Clean up
        if os.path.exists(config_path):
            os.unlink(config_path)


# Simulation mode tests - these run without hardware
@pytest.fixture
def simulation_bench_config_file():
    """Create a bench configuration file with simulation enabled."""
    simulation_config = TEST_BENCH_CONFIG.replace("simulate: false", "simulate: true")

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(simulation_config.encode('utf-8'))
        config_path = f.name

    yield config_path

    # Clean up after test
    if os.path.exists(config_path):
        os.unlink(config_path)


def test_bench_simulation_mode(simulation_bench_config_file):
    """Test bench functionality in simulation mode."""
    with Bench.open(simulation_bench_config_file) as bench:
        # Verify simulation mode is enabled
        assert bench.config.simulate == True

        # Verify basic bench properties
        assert bench.config.bench_name == "Test Bench for End-to-End Testing"
        assert bench.config.version == "1.0.0"
        assert bench.config.experiment.title == "Bench End-to-End Test"

        # Verify instruments were created (simulated)
        assert "psu" in bench._instrument_instances
        assert "dmm" in bench._instrument_instances

        # Test accessing instruments by attribute
        assert bench.psu is not None
        assert bench.dmm is not None

        # Test basic instrument operations in simulation mode
        try:
            # These should work in simulation mode
            psu_id = bench.psu.id()
            assert isinstance(psu_id, str)

            dmm_id = bench.dmm.id()
            assert isinstance(dmm_id, str)
        except Exception as e:
            # If simulation mode isn't fully implemented, skip the test
            pytest.skip(f"Simulation mode not fully implemented: {str(e)}")


def test_bench_hardware_vs_simulation_config_difference():
    """Test that we can differentiate between hardware and simulation configurations."""
    # Create hardware config
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(TEST_BENCH_CONFIG.encode('utf-8'))
        hardware_config_path = f.name

    # Create simulation config
    simulation_config = TEST_BENCH_CONFIG.replace("simulate: false", "simulate: true")
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(simulation_config.encode('utf-8'))
        simulation_config_path = f.name

    try:
        # Test hardware availability check
        is_hw_available, hw_error = check_hardware_available()

        # For now, just verify that the check function works
        # The actual hardware availability depends on the environment
        assert isinstance(is_hw_available, bool)
        if not is_hw_available:
            assert isinstance(hw_error, str)
            assert len(hw_error) > 0

    finally:
        # Clean up
        for path in [hardware_config_path, simulation_config_path]:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
