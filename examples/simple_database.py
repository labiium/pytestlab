#!/usr/bin/env python3
"""
PyTestLab Simple Database Example

This example demonstrates:
  - Creating an Experiment with trial data
  - Storing experiments in the measurement database
  - Retrieving experiments from the database
  - Searching experiments

This example creates a temporary database that is cleaned up after.
"""

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
    db_path = "simple_example.db"
    print(f"\n--- Using Database: {db_path} ---")

    try:
        # Open the database (creates it if it doesn't exist)
        db = MeasurementDatabase(db_path)

        # Store the experiment
        exp_id = db.store_experiment(None, exp)
        print(f"  Stored experiment with ID: {exp_id}")

        # List all experiments
        print("\n--- Listing Experiments ---")
        experiments = db.list_experiments()
        print(f"  Database contains {len(experiments)} experiment(s)")
        for exp_codename in experiments:
            print(f"    - {exp_codename}")

        # Retrieve the experiment
        print("\n--- Retrieving Experiment ---")
        retrieved = db.retrieve_experiment(exp_id)
        print(f"  Retrieved: {retrieved.name}")
        print(f"  Description: {retrieved.description}")
        print(f"  Data rows: {len(retrieved.data)}")

        # Close the database
        db.close()
        print("\n  Database connection closed")

    finally:
        # Clean up the database file
        import os

        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"  Cleaned up: {db_path}")

    print("\n" + "=" * 60)
    print("Database example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
