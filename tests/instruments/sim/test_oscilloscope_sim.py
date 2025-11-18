# tests/instruments/sim/test_oscilloscope_sim.py
import math

import polars as pl
import pytest
from PIL import Image

from pytestlab.common.enums import AcquisitionType
from pytestlab.common.enums import TriggerSlope
from pytestlab.common.enums import WaveformType
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments import Oscilloscope


def _sim_state(scope: Oscilloscope):
    backend = getattr(scope, "_backend", None)
    assert backend is not None, "Sim scope should expose backend state"
    return backend._state


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
    assert reset_scale[0] == 1.0e-3  # Default from initial_state in YAML


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

    cmd = sim_scope.scpi_engine.build("channel_display", channel=2)[0]
    ch2_display_state = sim_scope._query(cmd)
    assert ch2_display_state == "1"


def test_trigger_facade(sim_scope: Oscilloscope):
    """Verify the trigger facade methods."""
    sim_scope.trigger.setup_edge(source="CH4", level=1.23, slope=TriggerSlope.NEGATIVE)

    # Verify the state change by querying the simulator
    source = sim_scope._query(sim_scope.scpi_engine.build("trigger_source")[0])
    level = sim_scope._query(sim_scope.scpi_engine.build("trigger_level")[0])
    slope = sim_scope._query(sim_scope.scpi_engine.build("trigger_slope")[0])

    assert source == "CHANnel4"
    assert float(level) == 1.23
    assert slope == "NEG"


def test_waveform_acquisition(sim_scope: Oscilloscope):
    """Verify that read_channels returns a correctly structured result."""
    # Test without mocking - use the actual method
    result = sim_scope.read_channels(1, 3)  # Read channels 1 and 3

    assert isinstance(result.values, pl.DataFrame)
    assert result.values.shape[0] == 1024  # Points from YAML
    assert result.values.shape[1] == 3  # Time + CH1 + CH3
    assert result.values.columns == ["Time (s)", "Channel 1 (V)", "Channel 3 (V)"]

    # Check dtypes
    assert result.values["Time (s)"].dtype == pl.Float64
    assert result.values["Channel 1 (V)"].dtype == pl.Float64
    assert result.values["Channel 3 (V)"].dtype == pl.Float64


def test_error_generation(sim_scope: Oscilloscope):
    """Verify that the simulator generates an error based on the YAML rule."""
    sim_scope.clear_status()  # Ensure error queue is empty

    # This action should trigger the error rule in the YAML profile
    with pytest.raises(InstrumentCommunicationError) as exc_info:
        sim_scope.channel(1).setup(scale=0.0005)
    assert "Data out of range" in str(exc_info.value)


def test_panel_controls_and_autoscale(sim_scope: Oscilloscope):
    """Validate panel lock toggling and autoscale command."""
    sim_scope.lock_panel(True)
    state = _sim_state(sim_scope)
    assert state["panel"]["locked"] == "1"

    sim_scope.lock_panel(False)
    assert state["panel"]["locked"] == "0"

    # Should execute without raising
    sim_scope.auto_scale()


def test_measurement_functions(sim_scope: Oscilloscope):
    """Ensure measurement helpers return populated MeasurementResult objects."""
    vpp_result = sim_scope.measure_voltage_peak_to_peak(1)
    value = getattr(vpp_result.values, "nominal_value", vpp_result.values)
    assert value == pytest.approx(0.5)
    assert vpp_result.units == "V"

    vrms_result = sim_scope.measure_rms_voltage(1)
    value = getattr(vrms_result.values, "nominal_value", vrms_result.values)
    assert value == pytest.approx(0.353553, rel=1e-6)
    assert vrms_result.units == "V"


def test_fft_configuration_and_data(sim_scope: Oscilloscope):
    """Configure FFT, verify simulator state, and ensure data can be acquired."""
    sim_scope.configure_fft(
        source_channel=1,
        span=2.5e6,
        scale=2.0,
        offset=-10.0,
        window_type="HANNing",
        units="DECibel",
    )
    state = _sim_state(sim_scope)
    fft_state = state["fft"]
    assert fft_state["source"] == "CHANnel1"
    assert fft_state["window"] == "HANNing"
    assert fft_state["units"] == "DECibel"
    assert fft_state["span"] == pytest.approx(2.5e6)
    assert fft_state["scale"] == pytest.approx(2.0)
    assert fft_state["offset"] == pytest.approx(-10.0)
    assert fft_state["display"] == "1"

    fft_result = sim_scope.read_fft_data(1)
    assert isinstance(fft_result.values, pl.DataFrame)
    assert not fft_result.values.is_empty()
    assert "Frequency (Hz)" in fft_result.values.columns
    assert "Magnitude (Linear)" in fft_result.values.columns


