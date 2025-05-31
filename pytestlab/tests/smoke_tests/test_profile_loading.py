import pytest
import glob
import os
from pydantic import ValidationError

from pytestlab.config.loader import load_profile
from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.errors import InstrumentParameterError # Assuming this might be raised by contract operations
from pytestlab.common.health import HealthStatus, HealthReport # Added for health_check

# Define the path to the profiles directory
PROFILES_DIR = "pytestlab/profiles"

def discover_yaml_files(directory):
    """Discovers all .yaml files in the given directory and its subdirectories."""
    return glob.glob(os.path.join(directory, "**", "*.yaml"), recursive=True)

# Get all YAML profile paths
profile_paths = discover_yaml_files(PROFILES_DIR)
if not profile_paths:
    # Handle case where no profiles are found to avoid pytest collection errors
    # You might want to raise an error or skip tests if no profiles are expected
    print(f"Warning: No YAML profiles found in {PROFILES_DIR}. Smoke tests will be skipped.")

@pytest.mark.parametrize("profile_path", profile_paths)
def test_profile_loading_and_basic_instrument_operations(profile_path):
    """
    Tests loading of a YAML profile, instantiation of the instrument in simulation mode,
    and basic instrument contract operations.
    """
    # 1. Load the profile
    try:
        profile_config = load_profile(profile_path)
        assert profile_config is not None, f"Profile loading failed for {profile_path}"
    except ValidationError as e:
        pytest.fail(f"Profile {profile_path} failed validation: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred while loading profile {profile_path}: {e}")

    # 2. Instantiate the corresponding instrument in simulation mode
    try:
        instrument = AutoInstrument.from_config(profile_path, simulate=True)
        assert instrument is not None, f"Instrument instantiation failed for {profile_path}"
    except Exception as e:
        pytest.fail(f"Failed to instantiate instrument from profile {profile_path} in simulation mode: {e}")

    # 3. Perform basic "contract" operations
    try:
        # IDN Query
        idn_str = instrument.id()
        assert isinstance(idn_str, str), f"IDN string for {profile_path} is not a string: {type(idn_str)}"
        assert len(idn_str) > 0, f"IDN string for {profile_path} is empty"

        # Reset
        instrument.reset()  # Assert no exception

        # Health Check
        health_report = instrument.health_check()
        assert isinstance(health_report, HealthReport), f"Health check for {profile_path} did not return a HealthReport object"
        # In simulation, we expect OK or WARNING (if some simulated features are 'missing')
        # but not ERROR unless the simulation itself is broken.
        assert health_report.status in [HealthStatus.OK, HealthStatus.WARNING], \
            f"Health check for {profile_path} returned status {health_report.status}. Report: {health_report.model_dump_json(indent=2)}"
        if health_report.status == HealthStatus.WARNING:
            print(f"Warning: Health check for {profile_path} returned WARNING. Warnings: {health_report.warnings}")
        if health_report.errors:
             pytest.fail(f"Health check for {profile_path} reported errors: {health_report.errors}")


        # Close
        instrument.close()  # Assert no exception

        # Optional: Query a few simple, common parameters (example)
        # This part is highly dependent on the instrument types and their common parameters.
        # For a generic test, this might be difficult.
        # If specific common parameters exist across many simulated instruments, they can be added here.
        # For example, if all instruments had a 'status' query:
        # status = instrument.query("*STB?") # Example SCPI command
        # assert isinstance(status, str)

    except InstrumentParameterError as e:
        pytest.fail(f"Instrument parameter error during contract operations for {profile_path} with {instrument.config.model}: {e}")
    except NotImplementedError:
        # Some simulated instruments might not implement all methods
        print(f"Warning: A standard operation (id, reset, close, health_check) might not be implemented for {instrument.config.model} from {profile_path}")
    except Exception as e:
        pytest.fail(f"An error occurred during basic contract operations for {profile_path} with {instrument.config.model}: {e}")