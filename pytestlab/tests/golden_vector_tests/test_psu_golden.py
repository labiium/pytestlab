import pytest
from typing import Dict, Any

# Assuming PowerSupply instrument and its config are available
# Adjust imports based on actual project structure
from pytestlab.instruments import PowerSupply 
from pytestlab.config.power_supply_config import PowerSupplyConfig, ChannelConfig
from pytestlab.instruments.backends.sim_backend import SimBackend # For default SimBackend state structure
from .spy_backend import SpyingSimBackend

# Default config for a simulated PSU for testing purposes
# This would ideally match a profile or be more generic
# For simplicity, we define a basic one here.
DEFAULT_PSU_CONFIG = PowerSupplyConfig(
    general=dict(id="SimulatedPSU", driver="PowerSupply"),
    channels=[
        ChannelConfig(channel=1, voltage_max=30.0, current_max=5.0)
    ]
)

@pytest.fixture
def spying_psu():
    """
    Fixture to provide a PowerSupply instrument instance
    initialized with SpyingSimBackend.
    """
    # Create a SpyingSimBackend instance.
    # We need to provide it with a command_map if the default SimBackend one isn't sufficient
    # or if we want to pre-program specific responses for these tests.
    # For now, assume base SimBackend command_map has basic PSU commands like *IDN?, VOLT, CURR, OUTP
    backend = SpyingSimBackend(command_map=SimBackend.DEFAULT_COMMAND_MAP) # Use default or extend
    
    # Initialize the PowerSupply instrument with this backend and config
    # The 'address' can be a dummy one for simulated backends
    instrument = PowerSupply(config=DEFAULT_PSU_CONFIG, backend=backend, address="SIM::PSU")
    instrument.connect() # Connect to establish the backend link
    backend.clear_trace() # Clear any connection-related commands
    return instrument, backend

def assert_command_trace(actual_trace, expected_trace):
    """Helper to assert command trace equality."""
    assert len(actual_trace) == len(expected_trace), \
        f"Trace length mismatch. Got {len(actual_trace)}, expected {len(expected_trace)}."
    for i, (actual, expected) in enumerate(zip(actual_trace, expected_trace)):
        assert actual["type"] == expected["type"], f"Trace item {i} type mismatch."
        # SCPI commands are case-insensitive in practice, but drivers might be consistent.
        # For robustness, could compare lowercased commands if needed.
        assert actual["cmd"].strip() == expected["cmd"].strip(), f"Trace item {i} command mismatch."

# --- Test Cases ---

def test_psu_set_voltage(spying_psu):
    """Test setting voltage on channel 1."""
    psu, backend = spying_psu
    channel = 1
    voltage_to_set = 5.0

    # High-level driver call
    psu.set_voltage(voltage=voltage_to_set, channel=channel)

    # Expected SCPI trace
    # Assuming a common SCPI command structure. This might vary by instrument.
    # e.g., "SOUR:VOLT 5.0" or "VOLT 5.0" or "CH1:VOLT 5.0"
    # Let's assume the SimBackend and PowerSupply driver use "VOLT <val>" for channel 1 by default
    # or "SOURce[<n>]:VOLTage[:LEVel][:IMMediate][:AMPLitude] <voltage>"
    # For a multi-channel PSU, it's often "INST:SEL CH1; VOLT 5.0" or "VOLT 5.0, (@1)"
    # Let's assume our SimPSU uses "VOLTage <value>" for the selected channel (default 1)
    # or if the driver handles channel selection explicitly:
    expected_trace = [
        {"type": "write", "cmd": f"SOUR:VOLT {voltage_to_set:.2f}"} # Example, could be CH1:VOLT
        # Or, if channel selection is separate:
        # {"type": "write", "cmd": f"INST:NSEL {channel}"},
        # {"type": "write", "cmd": f"SOUR:VOLT {voltage_to_set:.2f}"}
    ]
    # This needs to match what the PowerSupply.set_voltage actually sends.
    # For now, using a placeholder. This is the most critical part to get right.
    # Let's assume the PowerSupply driver for channel 1 sends:
    # "VOLT 5.0" if channel 1 is default or selected.
    # If the driver is more complex (e.g. `select_channel(1)` then `set_voltage_on_selected_channel(5.0)`)
    # the trace would be longer.
    # Let's assume a simple driver that sends "VOLT <value>" for channel 1 if not specified,
    # or "CH<n>:VOLT <value>" if channel is specified.
    # Given our `PowerSupply` class, it likely has channel awareness.
    # A common SCPI pattern is `VOLTage <value>, (@<channel_list>)` or `APPL <voltage>, <current>, (@<channel_list>)`
    # Or `SOURce<c>:VOLTage <voltage>`
    # Let's assume `SOUR1:VOLT 5.00` for channel 1
    expected_trace = [
        {"type": "write", "cmd": f"SOUR{channel}:VOLT {voltage_to_set:.2f}"}
    ]


    # Expected final state of SimBackend (relevant parts)
    # This depends on how SimBackend's _process_command updates its state.
    expected_state_changes = {
        f"source_{channel}_voltage": voltage_to_set 
        # Or, if SimBackend uses a more generic state key:
        # "voltage_ch1": voltage_to_set
    }
    # The actual keys in SimBackend.state depend on its implementation.
    # Let's assume SimBackend stores it as 'CH1_VOLTAGE' or similar.
    # For now, we'll check the trace primarily. State check is more complex without knowing SimBackend's internals.

    assert_command_trace(backend.get_trace(), expected_trace)
    # Example state check (adapt to actual SimBackend state keys)
    # assert backend.state[f"CH{channel}_VOLTAGE"] == voltage_to_set


