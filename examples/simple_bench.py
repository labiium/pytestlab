#!/usr/bin/env python3
"""
PyTestLab Simple Bench Example

This example demonstrates:
  - Loading a bench from a YAML configuration file
  - Accessing instruments by name
  - Using the bench context manager for automatic cleanup
  - Running basic operations on multiple instruments

The bench uses simulation mode - no hardware required.
"""

from pathlib import Path
from pytestlab import Bench


def main():
    """Run the simple bench example."""
    print("=" * 60)
    print("PyTestLab Simple Bench Example")
    print("=" * 60)

    # Find the bench configuration file
    bench_path = Path(__file__).parent / "simple_bench.yaml"

    print(f"\nLoading bench from: {bench_path.name}")

    # Load the bench using a context manager
    # This ensures proper cleanup when done
    with Bench.open(bench_path) as bench:
        print(f"✓ Bench loaded: {bench.name}")
        print(f"  Simulation mode: {bench.simulate}")
        print(f"  Number of instruments: {len(bench.instruments)}")

        # Access instruments by their alias
        print("\n--- Accessing Instruments ---")

        # Access the power supply
        psu = bench.psu
        print(f"\nPower Supply (psu):")
        print(f"  Model: {psu.config.model}")
        print(f"  ID: {psu.id()}")

        # Access the multimeter
        dmm = bench.dmm
        print(f"\nMultimeter (dmm):")
        print(f"  Model: {dmm.config.model}")
        print(f"  ID: {dmm.id()}")

        # Perform operations
        print("\n--- Running Operations ---")

        # Set up power supply
        print("\n1. Configuring power supply...")
        psu.set_voltage(1, 3.3)
        psu.set_current(1, 0.5)
        print("   Voltage: 3.3V, Current limit: 0.5A")

        # Enable output
        psu.output(1, True)
        print("   Output: ON")

        # Note: The multimeter can perform various measurements using dmm.measure()
        # In simulation mode, this demonstrates the API without real hardware
        print("\n2. Multimeter ready for measurements")
        print("   Available measurement functions:")
        print("   - DMMFunction.VOLTAGE_DC - DC voltage")
        print("   - DMMFunction.VOLTAGE_AC - AC voltage")
        print("   - DMMFunction.CURRENT_DC - DC current")
        print("   - DMMFunction.RESISTANCE - 2-wire resistance")

        # Turn off output
        psu.output(1, False)
        print("\n3. Power supply output turned off")

    # The context manager automatically closes all instruments
    print("\n" + "=" * 60)
    print("Bench example completed successfully!")
    print("All instruments cleaned up automatically.")
    print("=" * 60)


if __name__ == "__main__":
    main()
