#!/usr/bin/env python3
"""
PyTestLab Simple Plotting Example

This example demonstrates:
  - Creating an experiment with sample data
  - Plotting experiment data
  - Configuring plot appearance

Note: This example creates plots using matplotlib. The plots are saved to files
rather than displayed, making it suitable for automated testing.
"""

import numpy as np
from pytestlab import Experiment
from pytestlab.plotting import PlotSpec


def main():
    """Run the simple plotting example."""
    print("=" * 60)
    print("PyTestLab Simple Plotting Example")
    print("=" * 60)

    # Create an experiment with sample data
    print("\n--- Creating Experiment with Sample Data ---")
    exp = Experiment(
        name="Voltage Sweep Analysis", description="Demonstration of plotting capabilities"
    )

    # Define any parameters we'll use
    exp.add_parameter("Temperature", "°C", "Ambient temperature")

    # Generate sample data - a simple voltage sweep with some noise
    time_points = np.linspace(0, 10, 100)
    voltage = np.linspace(0, 5, 100)
    current = voltage / 10 + np.random.normal(0, 0.01, 100)  # I = V/R + noise
    power = voltage * current

    exp.add_trial(
        {
            "Time (s)": time_points,
            "Voltage (V)": voltage,
            "Current (A)": current,
            "Power (W)": power,
        },
        Temperature=25,
    )

    print(f"  Created experiment with {len(exp.data)} data points")

    # Create a plot specification
    print("\n--- Configuring Plot ---")
    plot_spec = PlotSpec(
        title="Voltage Sweep Results", xlabel="Voltage (V)", ylabel="Current (A)", grid=True
    )
    print(f"  Title: {plot_spec.title}")
    print(f"  X-axis: {plot_spec.xlabel}")
    print(f"  Y-axis: {plot_spec.ylabel}")

    # Generate the plot
    print("\n--- Generating Plot ---")
    try:
        fig = exp.plot(plot_spec)
        print("  Plot generated successfully!")

        # Save the plot to a file
        output_file = "simple_plot.png"
        fig.savefig(output_file, dpi=150, bbox_inches="tight")
        print(f"  Plot saved to: {output_file}")

        # Clean up the plot file
        import os

        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"  Cleaned up: {output_file}")

    except Exception as e:
        print(f"  Note: Plotting requires matplotlib: {e}")
        print("  To install: pip install 'pytestlab[plot]'")

    print("\n" + "=" * 60)
    print("Plotting example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
