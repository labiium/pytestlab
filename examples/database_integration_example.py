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
"""
import os
import shutil
import time
import numpy as np
import polars as pl
from pathlib import Path
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

from pytestlab.bench import Bench
from pytestlab.measurements.session import MeasurementSession
from pytestlab.experiments.database import MeasurementDatabase


# Create a temporary database path for this example
DB_PATH = "example_measurements.db"


def run_experiment(name, description, base_voltages, collector_range):
    """Run an experiment with the given parameters."""
    # Create a bench config with the database path
    bench_config = {
        "bench_name": "Transistor Test Bench",
        "description": "Database integration example bench",
        "version": "1.0.0",
        "experiment": {
            "title": name,
            "description": description,
            "operator": "Database Example Script",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "database_path": DB_PATH,
            "notes": "Automatically generated experiment for database integration example."
        },
        "simulate": True,
        "backend_defaults": {
            "type": "lamb"
        },
        "instruments": {
            "psu": {
                "profile": "keysight/EDU36311A",
                "backend": {"type": "lamb"}
            },
            "dmm": {
                "profile": "keysight/EDU34450A",
                "backend": {"type": "lamb"}
            }
        }
    }

    # Initialize bench from config dictionary
    with Bench.open_from_dict(bench_config) as bench:
        print(f"✅ Bench initialized for experiment: {name}")

        # Create measurement session using the bench
        with MeasurementSession(bench=bench) as session:
            # Define parameters
            session.parameter("V_base", base_voltages, unit="V",
                             notes="Base voltage for transistor")
            session.parameter("V_collector", collector_range, unit="V",
                             notes="Collector voltage sweep")

            # Define measurement function
            @session.acquire
            def measure_transistor(V_base, V_collector, psu, dmm):
                """Measure transistor collector current at specified voltages."""
                # Set up base voltage on channel 1
                psu.set_voltage(1, V_base)
                psu.set_current(1, 0.05)

                # Set up collector voltage on channel 2
                psu.set_voltage(2, V_collector)
                psu.set_current(2, 0.5)

                # Turn on outputs
                psu.output(1, True)
                psu.output(2, True)

                # Wait for circuit to stabilize
                time.sleep(0.05)

                # Measure collector current
                result = dmm.measure_current_dc()
                collector_current = result.values.nominal_value

                # Add some simulated calculation
                beta = collector_current / (V_base * 0.001)  # Simple hFE calculation

                # Turn off outputs
                psu.output(1, False)
                psu.output(2, False)

                # Return measurement data
                return {
                    "I_collector": collector_current,
                    "hFE": beta
                }

            # Run the measurement sweep
            print(f"🔄 Running measurement sweep...")
            experiment = session.run(show_progress=True)

            print(f"✅ Experiment completed: {len(experiment.data)} data points")
            return experiment


def run_multiple_experiments():
    """Run multiple experiments to populate the database."""
    # Remove any existing database file
    if os.path.exists(DB_PATH):
        os.unlink(DB_PATH)

    # Run first experiment - low base voltages
    experiment1 = run_experiment(
        name="Transistor Low Voltage Test",
        description="Characterization at low base voltages",
        base_voltages=np.linspace(0.5, 0.7, 3),
        collector_range=np.linspace(0, 5, 6)
    )

    # Wait a moment to ensure database writes complete
    time.sleep(0.5)

    # Run second experiment - high base voltages
    experiment2 = run_experiment(
        name="Transistor High Voltage Test",
        description="Characterization at high base voltages",
        base_voltages=np.linspace(0.8, 1.0, 3),
        collector_range=np.linspace(0, 5, 6)
    )

    # Return both experiments
    return experiment1, experiment2


def analyze_database():
    """Analyze the contents of the database."""
    print("\n" + "=" * 50)
    print("📊 Database Analysis")
    print("=" * 50)

    # Open the database directly
    db = MeasurementDatabase(DB_PATH)

    # List all experiments in the database
    experiments = db.list_experiments()
    print(f"Found {len(experiments)} experiments in the database:")

    # Display and analyze each experiment
    for i, exp_id in enumerate(experiments):
        print(f"\n📋 Experiment {i+1}: {exp_id}")

        # Retrieve the experiment
        experiment = db.retrieve_experiment(exp_id)

        print(f"  Title: {experiment.name}")
        print(f"  Description: {experiment.description}")
        print(f"  Data points: {len(experiment.data)}")
        print(f"  Parameters: {', '.join(experiment.parameters.keys())}")

        # Get unique base voltages
        base_voltages = sorted(set(experiment.data['V_base'].to_numpy().flatten()))
        print(f"  Base voltages tested: {[f'{v:.1f}V' for v in base_voltages]}")

        # Calculate statistics
        avg_current = experiment.data['I_collector'].mean()
        max_current = experiment.data['I_collector'].max()
        avg_gain = experiment.data['hFE'].mean()

        print(f"  Average collector current: {avg_current:.2f}A")
        print(f"  Maximum collector current: {max_current:.2f}A")
        print(f"  Average transistor gain (hFE): {avg_gain:.1f}")

    # Cross-experiment analysis
    if len(experiments) > 1:
        print("\n🔍 Cross-Experiment Analysis")

        # Compare the experiments
        results = []
        for exp_id in experiments:
            exp = db.retrieve_experiment(exp_id)

            # Calculate average gain per base voltage
            for v_base in sorted(set(exp.data["V_base"].to_numpy().flatten())):
                base_rows = exp.data.filter(pl.col("V_base") == v_base)
                avg_gain = base_rows["hFE"].mean()
                max_current = base_rows["I_collector"].max()

                results.append({
                    "experiment": exp.name,
                    "V_base": v_base,
                    "avg_hFE": avg_gain,
                    "max_I_collector": max_current
                })

        # Convert to DataFrame for easy analysis
        results_df = pl.DataFrame(results)
        print("\nGain and Current by Base Voltage:")
        print(results_df)

    # Close the database connection
    db.close()
    print("\n💾 Database analysis complete.")


def main():
    # Run multiple experiments and store them in the database
    print("🧪 Running transistor characterization experiments...")
    experiment1, experiment2 = run_multiple_experiments()

    # Analyze the database contents
    analyze_database()

    print("\n✅ Database integration example completed successfully.")
    print(f"Database file: {DB_PATH}")


if __name__ == "__main__":
    print("📊 PyTestLab Database Integration Example")
    print("=" * 60)

    # Run the main function
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Example interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
