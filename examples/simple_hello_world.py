#!/usr/bin/env python3
"""
PyTestLab Hello World - The simplest possible example.

This example demonstrates:
  - Creating a simulated instrument
  - Automatic backend opening on first use
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

    # Query the instrument identification
    print("2. Querying instrument ID (opens backend automatically)...")
    instrument_id = psu.id()
    print(f"   Instrument: {instrument_id}")

    # Set a simple voltage
    print("3. Setting voltage to 3.3V on channel 1...")
    psu.set_voltage(1, 3.3)
    print("   Done!")

    # Enable the output
    print("4. Enabling output...")
    psu.output(1, True)
    print("   Output enabled!")

    # Disable output and cleanup
    print("5. Cleaning up...")
    psu.output(1, False)
    psu.close()
    print("   Done!")

    print("\n" + "=" * 60)
    print("Hello World completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
