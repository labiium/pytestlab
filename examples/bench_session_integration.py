#!/usr/bin/env python3
"""
Bench and MeasurementSession Integration Example

This example demonstrates the integration between:
- Bench: For instrument management and experiment context
- MeasurementSession: For parameter sweeps and measurement functions
- Experiment: For data capture
- MeasurementDatabase: For persistence

The example performs a transistor characterization using a bench configuration
loaded from YAML, and executes a parameter sweep with the session.
"""
import os
import numpy as np
import time
from pathlib import Path

from pytestlab.bench import Bench
from pytestlab.measurements.session import MeasurementSession


def main():
    # Path to the bench configuration YAML file
    bench_file = Path(__file__).parent / "session_bench.yaml"

    # Open the bench - this initializes instruments and experiment context
    print(f"Opening bench from: {bench_file}")
    with Bench.open(bench_file) as bench:
        print(f"✅ Bench '{bench.name}' opened successfully")
        print(f"📋 Experiment: {bench.experiment.name}")

        # Verify database connection
        if bench.db:
            print(f"💾 Database connected: {bench.db.db_path}")

        # Create a measurement session that uses the bench
        # The session inherits experiment metadata and instruments from the bench
        with MeasurementSession(bench=bench) as session:
            print(f"\n📊 Session created: {session.name}")

            # Define parameters for the sweep
            # Base voltage parameter - sweep from 0.6V to 1.0V in 5 steps
            session.parameter("V_base", np.linspace(0.6, 1.0, 5), unit="V", notes="Base voltage")

            # Collector voltage parameter - sweep from 0V to 5V in 10 steps
            session.parameter("V_collector", np.linspace(0, 5, 10), unit="V", notes="Collector voltage")

            # Define a measurement function using bench instruments
            @session.acquire
            def measure_transistor(V_base, V_collector, psu, dmm):
                """Measure transistor collector current at given base and collector voltages."""
                print(f"Setting V_base={V_base:.2f}V, V_collector={V_collector:.2f}V")

                # Set up base voltage on channel 1
                psu.set_voltage(1, V_base)
                psu.set_current(1, 0.05)  # 50mA limit for base

                # Set up collector voltage on channel 2
                psu.set_voltage(2, V_collector)
                psu.set_current(2, 0.5)   # 500mA limit for collector

                # Turn on outputs
                psu.output(1, True)
                psu.output(2, True)

                # Wait for circuit to stabilize
                time.sleep(0.1)

                # Measure collector current (in simulation mode this will return random values)
                result = dmm.measure_current_dc()
                collector_current = result.values.nominal_value

                # Turn off outputs
                psu.output(1, False)
                psu.output(2, False)

                # Return measurements
                return {
                    "I_collector": collector_current,
                    "V_ce": V_collector,  # Collector-emitter voltage
                    "V_be": V_base,       # Base-emitter voltage
                }

            # Run the measurement sweep
            print("\n🔄 Starting measurement sweep...")
            experiment = session.run(show_progress=True)

            # The experiment object is already saved to the database by the bench
            print("\n✅ Measurement completed!")

            # Display results
            print("\n📈 Experiment data:")
            print(experiment.data.head(10))  # Show first 10 rows

            # Calculate transistor parameters
            print("\n🔍 Transistor characteristics:")
            df = experiment.data

            # Group by base voltage and show collector current range
            for v_base in sorted(set(df["V_base"].to_numpy().flatten())):
                base_rows = df.filter(pl.col("V_base") == v_base)
                i_collector_max = base_rows["I_collector"].max()
                print(f"Base voltage {v_base:.2f}V → Max collector current: {i_collector_max:.3f}A")

            # Report experiment database info
            print(f"\n💾 Experiment saved to database: {os.path.basename(bench.db.db_path)}")
            print(f"Experiment name: {bench.experiment.name}")
            print(f"Number of data points: {len(experiment.data)}")


if __name__ == "__main__":
    print("🧪 PyTestLab Bench-Session Integration Example")
    print("=" * 50)

    # Import polars for DataFrame operations after initial imports have succeeded
    # This ensures the error messages are clearer if imports fail
    import polars as pl

    main()
