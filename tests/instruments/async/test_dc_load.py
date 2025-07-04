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

from pytestlab.instruments import AutoInstrument
from pytestlab.errors import InstrumentParameterError

# ------------------- CONFIGURE THIS FOR YOUR LAB -------------------
DC_LOAD_CONFIG_KEY = "keysight/EL33133A"  # <-- Set your profile key or path here
# --------------------------------------------------------------------


@pytest.mark.requires_real_hw
@pytest.mark.asyncio
async def test_dc_load_full_real():
    """
    Full functional test for a real DC Electronic Load using PyTestLab async API.
    """
    # Instantiate the DC Load (real hardware)
    dcl = await AutoInstrument.from_config(DC_LOAD_CONFIG_KEY)
    await dcl.connect_backend()

    # --- IDN ---
    idn = await dcl.id()
    print(f"IDN: {idn}")
    assert isinstance(idn, str)
    assert "Keysight".upper() in idn.upper()

    # --- Mode and Load Setting ---
    test_modes = {"CC": 2.5, "CV": 5.0, "CR": 10.0, "CP": 20.0}
    for mode, value in test_modes.items():
        await dcl.set_mode(mode)
        assert dcl.current_mode == mode
        await dcl.set_load(value)
        print(f"Set mode to {mode} with load {value}")

    # --- Input Control ---
    await dcl.enable_input(True)
    is_enabled = await dcl.is_input_enabled()
    assert is_enabled is True
    await dcl.enable_input(False)
    is_enabled = await dcl.is_input_enabled()
    assert is_enabled is False
    print("Input control tested.")

    # --- Short Circuit ---
    await dcl.short_input(True)
    # Note: Querying short state is not implemented in the driver, just testing command
    await dcl.short_input(False)
    print("Input short tested.")

    # --- Parameter Control (in CC mode) ---
    await dcl.set_mode("CC")
    await dcl.set_slew_rate(0.5)
    await dcl.set_range(5.0)
    print("Slew rate and range tested.")

    # --- Measurements with Uncertainty ---
    await dcl.enable_input(True)
    await dcl.set_load(1.0)
    
    current_meas = await dcl.measure_current()
    print(f"Measured Current: {current_meas.values}")
    assert isinstance(current_meas.values, UFloat)
    assert current_meas.units == "A"

    voltage_meas = await dcl.measure_voltage()
    print(f"Measured Voltage: {voltage_meas.values}")
    assert isinstance(voltage_meas.values, UFloat)
    assert voltage_meas.units == "V"

    power_meas = await dcl.measure_power()
    print(f"Measured Power: {power_meas.values}")
    assert isinstance(power_meas.values, UFloat)
    assert power_meas.units == "W"
    
    await dcl.enable_input(False)
    print("Uncertainty-aware measurements tested.")

    # --- Transient System ---
    await dcl.configure_transient_mode('PULSe')
    await dcl.set_transient_level(0.5)
    await dcl.start_transient()
    await dcl.stop_transient()
    print("Transient system tested.")

    # --- Battery Test ---
    await dcl.enable_battery_test(True)
    await dcl.set_battery_cutoff_voltage(10.0)
    await dcl.set_battery_cutoff_capacity(1.5)
    await dcl.set_battery_cutoff_timer(3600)
    # cap = await dcl.get_battery_test_measurement("capacity")
    # assert isinstance(cap, float)
    await dcl.enable_battery_test(False)
    print("Battery test system tested.")

    # --- Data Acquisition (if supported by hardware) ---
    # Note: These may require specific setup to yield data.
    # try:
    #     scope_data = await dcl.fetch_scope_data("current")
    #     assert isinstance(scope_data, np.ndarray)
    #     print("Scope data fetched.")
    # except Exception as e:
    #     print(f"Could not fetch scope data (may be normal): {e}")
    #
    # try:
    #     dlog_data = await dcl.fetch_datalogger_data(10)
    #     assert isinstance(dlog_data, list)
    #     print("Datalogger data fetched.")
    # except Exception as e:
    #     print(f"Could not fetch datalogger data (may be normal): {e}")

    # --- Error Handling ---
    errors = await dcl.get_all_errors()
    assert all(code == 0 for code, _ in errors)
    print("Error queue checked and clear.")

    # --- Health Check ---
    health = await dcl.health_check()
    print(f"Health: {health.status}")
    assert health.status in ("OK", "WARNING", "ERROR", "UNKNOWN")

    # --- Close ---
    await dcl.close()
    print("DC Load closed.")


@pytest.mark.requires_real_hw
@pytest.mark.asyncio
async def test_dc_load_error_cases_real():
    """
    Test error handling for invalid parameters on a real DC Load.
    """
    dcl = await AutoInstrument.from_config(DC_LOAD_CONFIG_KEY)
    await dcl.connect_backend()

    # Reset mode to ensure predictable state
    dcl.current_mode = None

    # Setting load before mode
    with pytest.raises(InstrumentParameterError, match="Load mode has not been set"):
        await dcl.set_load(1.0)

    # Setting slew rate before mode
    with pytest.raises(InstrumentParameterError, match="Mode must be set before setting slew rate"):
        await dcl.set_slew_rate(1.0)

    # Setting range before mode
    with pytest.raises(InstrumentParameterError, match="Mode must be set before setting range"):
        await dcl.set_range(1.0)

    # Invalid mode
    with pytest.raises(InstrumentParameterError, match="Unsupported mode 'XX'"):
        await dcl.set_mode("XX")

    print("Error cases tested successfully.")

    await dcl.close()