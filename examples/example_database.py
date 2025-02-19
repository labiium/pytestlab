#!/usr/bin/env python3
"""
example_database.py

This comprehensive example demonstrates how to use the Database class to:
  - Create an Experiment with trial data and detailed notes.
  - Store the Experiment (including parameters and notes) in a SQLite database.
  - Store a MeasurementResult in the database.
  - Retrieve and display the stored Experiment and MeasurementResult.
  - Demonstrate that storing an experiment with a duplicate codename raises an error.
  - Close the database connection.

Before running:
  - Ensure that 'pyarrow' and 'polars' are installed (e.g., via 'pip install pyarrow polars').
  - Adjust the import paths according to your project structure.
"""

import polars as pl
import numpy as np
from datetime import datetime
from pytestlab.experiments import Experiment
from pytestlab.experiments.results import MeasurementResult
from pytestlab.experiments.database import Database

def main():
    # Create a sample Experiment with detailed notes.
    exp = Experiment("Test Experiment", "An experiment to test database storage functionality.")
    exp.notes = "Conducted on 2025-02-19, this experiment validates database storage with detailed notes."
    exp.add_parameter("Temperature", "°C", "Ambient temperature during measurement")
    
    # Create sample trial data using a dictionary.
    trial_data = {
        "Time (s)": [0.0, 1.0, 2.0, 3.0],
        "Voltage (V)": [0.0, 1.0, 2.0, 3.0],
        "Current (A)": [0.0, 0.05, 0.10, 0.15]
    }
    exp.add_trial(trial_data, Temperature=25)
    
    # Add another trial using a Polars DataFrame.
    df_trial = pl.DataFrame({
        "Time (s)": [0.0, 1.0, 2.0, 3.0],
        "Voltage (V)": [0.0, 1.2, 2.4, 3.6],
        "Current (A)": [0.0, 0.06, 0.12, 0.18]
    })
    exp.add_trial(df_trial, Temperature=26)
    
    # Initialize the database (creates "test_experiment.db" in the current directory).
    db = Database("test_experiment")
    
    # Define a unique codename for the experiment.
    exp_codename = "EXP001"
    # Store the experiment.
    try:
        db.store_experiment(exp_codename, exp)
        print("Experiment stored in database.")
    except ValueError as e:
        print(e)
    
    # Attempt to store the same experiment under the same codename to demonstrate error raising.
    try:
        db.store_experiment(exp_codename, exp)
    except ValueError as e:
        print("\nError on duplicate experiment storage:", e)
    
    # Create a sample measurement result.
    meas_value = np.array([1.23, 4.56, 7.89])
    measurement = MeasurementResult(
        values=meas_value,
        instrument="Multimeter_X",
        units="V",
        measurement_type="Voltage"
    )
    measurement.timestamp = datetime.now().timestamp()
    
    meas_codename = "MEAS001"
    try:
        db.store_measurement(meas_codename, measurement)
        print("\nMeasurement stored in database.")
    except Exception as e:
        print(e)
    
    # Retrieve and display the experiment from the database.
    try:
        retrieved_exp = db.retrieve_experiment(exp_codename)
        print("\nRetrieved Experiment:")
        print("Name:", retrieved_exp.name)
        print("Description:", retrieved_exp.description)
        print("Notes:", getattr(retrieved_exp, "notes", "No notes available."))
        print("Trial Data (first few rows):")
        print(retrieved_exp.data.head(5))
    except Exception as e:
        print(e)
    
    # Retrieve and display the measurement from the database.
    try:
        retrieved_meas = db.retrieve_measurement(meas_codename)
        print("\nRetrieved Measurement:")
        print("Instrument:", retrieved_meas.instrument)
        print("Measurement Type:", retrieved_meas.measurement_type)
        print("Units:", retrieved_meas.units)
        print("Values:", retrieved_meas.values)
    except Exception as e:
        print(e)
    
    # Close the database connection.
    db.close()
    print("\nDatabase connection closed.")

if __name__ == "__main__":
    main()
