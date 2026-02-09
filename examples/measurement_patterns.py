#!/usr/bin/env python3
"""
PyTestLab Measurement Patterns Examples

This module demonstrates common measurement patterns using PyTestLab:
- Basic instrument connection and configuration
- Bench-based measurement with YAML configuration
- Parameter sweeps with MeasurementSession
- Error handling and resource management

All examples use simulation mode - no hardware required.
"""

import time

import numpy as np

import pytestlab
from pytestlab import AutoInstrument
from pytestlab.measurements import MeasurementSession


def basic_instrument_usage():
    """Basic instrument connection and measurement."""
    print("\n=== Basic Instrument Usage ===")

    # Connect to oscilloscope with simulation
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()

    try:
        # Configure channels using direct API (more reliable in simulation)
        scope.set_channel_axis(1, scale=0.5, offset=0.0)
        scope.display_channel(1, True)
        scope.set_channel_axis(2, scale=1.0, offset=0.0)
        scope.display_channel(2, True)
        print("✓ Oscilloscope channels configured")

        # Note: Trigger configuration and data acquisition
        # would be done here with real hardware
        print("✓ Oscilloscope ready for acquisition")

    finally:
        scope.close()


def bench_configuration_example():
    """Using Bench with YAML configuration and safety limits."""
    print("\n=== Bench Configuration Example ===")

    with pytestlab.Bench.open("examples/bench.yaml") as bench:
        # Safe operation using facade API
        print("✓ Bench opened with instruments:")
        for alias in bench.instruments:
            print(f"  - {alias}")

        # Configure power supply using chainable facade
        bench.psu1.channel(1).set(voltage=3.3, current_limit=0.5).on()
        print("✓ Power supply channel 1: 3.3V, 0.5A limit, output ON")

        # Wait for settling
        time.sleep(0.1)

        # Note: In real use, you would measure here
        print("✓ Measurement would be taken here with real hardware")

        # Power off
        bench.psu1.channel(1).off()
        print("✓ Power supply channel 1 turned off")


def parameter_sweep_measurement():
    """Complex measurement session with parameter sweeps."""
    print("\n=== Parameter Sweep Measurement ===")

    with MeasurementSession("Diode I-V Characterization") as meas:
        # Configure instruments (in simulation mode)
        meas.instrument("psu", "keysight/EDU36311A", simulate=True)

        # Define sweep parameters
        meas.parameter("voltage", np.linspace(0, 3.0, 11), unit="V")
        meas.parameter("temperature", [25, 50, 75], unit="°C")

        @meas.acquire
        def measure_iv_point(psu, voltage, temperature):
            """Acquire single I-V measurement point."""

            # Set voltage using facade API
            psu.channel(1).set(voltage=voltage, current_limit=0.1).on()

            # Wait for settling
            time.sleep(0.01)

            # Simulate current measurement
            # In real use: current = psu.read_current(1)
            import random

            current = voltage * 0.01 + random.uniform(-0.001, 0.001)

            # Turn off output
            psu.channel(1).off()

            return {
                "current": current,
                "voltage_applied": voltage,
                "temperature": temperature,
            }

        # Run the measurement
        print("Starting parameter sweep...")
        results = meas.run(show_progress=False)

        # Analyze results
        print(f"✓ Total measurements: {len(results.data)}")
        print(f"✓ Voltage range: 0 to 3.0V")
        print(f"✓ Temperatures tested: 25°C, 50°C, 75°C")


def advanced_measurement_patterns():
    """Advanced patterns with error handling and sequential operations."""
    print("\n=== Advanced Measurement Patterns ===")

    instruments = []

    try:
        # Connect multiple instruments
        psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
        psu.connect_backend()
        instruments.append(psu)

        awg = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
        awg.connect_backend()
        instruments.append(awg)

        print(f"✓ Connected {len(instruments)} instruments")

        # Configure power supply
        psu.channel(1).set(voltage=5.0, current_limit=0.1).on()
        print("✓ Power supply: 5V output enabled")

        # Configure AWG
        awg.channel(1).setup_sine(frequency=1000, amplitude=1.0).enable()
        print("✓ AWG: 1kHz sine wave enabled")

        # Simulate measurement time
        time.sleep(0.1)

        # Cleanup
        awg.channel(1).disable()
        psu.channel(1).off()
        print("✓ All outputs disabled")

    except Exception as e:
        print(f"❌ Error during measurement: {e}")
        raise

    finally:
        # Ensure all instruments are closed
        for inst in instruments:
            try:
                inst.close()
            except Exception:
                pass
        print("✓ All instruments closed")


def database_storage_example():
    """Example of storing measurements in database."""
    print("\n=== Database Storage Example ===")

    import tempfile
    import os

    # Create temporary database
    db_path = tempfile.mktemp(suffix=".db")

    try:
        with pytestlab.Bench.open("examples/bench.yaml") as bench:
            # Initialize database
            bench.initialize_database(db_path)
            print(f"✓ Database initialized: {db_path}")

            # Run a simple measurement
            bench.psu1.channel(1).set(voltage=3.3).on()
            time.sleep(0.1)
            bench.psu1.channel(1).off()

            # Save experiment to database
            if bench.experiment:
                codename = bench.save_experiment(notes="Test measurement")
                print(f"✓ Experiment saved: {codename}")

    finally:
        # Clean up
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"✓ Cleaned up database")


def main():
    """Run all example patterns."""
    print("Running PyTestLab synchronous examples...")
    print("=" * 60)

    try:
        basic_instrument_usage()
        bench_configuration_example()
        parameter_sweep_measurement()
        advanced_measurement_patterns()
        database_storage_example()

        print("\n" + "=" * 60)
        print("✅ All examples completed successfully!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n⚠️ Examples interrupted by user")
    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        raise


if __name__ == "__main__":
    main()
