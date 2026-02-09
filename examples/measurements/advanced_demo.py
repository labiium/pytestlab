#!/usr/bin/env python3
"""
advanced_demo.py – End-to-end showcase
======================================

* MeasurementSession with two parameters and two instruments
* Auto-generated experiment code on DB insert
* Rich DataFrame with scalar + vector columns

Note: This example runs in simulation mode - no hardware required.
"""

from __future__ import annotations

import random

import numpy as np

from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.measurements import Measurement


def main():
    """Run the advanced demo."""
    print("Advanced Measurement Demo")
    print("=" * 60)

    # Create a measurement session with database storage
    db_path = "advanced_demo.db"

    with Measurement("Demo sweep", "End-to-end showcase") as m:
        # Setup instruments (simulation mode)
        psu = m.instrument("psu", "keysight/EDU36311A", simulate=True)
        dmm = m.instrument("dmm", "keysight/EDU34450A", simulate=True)

        # Define parameters
        m.parameter("V_BIAS", np.linspace(0, 5, 6), unit="V")
        m.parameter("REP", range(3))

        @m.acquire
        def sweep(psu, dmm, V_BIAS, REP):
            # Set voltage
            psu.channel(1).set(voltage=V_BIAS, current_limit=0.1).on()

            # Simulated measurement
            import time

            time.sleep(0.05)

            # Simulated DMM reading
            current = (V_BIAS / 10) + random.uniform(-0.01, 0.01)

            psu.channel(1).off()

            return {
                "current": current,
                "vector": np.random.randn(4),  # Vector data
            }

        # Run the sweep
        print("Running measurement sweep...")
        experiment = m.run(show_progress=False)

        print(f"\n✓ Captured {len(experiment.data)} measurements")
        print(f"\nData preview:")
        print(experiment.data)

        # Save to database
        print(f"\nSaving to database: {db_path}")
        db = MeasurementDatabase(db_path)
        codename = db.store_experiment(None, experiment)
        print(f"✓ Stored with codename: {codename}")

        # Retrieve and verify
        retrieved = db.retrieve_experiment(codename)
        print(f"✓ Retrieved experiment: {retrieved.name}")
        print(f"  Data points: {len(retrieved.data)}")

        db.close()

        # Clean up
        import os

        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"✓ Cleaned up database")

    print("\n" + "=" * 60)
    print("Demo completed successfully!")


if __name__ == "__main__":
    main()
