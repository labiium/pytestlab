import unittest
import os
import numpy as np
from datetime import datetime
# Import your classes here, adjust the import paths as needed
from pytestlab.experiments import Database, MeasurementResult, Experiment
import polars as pl
import numpy as np

class TestDatabase(unittest.TestCase):
    def setUp(self):
        """Set up test database and other initial conditions."""
        self.db_path = "test_database"
        self.db = Database(self.db_path)
        # Setup for additional objects like Experiment and MeasurementResult if needed

    def tearDown(self):
        """Tear down test database and other cleanup."""
        self.db.close()  # Ensure the connection is closed
        os.remove(f"{self.db_path}.db")

    def test_experiment_storage(self):
        data_values = pl.DataFrame({"a":  np.arange(1, 1000), "b": np.arange(1,1000)}, schema={"a": pl.UInt64, "b": pl.UInt64})
        data = MeasurementResult(instrument="fake", values=data_values, measurement_type="fake", units="l")
        experiment = Experiment("Test", "test experiment")
        for _ in range(100):
            experiment.add_trial(data)
        

        output = experiment.data.to_arrow()

        attempt = pl.from_arrow(output)
        print(attempt)

        self.db.store_experiment("experiment", experiment)


        retrieved_data = self.db.retrieve_experiment("experiment")
        print(retrieved_data.data)

        # print(data)
        # print(retrieved_data)

        # assert retrieved_data == data
