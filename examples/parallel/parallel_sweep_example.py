"""
PyTestLab: Parallel Measurement Example
========================================

This example demonstrates the new parallel task execution feature of the
MeasurementSession. It simulates a common real-world scenario: characterizing
a device's response (e.g., ripple voltage) while its power supply and load
are dynamically changing.

Workflow:
1. A Power Supply (`psu`) ramps its voltage up and down in the background.
2. A DC Electronic Load (`load`) applies a pulsed load current in the background.
3. While these two tasks run concurrently, an Oscilloscope (`scope`) repeatedly
   acquires waveforms.

This entire process is managed declaratively using the MeasurementSession builder.
"""
import asyncio
import numpy as np
import polars as pl
from pathlib import Path

from pytestlab import Bench, Measurement

async def main():
    """Main function to set up and run the parallel measurement."""

    # Define the path to the bench configuration file
    bench_config_path = Path(__file__).parent / "bench_parallel.yaml"

    # Use a Bench object to manage all instruments
    async with await Bench.open(bench_config_path) as bench:
        print("Bench initialized with the following instruments:")
        for alias in bench.instruments:
            print(f"- {alias}")

        # Create a MeasurementSession, inheriting instruments from the bench
        async with Measurement(bench=bench) as session:
            session.name = "Device Ripple Under Dynamic Load"
            session.description = (
                "Measures DUT output ripple while PSU voltage ramps and "
                "DC load applies current pulses."
            )

            # Task 1: Ramp the PSU voltage up and down continuously.
            # This runs in the background for the entire session duration.
            @session.task
            async def psu_ramp(psu):
                """Varies the PSU voltage from 1V to 5V and back."""
                print("-> PSU Ramp Task: Started")
                await psu.channel(1).set(voltage=1.0, current_limit=1.0).on()
                try:
                    while True:
                        # Ramp up
                        for voltage in np.linspace(1.0, 5.0, 10):
                            await psu.channel(1).set(voltage=voltage)
                            await asyncio.sleep(0.2)
                        # Ramp down
                        for voltage in np.linspace(5.0, 1.0, 10):
                            await psu.channel(1).set(voltage=voltage)
                            await asyncio.sleep(0.2)
                except asyncio.CancelledError:
                    print("-> PSU Ramp Task: Stopped")
                    await psu.channel(1).off()

            # Task 2: Apply a pulsed load current.
            # This also runs in the background.
            @session.task
            async def load_pulse(load):
                """Applies a 1A pulse load with a 50% duty cycle."""
                print("-> DC Load Pulse Task: Started")
                await load.set_mode("CC") # Constant Current mode
                await load.enable_input(True)
                try:
                    while True:
                        await load.set_load(1.0)  # 1A load
                        await asyncio.sleep(0.5)
                        await load.set_load(0.1)  # 0.1A load
                        await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    print("-> DC Load Pulse Task: Stopped")
                    await load.enable_input(False)

            # Acquisition Task: Repeatedly measure with the oscilloscope.
            # This is the main data collection loop.
            @session.acquire
            async def measure_ripple(scope):
                """Acquires a waveform and calculates its Vpp as ripple."""
                await scope._send_command(":SINGle")
                await asyncio.sleep(0.05) # Allow time for acquisition
                waveform_result = await scope.read_channels(1)
                vpp_result = await scope.measure_voltage_peak_to_peak(1)

                return {
                    "vpp_ripple": vpp_result.values,
                    "waveform_data": waveform_result.values # Store the full waveform
                }

            # Run the session in parallel mode for 5 seconds,
            # acquiring data every 250ms.
            print("\nStarting parallel measurement session for 5 seconds...")
            experiment = await session.run(duration=5.0, interval=0.25)
            print("Session finished.")

    # --- Analysis ---
    print("\n--- Results ---")
    results_df = experiment.data
    print(results_df)

    # Example of post-processing the collected data
    if not results_df.is_empty():
        max_ripple = results_df["vpp_ripple"].max()
        avg_ripple = results_df["vpp_ripple"].mean()
        print(f"\nMaximum observed ripple: {max_ripple:.4f} V")
        print(f"Average observed ripple: {avg_ripple:.4f} V")

        # You can also access the detailed waveform data for further analysis
        first_waveform = results_df["waveform_data"][0]
        print("\nSchema of the first captured waveform:")
        print(first_waveform)


if __name__ == "__main__":
    asyncio.run(main())
