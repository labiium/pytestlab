#!/usr/bin/env python3
"""
Parallel Measurement Demo - PyTestLab Synchronous API
====================================================

This example demonstrates how to use the @session.task decorator to run
background operations in parallel with data acquisition. This is essential
for complex experiments where you need multiple things happening simultaneously.

Example scenarios:
- PSU ramping voltage while acquiring scope data
- Load cycling on/off while monitoring power consumption
- Temperature control while measuring device characteristics
- Stimulus generation while recording responses

Note: This example uses simulation mode - no hardware required.
"""

import random
import time

import numpy as np

from pytestlab.measurements import MeasurementSession


def basic_parallel_example():
    """Basic example with PSU ramping while measuring voltage."""
    print("\n=== Basic Parallel Example ===")

    with MeasurementSession("PSU Ramp + Voltage Monitoring") as session:
        # Setup instruments (simulation mode)
        session.instrument("psu", "keysight/EDU36311A", simulate=True)

        # Task 1: Ramp PSU voltage from 0 to 5V over 5 seconds
        @session.task
        def voltage_ramp(psu):
            print("🔄 Starting voltage ramp...")
            for v in np.linspace(0, 5, 20):
                psu.channel(1).set(voltage=v, current_limit=0.1).on()
                time.sleep(0.25)
            print("🛑 Voltage ramp stopped")

        # Acquisition: Monitor voltage every 200ms
        @session.acquire
        def monitor_voltage(psu):
            # In simulation, we return the set voltage with some noise
            # In real use, you would measure with DMM
            voltage = 2.5 + random.uniform(-0.1, 0.1)  # Simulated measurement
            return {"measured_voltage": voltage}

        # Run for 5 seconds, acquire every 200ms
        print("🎯 Running parallel measurement for 5 seconds...")
        experiment = session.run(duration=5.0, interval=0.2)

        print(f"✅ Captured {len(experiment.data)} voltage measurements")
        if len(experiment.data) > 0:
            voltages = experiment.data["measured_voltage"].to_numpy()
            print(f"📊 Voltage range: {voltages.min():.2f}V to {voltages.max():.2f}V")


def complex_parallel_example():
    """Complex example with multiple parallel tasks."""
    print("\n=== Complex Parallel Example ===")

    with MeasurementSession("Multi-Task Power Analysis") as session:
        # Setup instruments
        session.instrument("psu", "keysight/EDU36311A", simulate=True)
        session.instrument(
            "load", "keysight/EDU36311A", simulate=True
        )  # Using PSU as load for demo
        session.instrument("scope", "keysight/DSOX1204G", simulate=True)

        # Task 1: PSU voltage stepping
        @session.task
        def voltage_stepping(psu):
            voltages = [3.3, 5.0, 5.0, 3.3, 3.3]  # Within 6V limit for EDU36311A Ch1
            for v in voltages:
                psu.channel(1).set(voltage=v, current_limit=1.0).on()
                time.sleep(1.0)
            psu.channel(1).off()

        # Task 2: Load cycling (simulated)
        @session.task
        def load_cycling(load):
            for i in range(6):
                state = "ON" if i % 2 == 0 else "OFF"
                print(f"  Load: {state}")
                time.sleep(1.0)

        # Acquisition: Measure power
        @session.acquire
        def measure_power(psu, load, scope):
            # Simulated measurements
            voltage = 5.0 + random.uniform(-0.1, 0.1)
            current = 0.5 + random.uniform(-0.05, 0.05)
            power = voltage * current

            return {
                "voltage": voltage,
                "current": current,
                "power": power,
            }

        # Run for 6 seconds
        print("🎯 Running complex parallel measurement...")
        experiment = session.run(duration=6.0, interval=0.5)

        print(f"✅ Captured {len(experiment.data)} power measurements")
        if len(experiment.data) > 0:
            powers = experiment.data["power"].to_numpy()
            print(f"📊 Power range: {powers.min():.2f}W to {powers.max():.2f}W")


def main():
    """Run all parallel measurement examples."""
    print("🧪 PyTestLab Parallel Measurement Demo")
    print("=" * 60)

    try:
        basic_parallel_example()
        complex_parallel_example()

        print("\n" + "=" * 60)
        print("✅ All parallel measurement examples completed!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
