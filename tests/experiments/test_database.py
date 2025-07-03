import unittest
import os
import numpy as np
import polars as pl
from datetime import datetime
from pytestlab.experiments import Database, MeasurementResult, Experiment

class TestDatabase(unittest.TestCase):
    def setUp(self):
        """Set up test database and other initial conditions."""
        self.db_path = "test_database"
        self.db = Database(self.db_path)

    def tearDown(self):
        """Tear down test database and other cleanup."""
        self.db.close()
        if os.path.exists(f"{self.db_path}.db"):
            os.remove(f"{self.db_path}.db")

    def test_store_and_retrieve_measurement(self):
        """Test storing and retrieving a MeasurementResult."""
        values = pl.DataFrame({"a": np.arange(5)}, schema={"a": pl.Int64})
        meas = MeasurementResult(
            instrument="DMM",
            values=values,
            measurement_type="voltage",
            units="V",
            timestamp=datetime.now().timestamp()
        )
        codename = self.db.store_measurement(None, meas)
        retrieved = self.db.retrieve_measurement(codename)
        self.assertEqual(retrieved.instrument, meas.instrument)
        self.assertEqual(retrieved.measurement_type, meas.measurement_type)
        self.assertEqual(retrieved.units, meas.units)
        self.assertTrue(np.allclose(retrieved.values["a"].to_numpy(), values["a"].to_numpy()))

    def test_list_and_search_measurements(self):
        """Test listing and searching for measurements."""
        values = pl.DataFrame({"b": np.arange(3)}, schema={"b": pl.Int64})
        meas = MeasurementResult(
            instrument="Scope",
            values=values,
            measurement_type="current",
            units="A",
            timestamp=datetime.now().timestamp()
        )
        codename = self.db.store_measurement(None, meas)
        all_codes = self.db.list_measurements()
        self.assertIn(codename, all_codes)
        results = self.db.search_measurements("Scope")
        self.assertTrue(any(r["codename"] == codename for r in results))

    def test_experiment_storage(self):
        """Test storing and retrieving an Experiment."""
        experiment = Experiment("Test", "test experiment")
        data_values = pl.DataFrame({"a": np.arange(1, 1000), "b": np.arange(1, 1000)}, schema={"a": pl.UInt64, "b": pl.UInt64})
        data = MeasurementResult(instrument="fake", values=data_values, measurement_type="fake", units="l")
        experiment.add_trial(data)
        codename = self.db.store_experiment(None, experiment)
        retrieved = self.db.retrieve_experiment(codename)
        self.assertEqual(retrieved.name, experiment.name)
        self.assertEqual(retrieved.description, experiment.description)
        self.assertEqual(retrieved.data.schema, experiment.data.schema)
        self.assertEqual(len(retrieved), len(experiment))

    def test_list_and_search_experiments(self):
        """Test listing and searching for experiments."""
        experiment = Experiment("SearchExp", "desc")
        experiment.add_parameter("Current", "A")
        experiment.add_trial({"Current": 2.34}, Current=2.34)
        codename = self.db.store_experiment(None, experiment)
        all_codes = self.db.list_experiments()
        self.assertIn(codename, all_codes)
        results = self.db.search_experiments("SearchExp")
        self.assertTrue(any(r["codename"] == codename for r in results))

    def test_stats_and_vacuum(self):
        """Test database stats and vacuuming."""
        experiment = Experiment("StatsExp", "desc")
        experiment.add_parameter("X", "unit")
        experiment.add_trial({"X": 1}, X=1)
        self.db.store_experiment(None, experiment)
        stats = self.db.get_stats()
        self.assertGreaterEqual(stats["experiments"], 1)
        self.db.vacuum()  # Should not raise

if __name__ == "__main__":
    unittest.main()
