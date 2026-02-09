#!/usr/bin/env python3
"""
PyTestLab Hello World - The simplest possible example.

This example demonstrates:
  - Connecting to a simulated instrument
  - Querying instrument identification
  - Setting voltage and enabling output
  - Proper cleanup

No external hardware required - runs entirely in simulation mode.
"""

from pytestlab import AutoInstrument


def main():
    """Run the hello world example."""
    print("=" * 60)
    print("PyTestLab Hello World Example")
    print("=" * 60)

    # Create a simulated power supply
    # The 'simulate=True' flag ensures no real hardware is needed
    print("\n1. Creating simulated power supply...")
    psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)

    # Connect to the instrument's backend
    print("2. Connecting to backend...")
    psu.connect_backend()

    # Query the instrument identification
    print("3. Querying instrument ID...")
    instrument_id = psu.id()
    print(f"   Instrument: {instrument_id}")

    # Set a simple voltage
    print("4. Setting voltage to 3.3V on channel 1...")
    psu.set_voltage(1, 3.3)
    print("   Done!")

    # Enable the output
    print("5. Enabling output...")
    psu.output(1, True)
    print("   Output enabled!")

    # Disable output and cleanup
    print("6. Cleaning up...")
    psu.output(1, False)
    psu.close()
    print("   Done!")

    print("\n" + "=" * 60)
    print("Hello World completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
