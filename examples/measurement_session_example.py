#!/usr/bin/env python3
"""
MeasurementSession Example

This example demonstrates the basic usage of MeasurementSession class:
- Creating a session
- Defining parameters
- Registering measurement functions
- Running a parameter sweep
- Accessing the results

This example runs in simulation mode.
"""
import time
import numpy as np
from pytestlab.measurements.session import MeasurementSession
from pytestlab.instruments import AutoInstrument


def main():
    # Create a measurement session
    print("Creating a measurement session...")
    with MeasurementSession(
        name="Voltage Sweep Test",
        description="Testing voltage response of a simulated device"
    ) as session:
        print(f"Session created: {session.name}")

        # Define parameters for the sweep
        session.parameter("voltage", np.linspace(0, 5, 10), unit="V", notes="Input voltage")
        session.parameter("delay", [0.1, 0.5], unit="s", notes="Settling time")

        # Get instruments (in simulation mode)
        psu = session.instrument("psu", "keysight/EDU36311A", simulate=True)
        dmm = session.instrument("dmm", "keysight/EDU34450A", simulate=True)

        # Define a measurement function
        @session.acquire
        def measure_response(voltage, delay, psu, dmm):
            """Measure the response of a device to an input voltage."""
            print(f"Setting voltage to {voltage:.2f}V, waiting {delay}s...")

            # Set the voltage on channel 1
            psu.set_voltage(1, voltage)
            psu.set_current(1, 0.1)  # Low current limit for safety

            # Enable output
            psu.output(1, True)

            # Wait for the specified delay
            time.sleep(delay)

            # Measure the response (in simulation mode, this will return random values)
            result = dmm.measure_voltage_dc()

            # Turn off the output
            psu.output(1, False)

            # Return a dictionary of measurements
            return {
                "measured_voltage": result.values.nominal_value,
                "timestamp": time.time()
            }

        # Run the measurement sweep
        print("\nStarting measurement sweep...")
        experiment = session.run(show_progress=True)

        # Print the results
        print("\nMeasurement completed!")
        print("\nExperiment data:")
        print(experiment.data)

        # Access specific data columns
        voltages = experiment.data.select("voltage").to_numpy()
        measured = experiment.data.select("measured_voltage").to_numpy()

        print("\nInput vs. Output Summary:")
        print(f"Input voltage range: {voltages.min():.2f}V to {voltages.max():.2f}V")
        print(f"Measured voltage range: {measured.min():.2f}V to {measured.max():.2f}V")

        # Export the data
        print("\nExporting data to experiment_results.parquet")
        experiment.save_parquet("experiment_results.parquet")


if __name__ == "__main__":
    print("PyTestLab MeasurementSession Example")
    print("=" * 40)
    main()
