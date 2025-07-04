# tests/instruments/async/test_multimeter.py
"""
Real Instrument Sanity Test for Keysight EDU34450A Multimeter (Async)

This script exercises key functionality of the Multimeter instrument class using the new async API.
"""
import asyncio
from pytestlab.instruments import AutoInstrument
from pytestlab.config.multimeter_config import DMMFunction
from uncertainties.core import UFloat

async def main():
    """Main async function to run the test."""
    print("--- Initializing Multimeter ---")
    # Create an instrument instance from a profile configuration.
    # This assumes the profile 'keysight/EDU34450A.yaml' exists and is configured.
    try:
        mm = await AutoInstrument.from_config("keysight/EDU34450A")
    except Exception as e:
        print(f"Failed to initialize instrument: {e}")
        return

    # --- Instrument Identification ---
    print("\n--- [1] Instrument Identification ---")
    idn = await mm.id()
    print(f"Instrument ID: {idn}")
    assert "KEYSIGHT" in idn.upper()
    assert "EDU34450A" in idn.upper()
    print("IDN Check: PASS")

    # --- Configure and Measure DC Voltage ---
    print("\n--- [2] DC Voltage Measurement (Autorange) ---")
    measurement = await mm.measure(DMMFunction.VOLTAGE_DC)
    print(f"Measured DC Voltage: {measurement.values} {measurement.units}")
    assert isinstance(measurement.values, UFloat)
    assert measurement.units == "V"
    print("DC Voltage Measurement: PASS")

    # --- Configure and Measure AC Voltage with fixed range ---
    print("\n--- [3] AC Voltage Measurement (1V Range) ---")
    measurement = await mm.measure(DMMFunction.VOLTAGE_AC, range_val="1")
    print(f"Measured AC Voltage: {measurement.values} {measurement.units}")
    assert isinstance(measurement.values, UFloat)
    assert measurement.units == "V"
    assert abs(measurement.values.n) <= 1.0
    print("AC Voltage Measurement: PASS")

    # --- Configure and Measure Resistance ---
    print("\n--- [4] 4-Wire Resistance Measurement ---")
    measurement = await mm.measure(DMMFunction.FRESISTANCE)
    print(f"Measured Resistance: {measurement.values} {measurement.units}")
    assert isinstance(measurement.values, UFloat)
    assert measurement.units == "Ω"
    print("Resistance Measurement: PASS")
    
    # --- Retrieve and Display Structured Configuration ---
    print("\n--- [5] Retrieving Structured Configuration ---")
    # Set a known state first
    await mm.configure_measurement(DMMFunction.CURRENT_DC, range_val="0.1", resolution="MAX")
    config = await mm.get_config()
    print(f"Current Configuration:\n{config}")
    assert config.measurement_mode == "Current"
    assert config.range_value == 0.1
    assert config.units == "A"
    print("Get Config: PASS")

    # --- Check for System Errors ---
    print("\n--- [6] Checking for System Errors ---")
    errors = await mm.get_all_errors()
    print(f"System Error Query Response: {errors}")
    assert isinstance(errors, list) and len(errors) == 0
    print("Error Check: PASS")

    # --- Run Self-Test ---
    print("\n--- [7] Running Self-Test ---")
    result = await mm.run_self_test()
    print(f"Self-test result: '{result}'")
    assert result == "Passed"
    print("Self-Test: PASS")

    print("\n--- Multimeter async test completed successfully! ---")

if __name__ == "__main__":
    asyncio.run(main())
