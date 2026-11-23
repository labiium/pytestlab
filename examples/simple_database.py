#!/usr/bin/env python3
"""
PyTestLab Simple Database Example

This example demonstrates:
  - Creating an Experiment with trial data
  - Storing experiments in the measurement database
  - Retrieving experiments from the database

This example creates a temporary database that is cleaned up after.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from pytestlab import Experiment
from pytestlab.experiments.database import MeasurementDatabase


def main():
    """Run the simple database example."""
    print("=" * 60)
    print("PyTestLab Simple Database Example")
    print("=" * 60)

    # Create an experiment
    print("\n--- Creating Experiment ---")
    exp = Experiment(
        name="Simple Device Test", description="A basic experiment to demonstrate database storage"
    )

    # Add some parameters
    exp.add_parameter("Temperature", "°C", "Ambient temperature")
    exp.add_parameter("TestID", "", "Test identifier")

    # Add trial data
    print("Adding trial data...")
    exp.add_trial(
        {
            "Time (s)": [0, 1, 2, 3, 4],
            "Voltage (V)": [0.0, 1.0, 2.0, 3.0, 4.0],
            "Current (A)": [0.0, 0.1, 0.2, 0.3, 0.4],
        },
        Temperature=25,
        TestID="T001",
    )

    exp.add_trial(
        {
            "Time (s)": [0, 1, 2, 3, 4],
            "Voltage (V)": [0.0, 1.2, 2.4, 3.6, 4.8],
            "Current (A)": [0.0, 0.12, 0.24, 0.36, 0.48],
        },
        Temperature=30,
        TestID="T002",
    )

    print(f"  Created experiment with {len(exp.data)} rows of data")

    # Create and use the database
    with TemporaryDirectory(prefix="pytestlab-example-") as directory:
        path = Path(directory) / "example.db"
        with MeasurementDatabase(path) as db:
            exp_id = db.store_experiment(None, exp)
            print(f"  Stored experiment with ID: {exp_id}")
            print("  Experiments:", db.list_experiments())
            retrieved = db.retrieve_experiment(exp_id)
            print(f"  Retrieved: {retrieved.name}; {len(retrieved.data)} rows")

    print("\n" + "=" * 60)
    print("Database example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