def test_wave_generator_controls(sim_scope: Oscilloscope):
    """Exercise waveform-generator helper APIs."""
    sim_scope.wave_gen(True)
    state = _sim_state(sim_scope)
    assert state["wgen"]["output"] == "1"

    sim_scope.set_wgen_sin(amp=2.0, offset=0.2, freq=1.5e3)
    assert state["wgen"]["func"] == WaveformType.SINE.value
    assert state["wgen"]["volt"] == pytest.approx(2.0)
    assert state["wgen"]["offset"] == pytest.approx(0.2)
    assert state["wgen"]["freq"] == pytest.approx(1.5e3)

    sim_scope.set_wgen_square(v0=-1.0, v1=1.0, freq=2.0e3, duty_cycle=120)
    assert state["wgen"]["func"] == WaveformType.SQUARE.value
    assert state["wgen"]["low"] == pytest.approx(-1.0)
    assert state["wgen"]["high"] == pytest.approx(1.0)
    assert state["wgen"]["freq"] == pytest.approx(2.0e3)
    assert state["wgen"]["square_duty"] == pytest.approx(99)

    sim_scope.set_wgen_ramp(v0=-0.5, v1=0.5, freq=3.0e3, symmetry=120)
    assert state["wgen"]["func"] == WaveformType.RAMP.value
    assert state["wgen"]["ramp_symmetry"] == pytest.approx(100)

    sim_scope.set_wgen_pulse(v0=0.0, v1=2.0, period=1e-3, pulse_width=2e-4)
    assert state["wgen"]["func"] == WaveformType.PULSE.value
    assert state["wgen"]["period"] == pytest.approx(1e-3)
    assert state["wgen"]["pulse_width"] == pytest.approx(2e-4)

    sim_scope.set_wgen_dc(offset=0.75)
    assert state["wgen"]["func"] == WaveformType.DC.value
    assert state["wgen"]["offset"] == pytest.approx(0.75)

    sim_scope.set_wgen_noise(v0=-0.1, v1=0.1, offset=0.05)
    assert state["wgen"]["func"] == WaveformType.NOISE.value
    assert state["wgen"]["low"] == pytest.approx(-0.1)
    assert state["wgen"]["high"] == pytest.approx(0.1)
    assert state["wgen"]["offset"] == pytest.approx(0.05)

    sim_scope.wave_gen(False)
    assert state["wgen"]["output"] == "0"


def test_display_channel_bulk(sim_scope: Oscilloscope):
    """Ensure list inputs toggle multiple channels."""
    channels = [1, 2, 3]
    sim_scope.display_channel(channels, state=False)
    for ch in channels:
        cmd = sim_scope.scpi_engine.build("channel_display", channel=ch)[0]
        assert sim_scope._query(cmd) == "0"

    sim_scope.display_channel(channels, state=True)
    for ch in channels:
        cmd = sim_scope.scpi_engine.build("channel_display", channel=ch)[0]
        assert sim_scope._query(cmd) == "1"


def test_time_axis_invalid_inputs(sim_scope: Oscilloscope):
    """set_time_axis should guard against non-finite or negative values."""
    with pytest.raises(InstrumentParameterError, match="finite"):
        sim_scope.set_time_axis(scale=math.inf, position=0.0)
    with pytest.raises(InstrumentParameterError, match="between"):
        sim_scope.set_time_axis(scale=-0.5, position=0.0)
    with pytest.raises(InstrumentParameterError, match="finite"):
        sim_scope.set_time_axis(scale=1e-3, position=math.nan)


def test_screenshot_returns_image(sim_scope: Oscilloscope):
    """The screenshot helper should decode PNG data into a Pillow image."""
    image = sim_scope.screenshot()
    assert isinstance(image, Image.Image)
    assert image.size == (1, 1)


def test_health_check_reports_features(sim_scope: Oscilloscope):
    """Health report should reflect simulated capabilities."""
    report = sim_scope.health_check()
    assert report.status in {"OK", "WARNING"}
    assert report.supported_features.get("fft") is True
    assert report.supported_features.get("function_generator") is True
    assert report.instrument_idn and report.instrument_idn.upper().startswith("SIMULATED")


def test_acquisition_facade_operations(sim_scope: Oscilloscope):
    """Verify acquisition facade drives simulated state correctly."""
    sim_scope.acquisition.set_acquisition_type(AcquisitionType.AVERAGE)
    state = _sim_state(sim_scope)
    assert state["acquisition"]["type"] == "AVERage"

    sim_scope.acquisition.set_acquisition_mode("SEGMENTED")
    assert state["acquisition"]["mode"] == "SEGMented"

    sim_scope.acquisition.set_acquisition_average_count(8)
    assert state["acquisition"]["count"] == 8

    sim_scope.acquisition.set_segmented_count(10)
    assert state["acquisition"]["segment_count"] == 10

    sim_scope.acquisition.set_segment_index(3)
    assert state["acquisition"]["segment_index"] == 3

    sim_scope.acquisition.analyze_all_segments()

    assert sim_scope.acquisition.get_acquisition_type() == AcquisitionType.AVERAGE.name
    assert sim_scope.acquisition.get_acquisition_mode() == "SEGMENTED"
    assert sim_scope.acquisition.get_acquisition_average_count() == 8
    assert sim_scope.acquisition.get_segmented_count() == 10
    assert sim_scope.acquisition.get_segment_index() == 3
