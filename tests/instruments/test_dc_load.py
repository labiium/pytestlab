"""
pytestlab/tests/instruments/async/test_dc_load.py

Comprehensive asynchronous test suite for a real DC Electronic Load using the
PyTestLab async API.

This test covers all major features of the DCActiveLoad driver:
- Connection and identification
- Mode and load setting (CC, CV, CP, CR)
- Input control (enable, short)
- Parameter control (slew rate, range)
- Uncertainty-aware measurements (current, voltage, power)
- Transient system control
- Battery test system control
- Data acquisition (scope, datalogger)
- Error handling

**NOTE:** This test requires a real Keysight EL30000 series DC Load connected
and accessible via VISA. Set the DC_LOAD_CONFIG_KEY below.

Run with:
    pytest -v tests/instruments/async/test_dc_load.py

Requires:
    pytest
    pytest-asyncio
    numpy
    uncertainties
    pytestlab (with async API)
"""

import pytest
import numpy as np
from uncertainties import UFloat

from pytestlab.instruments import AutoInstrument, DCActiveLoad
from pytestlab.errors import InstrumentParameterError

# ------------------- CONFIGURE THIS FOR YOUR LAB -------------------
DC_LOAD_CONFIG_KEY = "keysight/EL33133A"  # <-- Set your profile key or path here
# --------------------------------------------------------------------

def check_hardware_available():
    """Check if DC load hardware is available for testing."""
    try:
        dcl = AutoInstrument.from_config(DC_LOAD_CONFIG_KEY)
        dcl.connect_backend()
        # Try to get IDN to verify connection
        idn = dcl.id()
        dcl.close()
        return True, None
    except Exception as e:
        return False, str(e)


@pytest.mark.requires_real_hw
def test_dc_load_full_real():
    """
    Full functional test for a real DC Electronic Load using PyTestLab async API.
    """
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"DC Load hardware not available: {error_msg}")
    # Instantiate the DC Load (real hardware)
    dcl = AutoInstrument.from_config(DC_LOAD_CONFIG_KEY)
    dcl.connect_backend()

    # --- IDN ---
    idn = dcl.id()
    print(f"IDN: {idn}")
    assert isinstance(idn, str)
    assert "Keysight".upper() in idn.upper()

    # --- Mode and Load Setting ---
    test_modes = {"CC": 2.5, "CV": 5.0, "CR": 10.0, "CP": 20.0}
    for mode, value in test_modes.items():
        dcl.set_mode(mode)
        assert dcl.current_mode == mode
        dcl.set_load(value)
        print(f"Set mode to {mode} with load {value}")

    # --- Input Control ---
    dcl.enable_input(True)
    is_enabled = dcl.is_input_enabled()
    assert is_enabled is True
    dcl.enable_input(False)
    is_enabled = dcl.is_input_enabled()
    assert is_enabled is False
    print("Input control tested.")

    # --- Short Circuit ---
    dcl.short_input(True)
    # Note: Querying short state is not implemented in the driver, just testing command
    dcl.short_input(False)
    print("Input short tested.")

    # --- Parameter Control (in CC mode) ---
    dcl.set_mode("CC")
    dcl.set_slew_rate(0.5)
    dcl.set_range(5.0)
    print("Slew rate and range tested.")

    # --- Measurements with Uncertainty ---
    dcl.enable_input(True)
    dcl.set_load(1.0)

    current_meas = dcl.measure_current()
    print(f"Measured Current: {current_meas.values}")
    assert isinstance(current_meas.values, UFloat)
    assert current_meas.units == "A"

    voltage_meas = dcl.measure_voltage()
    print(f"Measured Voltage: {voltage_meas.values}")
    assert isinstance(voltage_meas.values, UFloat)
    assert voltage_meas.units == "V"

    power_meas = dcl.measure_power()
    print(f"Measured Power: {power_meas.values}")
    assert isinstance(power_meas.values, UFloat)
    assert power_meas.units == "W"

    dcl.enable_input(False)
    print("Uncertainty-aware measurements tested.")

    # --- Transient System ---
    dcl.configure_transient_mode('PULSe')
    dcl.set_transient_level(0.5)
    dcl.start_transient()
    dcl.stop_transient()
    print("Transient system tested.")

    # --- Battery Test ---
    dcl.enable_battery_test(True)
    dcl.set_battery_cutoff_voltage(10.0)
    dcl.set_battery_cutoff_capacity(1.5)
    dcl.set_battery_cutoff_timer(3600)
    # cap = dcl.get_battery_test_measurement("capacity")
    # assert isinstance(cap, float)
    dcl.enable_battery_test(False)
    print("Battery test system tested.")

    # --- Data Acquisition (if supported by hardware) ---
    # Note: These may require specific setup to yield data.
    # try:
    #     scope_data = dcl.fetch_scope_data("current")
    #     assert isinstance(scope_data, np.ndarray)
    #     print("Scope data fetched.")
    # except Exception as e:
    #     print(f"Could not fetch scope data (may be normal): {e}")
    #
    # try:
    #     dlog_data = dcl.fetch_datalogger_data(10)
    #     assert isinstance(dlog_data, list)
    #     print("Datalogger data fetched.")
    # except Exception as e:
    #     print(f"Could not fetch datalogger data (may be normal): {e}")

    # --- Error Handling ---
    errors = dcl.get_all_errors()
    assert all(code == 0 for code, _ in errors)
    print("Error queue checked and clear.")

    # --- Health Check ---
    health = dcl.health_check()
    print(f"Health: {health.status}")
    assert health.status in ("OK", "WARNING", "ERROR", "UNKNOWN")

    # --- Close ---
    dcl.close()
    print("DC Load closed.")

