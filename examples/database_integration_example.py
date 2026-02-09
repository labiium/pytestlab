#!/usr/bin/env python3
"""
Database Integration Example

This example demonstrates the complete integration between:
- Bench: For instrument management and experiment context
- MeasurementSession: For parameter sweeps and measurements
- Experiment: For data capture and metadata
- MeasurementDatabase: For persistent storage and retrieval

The example shows:
1. Creating and running experiments with a bench and session
2. Storing experiments in a database
3. Retrieving and analyzing stored experiments
4. Managing multiple experiments in a single database

Note: This example runs in simulation mode - no hardware required.
"""

import os
import random
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

from pytestlab.bench import Bench
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.measurements.session import MeasurementSession

# Create a temporary database path for this example
DB_PATH = "example_measurements.db"


def run_experiment_with_bench(name, description, base_voltages, collector_range, db_path=None):
    """Run an experiment using a bench configuration file."""
    # Use the session_bench.yaml file as a base
    bench_file = Path(__file__).parent / "session_bench.yaml"

    print(f"\n🔬 Running experiment: {name}")
    print(f"   Description: {description}")

    # Open the bench
    with Bench.open(bench_file) as bench:
        print(f"✅ Bench '{bench.name}' opened")

        # Override database path if provided
        if db_path:
            bench.initialize_database(db_path)

        # Create measurement session
        with MeasurementSession(bench=bench, name=name, description=description) as session:
            print(f"📊 Session created: {session.name}")

            # Define parameters
            session.parameter("V_base", base_voltages, unit="V", notes="Base voltage")
            session.parameter("V_collector", collector_range, unit="V", notes="Collector voltage")

            # Get instruments from bench
            psu = bench.psu
            dmm = bench.dmm

            @session.acquire
            def measure_transistor(V_base, V_collector, psu, dmm):
                """Measure transistor characteristics."""
                # Set up base voltage on channel 1
                psu.set_voltage(1, V_base)
                psu.set_current(1, 0.05)

                # Set up collector voltage on channel 2
                psu.set_voltage(2, V_collector)
                psu.set_current(2, 0.5)

                # Turn on outputs
                psu.output(1, True)
                psu.output(2, True)

                # Wait for stabilization
                time.sleep(0.05)

                # Simulate measurement (in real use: dmm.measure(DMMFunction.CURRENT_DC))
                collector_current = random.uniform(0.001, 0.1)

                # Turn off outputs
                psu.output(1, False)
                psu.output(2, False)

                return {
                    "I_collector": collector_current,
                    "V_ce": V_collector,
                    "V_be": V_base,
                }

            # Run the sweep
            experiment = session.run(show_progress=False)
            print(f"✅ Experiment completed with {len(experiment.data)} data points")

            # Save to database if available
            if bench.db:
                codename = bench.save_experiment()
                print(f"💾 Experiment saved to database: {codename}")

            return experiment


def analyze_experiments(db_path):
    """Analyze experiments stored in the database."""
    print("\n" + "=" * 60)
    print("📊 ANALYZING STORED EXPERIMENTS")
    print("=" * 60)

    # Open the database
    db = MeasurementDatabase(db_path)

    # List all experiments
    experiments = db.list_experiments()
    print(f"\n📋 Database contains {len(experiments)} experiment(s)")

    # Analyze each experiment
    for codename in experiments:
        print(f"\n--- Experiment: {codename} ---")

        # Retrieve the experiment
        experiment = db.retrieve_experiment(codename)
        print(f"Name: {experiment.name}")
        print(f"Description: {experiment.description}")
        print(f"Data points: {len(experiment.data)}")

        # Show summary statistics
        if len(experiment.data) > 0:
            df = experiment.data
            numeric_cols = [c for c in df.columns if df[c].dtype in (pl.Float64, pl.Int64)]

            for col in numeric_cols[:3]:  # Show first 3 numeric columns
                mean_val = df[col].mean()
                max_val = df[col].max()
                print(f"  {col}: mean={mean_val:.4f}, max={max_val:.4f}")

    db.close()


def main():
    """Run the database integration example."""
    print("📊 PyTestLab Database Integration Example")
    print("=" * 60)
    print("This example demonstrates:")
    print("  1. Running experiments with Bench + MeasurementSession")
    print("  2. Storing experiments in MeasurementDatabase")
    print("  3. Retrieving and analyzing stored experiments")
    print()

    # Clean up any existing database
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"🗑️ Cleaned up existing database: {DB_PATH}")

    try:
        # Run first experiment - Low voltage test
        experiment1 = run_experiment_with_bench(
            name="Transistor Low Voltage Test",
            description="Testing transistor at lower base voltages",
            base_voltages=np.linspace(0.6, 0.8, 3),
            collector_range=np.linspace(0, 3, 4),
            db_path=DB_PATH,
        )

        # Run second experiment - High voltage test
        experiment2 = run_experiment_with_bench(
            name="Transistor High Voltage Test",
            description="Testing transistor at higher base voltages",
            base_voltages=np.linspace(0.8, 1.0, 3),
            collector_range=np.linspace(0, 5, 6),
            db_path=DB_PATH,
        )

        # Analyze stored experiments
        analyze_experiments(DB_PATH)

        # Demonstrate data export
        print("\n" + "=" * 60)
        print("📤 DATA EXPORT EXAMPLES")
        print("=" * 60)

        # Export to Parquet
        parquet_file = "experiment_data.parquet"
        experiment1.save_parquet(parquet_file)
        print(f"✅ Exported experiment 1 to: {parquet_file}")

        # Clean up exported file
        if os.path.exists(parquet_file):
            os.remove(parquet_file)
            print(f"🗑️ Cleaned up: {parquet_file}")

        print("\n" + "=" * 60)
        print("✅ DATABASE INTEGRATION EXAMPLE COMPLETED")
        print("=" * 60)
        print(f"\nDatabase file: {DB_PATH}")
        print("You can use SQLite browser tools to inspect the database contents.")

    finally:
        # Clean up the database file
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print(f"\n🗑️ Cleaned up database: {DB_PATH}")


if __name__ == "__main__":
    main()