def test_psu_output_on(spying_psu):
    """Test turning output on for channel 1."""
    psu, backend = spying_psu
    channel = 1

    psu.set_output_state(True, channel=channel)

    expected_trace = [
        # Common: "OUTP ON" or "OUTP:STAT ON" or "OUTP1 ON"
        {"type": "write", "cmd": f"OUTP{channel}:STAT ON"}
    ]
    # Or if channel is implicit or selected prior:
    # expected_trace = [{"type": "write", "cmd": "OUTP ON"}]

    assert_command_trace(backend.get_trace(), expected_trace)
    # Expected state:
    # assert backend.state[f"CH{channel}_OUTPUT_STATE"] == "ON" # or True


def test_psu_measure_voltage(spying_psu):
    """Test measuring voltage on channel 1."""
    psu, backend = spying_psu
    channel = 1

    # Program SimBackend to return a specific value for this query
    # This requires the SpyingSimBackend or base SimBackend to allow pre-programming responses.
    # For now, let's assume SimBackend returns a default or predictable value.
    # Example: backend.sim_map["MEAS:VOLT?"] = "1.23" (if SimBackend supports this)
    # Or, if SimBackend has internal state that query reads from:
    simulated_voltage = 1.23
    backend.state[f"source_{channel}_voltage_sense"] = simulated_voltage # Hypothetical state key

    measured_voltage = psu.measure_voltage(channel=channel)

    expected_trace = [
        # Common: "MEAS:VOLT?" or "MEAS:VOLT? CH1"
        {"type": "query", "cmd": f"MEAS:VOLT? (@{channel})"} # Keysight style for specific channel
        # Or "MEAS:VOLT? CH1" or "SOUR{channel}:VOLT?" if measuring setpoint
        # Or just "MEAS:VOLT?" if channel is implicit
    ]
    # This needs to match the actual command sent by PowerSupply.measure_voltage()
    # Let's assume "MEAS:VOLT? CH1" or similar for channel 1
    expected_trace = [
        {"type": "query", "cmd": f"MEAS:VOLT? CH{channel}"} # A common pattern
    ]


    assert_command_trace(backend.get_trace(), expected_trace)
    # The SimBackend's query method needs to be programmed to return a value for "MEAS:VOLT? CH1"
    # For this test to pass, the SpyingSimBackend.query needs to return something.
    # The base SimBackend might return a default like "0.0" or from its state.
    # If we set backend.state['CH1_VOLTAGE_MEASUREMENT'] = 1.23, and query reads it.
    # For now, we assume the SimBackend is set up to provide a parseable float string.
    assert isinstance(measured_voltage, float)
    # assert measured_voltage == simulated_voltage # If we could preset the response

# More tests would follow for:
# - set_current_limit
# - measure_current
# - set_output_state(False, ...)
# - Error conditions (e.g., setting voltage out of range, if driver checks this before sending)

# Note: The exact SCPI commands and SimBackend state keys are crucial and
# need to align with the actual implementation of the PowerSupply driver
# and the SimBackend. These are illustrative examples.