#!/usr/bin/env python3
"""
example.py

This script demonstrates the usage of the Experiment class:
  - Creating an experiment instance with a name and description.
  - Adding experiment parameters.
  - Adding trial data in various formats (dictionary and Polars DataFrame) with extra parameter columns.
  - Printing the experiment summary (which displays the head of the data).
  - Exporting the data to disk as both an Apache Arrow file and a Parquet file.

Note:
  Make sure that 'pyarrow' is installed (e.g., via 'pip install pyarrow').
"""

import polars as pl
from pytestlab.experiments import Experiment  # Adjust this import based on your project structure

def main():
    # Create an experiment instance.
    exp = Experiment("Voltage Sweep Experiment", "Testing device response over various voltages.")
    
    # Add experiment parameters.
    exp.add_parameter("Temperature", "°C", "Ambient temperature during measurement")
    exp.add_parameter("TestID", "id", "Identifier for each trial")
    
    # ----------------------------
    # Add trial 1: data provided as a dictionary.
    # ----------------------------
    trial1 = {
        "Time (s)": [0.0, 1.0, 2.0, 3.0, 4.0],
        "Voltage (V)": [0.0, 1.0, 2.0, 3.0, 4.0],
        "Current (A)": [0.0, 0.1, 0.2, 0.3, 0.4]
    }
    exp.add_trial(trial1, Temperature=25, TestID="Trial1")
    
    # ----------------------------
    # Add trial 2: data provided as a dictionary (with different values).
    # ----------------------------
    trial2 = {
        "Time (s)": [0.0, 1.0, 2.0, 3.0, 4.0],
        "Voltage (V)": [0.0, 2.0, 4.0, 6.0, 8.0],
        "Current (A)": [0.0, 0.2, 0.4, 0.6, 0.8]
    }
    exp.add_trial(trial2, Temperature=30, TestID="Trial2")
    
    # ----------------------------
    # Add trial 3: data provided as a Polars DataFrame.
    # ----------------------------
    df_trial3 = pl.DataFrame({
        "Time (s)": [0.0, 1.0, 2.0, 3.0, 4.0],
        "Voltage (V)": [0.0, 1.5, 3.0, 4.5, 6.0],
        "Current (A)": [0.0, 0.15, 0.3, 0.45, 0.6]
    })
    exp.add_trial(df_trial3, Temperature=28, TestID="Trial3")
    
    # ----------------------------
    # Inspect and export the experiment data.
    # ----------------------------
    
    # Print the experiment instance.
    # The __str__ method shows experiment details and the first 5 rows of trial data.
    print(exp)
    
    # Export data to disk.
    # exp.save_arrow("experiment_data.arrow")
    exp.save_parquet("experiment_data.parquet")

if __name__ == "__main__":
    main()
