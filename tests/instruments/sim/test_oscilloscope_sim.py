# tests/instruments/sim/test_oscilloscope_sim.py
import pytest
import polars as pl
from pytestlab.instruments import Oscilloscope
from pytestlab.common.enums import TriggerSlope
from pytestlab.errors import InstrumentCommunicationError

# Test file for oscilloscope simulation

def test_idn_and_reset(sim_scope: Oscilloscope):
    """Verify *IDN? and *RST commands."""
    # 1. Test IDN
    idn = sim_scope.id()
    assert idn == "Simulated,Keysight,DSOX1204G,SIM1.0"

    # 2. Change a value from its default
    sim_scope.set_time_axis(scale=5.0, position=1.0)
    current_scale = sim_scope.get_time_axis()
    assert current_scale[0] == 5.0

    # 3. Test Reset
    sim_scope.reset()

    # 4. Verify the value has returned to its initial state from the YAML
    reset_scale = sim_scope.get_time_axis()
    assert reset_scale[0] == 1.0e-3 # Default from initial_state in YAML

def test_timebase_control(sim_scope: Oscilloscope):
    """Verify setting and getting timebase scale and position."""
    sim_scope.set_time_axis(scale=2.5e-3, position=-1e-3)

    scale, position = sim_scope.get_time_axis()

    assert scale == 2.5e-3
    assert position == -1e-3

def test_channel_facade(sim_scope: Oscilloscope):
    """Verify the chained channel facade methods."""
    # Use the facade to configure channel 2
    sim_scope.channel(2).setup(scale=0.5, offset=-0.1).enable()

    # Verify each setting was applied correctly
    ch2_scale, ch2_offset = sim_scope.get_channel_axis(2)
    assert ch2_scale == 0.5
    assert ch2_offset == -0.1

    ch2_display_state = sim_scope._query(":CHANnel2:DISPlay?")
    assert ch2_display_state == "1"

def test_trigger_facade(sim_scope: Oscilloscope):
    """Verify the trigger facade methods."""
    sim_scope.trigger.setup_edge(source="CH4", level=1.23, slope=TriggerSlope.NEGATIVE)

    # Verify the state change by querying the simulator
    source = sim_scope._query(":TRIGger:SOURce?")
    level = sim_scope._query(":TRIGger:LEVel?")
    slope = sim_scope._query(":TRIGger:SLOPe?")

    assert source == "CHANnel4"
    assert float(level) == 1.23
    assert slope == "NEG"

def test_waveform_acquisition(sim_scope: Oscilloscope):
    """Verify that read_channels returns a correctly structured result."""
    sim_scope.get_sampling_rate = lambda: 1.0e9
    result = sim_scope.read_channels(1, 3) # Read channels 1 and 3

    assert isinstance(result.values, pl.DataFrame)
    assert result.values.shape[0] == 1024 # Points from YAML
    assert result.values.shape[1] == 3 # Time + CH1 + CH3
    assert result.values.columns == ["Time (s)", "Channel 1 (V)", "Channel 3 (V)"]

    # Check dtypes
    assert result.values["Time (s)"].dtype == pl.Float64
    assert result.values["Channel 1 (V)"].dtype == pl.Float64
    assert result.values["Channel 3 (V)"].dtype == pl.Float64

def test_error_generation(sim_scope: Oscilloscope):
    """Verify that the simulator generates an error based on the YAML rule."""
    sim_scope.clear_status() # Ensure error queue is empty

    # This action should trigger the error rule in the YAML profile
    with pytest.raises(InstrumentCommunicationError) as exc_info:
        sim_scope.channel(1).setup(scale=0.0005)
    assert "Data out of range" in str(exc_info.value)
