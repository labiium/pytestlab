#!/usr/bin/env python3
"""
PyTestLab Simple Parameter Sweep Example

This example demonstrates:
  - Creating a MeasurementSession
  - Defining sweep parameters
  - Using the @session.acquire decorator
  - Running a parameter sweep
  - Exporting results

All instruments run in simulation mode - no hardware required.
"""

import numpy as np
from pytestlab import MeasurementSession


def main():
    """Run the simple sweep example."""
    print("=" * 60)
    print("PyTestLab Simple Parameter Sweep Example")
    print("=" * 60)

    # Create a measurement session
    # This is a context manager that handles setup and cleanup
    with MeasurementSession(
        name="Voltage Response Test", description="Simple voltage sweep demonstration"
    ) as session:
        print(f"\nSession created: {session.name}")

        # Define sweep parameters
        # These will be combined to create a full factorial sweep
        print("\n--- Defining Parameters ---")
        session.parameter("voltage", np.linspace(0, 5, 6), unit="V")
        session.parameter("delay", [0.1, 0.2], unit="s")
        print("  voltage: 0 to 5V in 6 steps")
        print("  delay: 0.1s and 0.2s")
        print(f"  Total combinations: {6 * 2}")

        # Add instruments to the session
        print("\n--- Adding Instruments ---")
        session.instrument("psu", "keysight/EDU36311A", simulate=True)
        print("  Power supply (psu): EDU36311A")

        # Define the measurement function
        # The @session.acquire decorator registers this function
        # It will be called for each parameter combination
        @session.acquire
        def measure_response(voltage, delay, psu):
            """
            Perform a measurement for each parameter combination.

            Args:
                voltage: The voltage value for this sweep point
                delay: The delay value for this sweep point
                psu: The power supply instrument (automatically injected)

            Returns:
                A dictionary of measurement results
            """
            # Set the voltage on channel 1
            psu.set_voltage(1, voltage)

            # Set a current limit for safety
            psu.set_current(1, 0.1)

            # Enable output
            psu.output(1, True)

            # In a real measurement, you might wait here
            # For this example, we just print what we're doing
            print(f"  Measuring at {voltage:.1f}V with {delay:.1f}s delay...")

            # Simulate a response (in real use, you'd measure actual DUT response)
            import random

            measured_value = voltage * (1 + random.uniform(-0.05, 0.05))

            # Disable output
            psu.output(1, False)

            # Return the measurement data
            return {
                "measured_voltage": measured_value,
                "error_percent": abs(measured_value - voltage) / voltage * 100
                if voltage > 0
                else 0,
            }

        # Run the sweep
        print("\n--- Running Sweep ---")
        experiment = session.run(show_progress=True)

        # Display results
        print("\n--- Results ---")
        print(f"Total measurements: {len(experiment.data)}")
        print("\nFirst 5 rows:")
        print(experiment.data.head(5))

        # Export to file
        output_file = "simple_sweep_results.parquet"
        experiment.save_parquet(output_file)
        print(f"\nResults saved to: {output_file}")

    print("\n" + "=" * 60)
    print("Sweep example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
