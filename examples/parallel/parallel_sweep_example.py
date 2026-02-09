"""
PyTestLab: Parallel Measurement Example
========================================

This example demonstrates the parallel task execution feature of the
MeasurementSession. It simulates a common real-world scenario: characterizing
a device's response while its power supply and load are dynamically changing.

Workflow:
1. A Power Supply (`psu`) ramps its voltage up and down in the background.
2. Another Power Supply (`load`) acts as a load in the background.
3. While these two tasks run concurrently, measurements are taken.

Note: This example runs in simulation mode - no hardware required.
"""

import random
import time
from pathlib import Path

import numpy as np

from pytestlab import Bench
from pytestlab import Measurement


def main():
    """Main function to set up and run the parallel measurement."""

    # Define the path to the bench configuration file
    bench_config_path = Path(__file__).parent / "bench_parallel.yaml"

    # Use a Bench object to manage all instruments
    with Bench.open(bench_config_path) as bench:
        print("Bench initialized with the following instruments:")
        for alias in bench.instruments:
            print(f"- {alias}")

        # Create a MeasurementSession, inheriting instruments from the bench
        with Measurement(bench=bench) as session:
            session.name = "Device Ripple Under Dynamic Load"
            session.description = "Measures DUT response while PSU voltage ramps and load changes."

            # Task 1: Ramp the PSU voltage up and down continuously.
            @session.task
            def psu_ramp(psu):
                """Varies the PSU voltage from 1V to 5V and back."""
                print("-> PSU Ramp Task: Started")
                psu.channel(1).set(voltage=1.0, current_limit=1.0).on()
                try:
                    while True:
                        # Ramp up
                        for voltage in np.linspace(1.0, 5.0, 10):
                            psu.channel(1).set(voltage=voltage)
                            time.sleep(0.2)
                        # Ramp down
                        for voltage in np.linspace(5.0, 1.0, 10):
                            psu.channel(1).set(voltage=voltage)
                            time.sleep(0.2)
                except Exception as e:
                    print(f"-> PSU Ramp Task: Stopped ({e})")
                finally:
                    psu.channel(1).off()

            # Task 2: Load changes
            @session.task
            def load_pulse(load):
                """Applies periodic load changes."""
                print("-> Load Pulse Task: Started")
                load.channel(1).set(voltage=3.3, current_limit=0.5).on()
                try:
                    while True:
                        # High load
                        load.channel(1).set(current_limit=0.5)
                        time.sleep(1.0)
                        # Low load
                        load.channel(1).set(current_limit=0.1)
                        time.sleep(1.0)
                except Exception as e:
                    print(f"-> Load Pulse Task: Stopped ({e})")
                finally:
                    load.channel(1).off()

            # Acquisition: Measure ripple voltage
            @session.acquire
            def measure_ripple(psu, load, scope):
                """Measures the output ripple of the DUT."""
                # Simulated ripple measurement
                # In real use, you would use scope.read_channels(1)
                ripple_voltage = random.uniform(0.01, 0.1)  # 10mV to 100mV
                return {"ripple_v": ripple_voltage}

            # Run the parallel measurement for 5 seconds
            print("\nStarting parallel measurement session for 5 seconds...")
            experiment = session.run(duration=5.0, interval=0.25)

            print(f"\n✅ Measurement Complete!")
            print(f"   Captured {len(experiment.data)} measurements.")

            if len(experiment.data) > 0:
                ripples = experiment.data["ripple_v"].to_numpy()
                print(f"   Ripple range: {ripples.min():.3f}V to {ripples.max():.3f}V")


if __name__ == "__main__":
    main()
