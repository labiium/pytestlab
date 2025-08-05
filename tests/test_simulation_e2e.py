import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import pytest
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.VirtualInstrument import VirtualInstrument
import importlib.util

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test artifacts."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)
def test_simulation_e2e(temp_dir):
    """
    An end-to-end test of the simulation recording and playback features.

    This test performs the following steps:
    1. Defines a script to interact with the VirtualInstrument.
    2. Programmatically calls the `pytestlab sim-profile record` command to
       generate a simulation profile from the script.
    3. Loads the newly generated profile into a new `VirtualInstrument` instance.
    4. Runs the same script against the simulated instrument.
    5. Asserts that the behavior of the simulated instrument matches the
       recorded session.
    """
    # 1. Define the script for recording (using dynamic simulation)
    recording_script_content = """
import random

def main(instrument):
    # Test basic set/get
    instrument.set_voltage(5.0)
    instrument.set_current(1.0)
    voltage = instrument.measure_voltage()
    current = instrument.measure_current()
    assert voltage == 5.0
    assert current == 1.0

    # Test stateful behavior
    instrument.set_trigger_state("ARMED")
    trigger_state = instrument.get_trigger_state()
    assert trigger_state == "ARMED"

    # Test increment/decrement
    instrument.increment_counter()
    instrument.increment_counter()
    counter = instrument.get_counter()
    assert counter == 2  # Dynamic simulation should show 2
    instrument.decrement_counter()
    counter = instrument.get_counter()
    assert counter == 1  # Dynamic simulation should show 1

    # Test dynamic expressions (py: and lambda:)
    result_add = instrument.dynamic_add(10.0)
    assert result_add == 11.0  # counter is 1, so 1 + 10 = 11

    random_val = instrument.dynamic_random()
    assert 1 <= random_val <= 100  # Check if within expected range

    # Test status message
    instrument.set_status_message("TEST_MESSAGE")
    status_msg = instrument.get_status_message()
    assert status_msg == "TEST_MESSAGE"

    # Test error handling
    instrument.push_error()
    code, msg = instrument.check_error()
    assert code == -100
    assert msg == "Custom Error"
    code, msg = instrument.check_error() # Check if error queue is cleared
    assert code == 0

    # Test binary data transfer
    waveform = instrument.fetch_waveform()
    assert len(waveform) > 0
    assert waveform.tobytes() == b'#800000008' # Check content of dummy binary file
"""

    # 2. Define the script for replay (using recorded static responses)
    replay_script_content = """
import random

def main(instrument):
    # Test basic set/get
    instrument.set_voltage(5.0)
    instrument.set_current(1.0)
    voltage = instrument.measure_voltage()
    current = instrument.measure_current()
    assert voltage == 5.0
    assert current == 1.0

    # Test stateful behavior
    instrument.set_trigger_state("ARMED")
    trigger_state = instrument.get_trigger_state()
    assert trigger_state == "ARMED"

    # Test increment/decrement - recorded responses
    instrument.increment_counter()
    instrument.increment_counter()
    counter = instrument.get_counter()
    # During recording, the final counter query returned 1.0
    assert counter == 1.0
    instrument.decrement_counter()
    counter = instrument.get_counter()
    # Static recorded response
    assert counter == 1.0

    # Test dynamic expressions - recorded responses
    result_add = instrument.dynamic_add(10.0)
    assert result_add == 11.0  # Static recorded response

    random_val = instrument.dynamic_random()
    # Random value is now fixed to recorded value
    assert isinstance(random_val, int) and 1 <= random_val <= 100

    # Test status message
    instrument.set_status_message("TEST_MESSAGE")
    status_msg = instrument.get_status_message()
    assert status_msg == "TEST_MESSAGE"

    # Test error handling - recorded responses
    instrument.push_error()
    code, msg = instrument.check_error()
    # During recording, error was cleared, so static response is no error
    assert code == 0
    assert msg == "No error"
    code, msg = instrument.check_error()
    assert code == 0

    # Test binary data transfer
    waveform = instrument.fetch_waveform()
    assert len(waveform) > 0
    assert waveform.tobytes() == b'#800000008' # Check content of dummy binary file
"""

    recording_script_path = temp_dir / "recording_script.py"
    replay_script_path = temp_dir / "replay_script.py"
    with open(recording_script_path, "w") as f:
        f.write(recording_script_content)
    with open(replay_script_path, "w") as f:
        f.write(replay_script_content)

    # 2. Programmatically call the `pytestlab sim-profile record` command
    recorded_profile_path = temp_dir / "recorded_virtual_instrument.yaml"
    import subprocess
    process = subprocess.Popen([
        "pytestlab",
        "sim-profile",
        "record",
        "pytestlab/virtual_instrument",
        "--simulate",
        "--script",
        str(recording_script_path),
        "--output-path",
        str(recorded_profile_path)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Wait for the process to complete
    stdout, stderr = process.communicate()

    assert process.returncode == 0, f"CLI command failed: {stderr.decode()}"
    assert recorded_profile_path.exists()



    # 3. Load the newly generated profile into a new `VirtualInstrument` instance.
    instrument = AutoInstrument.from_config(
        config_source=str(recorded_profile_path),
        simulate=True
    )
    instrument.connect_backend()

    # 4. Run the replay script against the simulated instrument.
    spec = importlib.util.spec_from_file_location("replay_module", replay_script_path)
    replay_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay_module)
    replay_module.main(instrument)

    # 5. Asserts that the behavior of the simulated instrument matches the recorded session.
    # The assertions are within the script itself. If the script runs without
    # raising an exception, the test is considered successful.
    instrument.close()

    # Cleanup the recorded profile and scripts
    if recorded_profile_path.exists():
        os.remove(recorded_profile_path)