@pytest.mark.requires_real_hw
def test_dc_load_advanced_features_real():
   """
   Tests the advanced features of the DC Electronic Load driver.
   """
   is_available, error_msg = check_hardware_available()
   if not is_available:
       pytest.skip(f"DC Load hardware not available: {error_msg}")
   dcl: DCActiveLoad = AutoInstrument.from_config(DC_LOAD_CONFIG_KEY)
   dcl.connect_backend()

   # --- Advanced Transient Control ---
   print("\n--- Testing Advanced Transient Control ---")
   dcl.set_mode("CC")
   dcl.configure_transient_mode('CONTinuous')
   dcl.set_transient_frequency(1000) # 1 kHz
   dcl.set_transient_duty_cycle(75.0) # 75%
   # Verification would require an oscilloscope, but we check that commands run
   print("Advanced transient control commands executed.")

   # --- LIST Subsystem ---
   print("\n--- Testing LIST Subsystem ---")
   dcl.set_mode("CC")
   # Create a 3-step current ramp
   (dcl.list(1)
          .set_levels("current", [0.1, 0.2, 0.3])
          .set_dwells([0.1, 0.1, 0.1])
          .configure(count=2))
   print("LIST subsystem configured.")
   # To run the list:
   dcl.configure_transient_mode('LIST')
   # dcl.start_transient() # This would start the actual list execution
   # time.sleep(1)
   # dcl.stop_transient()

   # --- Datalogger and Scope Configuration ---
   print("\n--- Testing Data Acquisition Configuration ---")
   # Configure datalogger
   dcl.configure_datalogger(duration_s=10, period_s=0.1, log_voltage=True, log_current=True)
   print("Datalogger configured.")
   # dcl.start_datalogger()
   # time.sleep(2)
   # dcl.stop_datalogger()

   # Configure scope
   dcl.configure_scope(points=512, interval_s=1e-4)
   print("Scope configured.")

   # --- Triggering System ---
   print("\n--- Testing Triggering System ---")
   # Configure acquisition to trigger when voltage crosses 1V (rising)
   dcl.configure_acquisition_trigger(source=DCActiveLoad.TriggerSource.VOLTAGE, level=1.0, slope_positive=True)
   print("Acquisition trigger configured.")

   # Configure transient to trigger on an external signal
   dcl.configure_transient_trigger(source=DCActiveLoad.TriggerSource.EXTERNAL)
   print("Transient trigger configured.")

   # --- Digital I/O ---
   print("\n--- Testing Digital I/O ---")
   # Configure Pin 1 as a Trigger Output with positive polarity
   dcl.configure_digital_pin(1, DCActiveLoad.DigitalPinFunction.TRIGGER_OUTPUT, DCActiveLoad.DigitalPinPolarity.POSITIVE)
   print("Digital Pin 1 configured as trigger output.")

   # --- Final Cleanup ---
   dcl.reset()
   dcl.close()
   print("Advanced features test completed.")


@pytest.mark.requires_real_hw
def test_dc_load_error_cases_real():
    """
    Test error handling for invalid parameters on a real DC Load.
    """
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"DC Load hardware not available: {error_msg}")
    dcl = AutoInstrument.from_config(DC_LOAD_CONFIG_KEY)
    dcl.connect_backend()

    # Reset mode to ensure predictable state
    dcl.current_mode = None

    # Setting load before mode
    with pytest.raises(InstrumentParameterError, match="Load mode has not been set"):
        dcl.set_load(1.0)

    # Setting slew rate before mode
    with pytest.raises(InstrumentParameterError, match="Mode must be set before setting slew rate"):
        dcl.set_slew_rate(1.0)

    # Setting range before mode
    with pytest.raises(InstrumentParameterError, match="Mode must be set before setting range"):
        dcl.set_range(1.0)

    # Invalid mode
    with pytest.raises(InstrumentParameterError, match="Unsupported mode 'XX'"):
        dcl.set_mode("XX")

    print("Error cases tested successfully.")

    dcl.close()
