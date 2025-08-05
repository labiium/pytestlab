"""
End-to-End Test for Bench, MeasurementSession, and Database Integration

This script tests the full integration between the Bench, MeasurementSession,
and MeasurementDatabase classes.
"""

import pytest
import os
import tempfile
import time
import yaml
from pathlib import Path
import polars as pl

from pytestlab.bench import Bench
from pytestlab.measurements.session import MeasurementSession
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.instruments.Multimeter import DMMFunction

# Test bench YAML configuration with a database path
TEST_BENCH_CONFIG_WITH_DB = """
bench_name: "Integration Test Bench"
description: "Test bench for integration of Bench, Session, and Database"
version: "1.0.0"
last_modified: "2025-07-04"

experiment:
  title: "Bench Integration Test"
  description: "Automated test of full system integration"
  operator: "Test Runner"
  date: "2025-07-04"
  database_path: "{db_path}"
  notes: |
    Testing full integration of the measurement system.

simulate: false

# Continue operation even if some instruments fail to connect
continue_on_instrument_error: true
continue_on_automation_error: true

backend_defaults:
  type: "lamb"

instruments:
  psu:
    profile: "keysight/EDU36311A"
    backend:
      type: "lamb"
  dmm:
    profile: "keysight/EDU34450A"
    backend:
      type: "lamb"

automation:
  pre_experiment:
    - "echo 'Starting integration test...'"
  post_experiment:
    - "echo 'Integration test completed.'"
"""


@pytest.fixture
def db_path():
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)

def check_hardware_available():
    """Check if bench hardware is available for testing."""
    try:
        # Create a minimal bench config for testing
        test_config = TEST_BENCH_CONFIG_WITH_DB.format(db_path="/tmp/test.db")
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


@pytest.fixture
def bench_config_file_with_db(db_path):
    """Create a temporary bench configuration file with a database path."""
    config_content = TEST_BENCH_CONFIG_WITH_DB.format(db_path=db_path)
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(config_content.encode('utf-8'))
        config_path = f.name
    yield config_path
    if os.path.exists(config_path):
        os.unlink(config_path)
@pytest.mark.requires_real_hw
def test_bench_session_database_integration(bench_config_file_with_db, db_path):
    """Test the full integration of Bench, MeasurementSession, and MeasurementDatabase."""
    # Check if hardware is available
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Hardware not available: {error_msg}")
    with Bench.open(bench_config_file_with_db) as bench:
        assert bench.experiment is not None
        assert bench.db is not None
        assert bench.db.db_path == Path(db_path)

        with MeasurementSession(bench=bench) as session:
            # The session should inherit the experiment from the bench
            assert session.name == "Bench Integration Test"
            assert session._experiment is bench.experiment

            # Define a parameter for the sweep
            session.parameter("voltage", [1.0, 2.0, 3.0], unit="V")

            # Define a measurement function that uses instruments from the bench
            @session.acquire
            def measure_voltage(voltage: float, psu, dmm):
                psu.set_voltage(1, voltage)
                psu.set_current(1, 0.1)
                psu.output(1, True)
                time.sleep(0.1)  # Wait for voltage to stabilize

                measurement = dmm.measure(function=DMMFunction.VOLTAGE_DC)

                psu.output(1, False)

                return {"measured_voltage": float(measurement.values.nominal_value)}

            # Run the measurement session
            experiment = session.run(show_progress=False)

            # The experiment data should be populated
            assert isinstance(experiment.data, pl.DataFrame)
            assert len(experiment.data) == 3
            assert "voltage" in experiment.data.columns
            assert "measured_voltage" in experiment.data.columns

    # After the bench context closes, the experiment should be saved to the database
    db = MeasurementDatabase(db_path)
    experiments = db.list_experiments()
    assert len(experiments) == 1

    codename = experiments[0]
    retrieved_experiment = db.retrieve_experiment(codename)

    assert retrieved_experiment.name == "Bench Integration Test"
    assert "integration" in retrieved_experiment.description
    assert len(retrieved_experiment.data) == 3
    assert "measured_voltage" in retrieved_experiment.data.columns


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
