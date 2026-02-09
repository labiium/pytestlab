#!/usr/bin/env python3
"""
PyTestLab Simple Instrument Control

This example demonstrates basic instrument control patterns:
  - Power supply: set voltage, current limit, and control output
  - Using the chainable facade API for clean code
  - Multimeter: measurement concepts
  - Proper resource management with context managers

All instruments run in simulation mode - no hardware required.
"""

from pytestlab import AutoInstrument


def power_supply_example():
    """Demonstrate basic power supply control."""
    print("\n--- Power Supply Example ---")

    # Create a simulated power supply
    psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)

    try:
        # Connect to the instrument
        psu.connect_backend()
        print(f"Connected to: {psu.id()}")

        # Method 1: Direct API calls
        print("\nMethod 1: Direct API calls")
        psu.set_voltage(1, 5.0)
        psu.set_current(1, 0.5)
        psu.output(1, True)
        print("  Set channel 1 to 5V, 0.5A limit, output ON")

        # Method 2: Chainable facade API (cleaner!)
        print("\nMethod 2: Chainable facade API")
        psu.channel(2).set(voltage=3.3, current_limit=0.1).on()
        print("  Set channel 2 to 3.3V, 0.1A limit, output ON")

        # Turn off all outputs
        psu.channel(1).off()
        psu.channel(2).off()
        print("\nAll channels turned off")

    finally:
        # Always close the connection
        psu.close()
        print("Power supply connection closed")


def multimeter_example():
    """Demonstrate basic multimeter operations."""
    print("\n--- Multimeter Example ---")

    # Create a simulated multimeter
    dmm = AutoInstrument.from_config("keysight/EDU34450A", simulate=True)

    try:
        dmm.connect_backend()
        print(f"Connected to: {dmm.id()}")

        # Note: In simulation mode, measurements return simulated values
        print("\nMeasurement functions available:")
        print("  - measure() with DMMFunction.VOLTAGE_DC - DC voltage measurement")
        print("  - measure() with DMMFunction.VOLTAGE_AC - AC voltage measurement")
        print("  - measure() with DMMFunction.CURRENT_DC - DC current measurement")
        print("  - measure() with DMMFunction.RESISTANCE - 2-wire resistance")

        # The Multimeter class uses the measure() method with DMMFunction enum
        from pytestlab.config.multimeter_config import DMMFunction

        # Note: In simulation mode, this demonstrates the API
        # In real use, this would return actual measurements
        print(f"\nTo perform a measurement:")
        print(f"  result = dmm.measure(DMMFunction.VOLTAGE_DC)")
        print(f"  # Returns a MeasurementResult with value and units")

    finally:
        dmm.close()
        print("Multimeter connection closed")


def oscilloscope_example():
    """Demonstrate basic oscilloscope operations."""
    print("\n--- Oscilloscope Example ---")

    # Create a simulated oscilloscope
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)

    try:
        scope.connect_backend()
        print(f"Connected to: {scope.id()}")

        # Configure channel using direct API
        print("\nConfiguring channel 1...")
        scope.set_channel_axis(1, scale=0.5, offset=0.0)  # 500mV/div, no offset
        scope.display_channel(1, True)
        print("  Channel 1: 500mV/div, enabled")

        # Configure timebase using set_time_axis
        print("\nConfiguring timebase...")
        scope.set_time_axis(scale=0.001, position=0.0)  # 1ms per division
        print("  Timebase: 1ms/div")

        # Note: The oscilloscope has a trigger facade for advanced configuration
        print("\nTrigger configuration available via scope.trigger facade:")
        print("  scope.trigger.setup_edge(source='CH1', level=0.0)")

        print("\nOscilloscope configured successfully!")

    finally:
        scope.close()
        print("Oscilloscope connection closed")


def main():
    """Run all instrument examples."""
    print("=" * 60)
    print("PyTestLab Simple Instrument Control Examples")
    print("=" * 60)

    try:
        power_supply_example()
        multimeter_example()
        oscilloscope_example()

        print("\n" + "=" * 60)
        print("All examples completed successfully!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\nExamples interrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        raise


if __name__ == "__main__":
    main()
