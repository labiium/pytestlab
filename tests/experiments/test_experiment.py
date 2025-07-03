import unittest
import polars as pl
from pytestlab.experiments import Experiment, ExperimentParameter
import numpy as np
import tempfile
import os

class TestExperiment(unittest.TestCase):
    def setUp(self):
        # Set up common resources needed across tests
        self.experiment_name = "Test Experiment"
        self.description = "Test Description"
        self.param_name = "Temperature"
        self.param_units = "Celsius"
        self.notes = "Room temperature"
        self.data = [1, 2, 3]

    def test_experiment_parameter_initialization(self):
        parameter = ExperimentParameter(self.param_name, self.param_units, self.notes)
        self.assertEqual(parameter.name, self.param_name)
        self.assertEqual(parameter.units, self.param_units)
        self.assertEqual(parameter.notes, self.notes)

    def test_experiment_parameter_str(self):
        parameter = ExperimentParameter(self.param_name, self.param_units)
        self.assertEqual(str(parameter), f"{self.param_name} ({self.param_units})")

    def test_experiment_initialization(self):
        experiment = Experiment(self.experiment_name, self.description)
        self.assertEqual(experiment.name, self.experiment_name)
        self.assertEqual(experiment.description, self.description)
        self.assertDictEqual(experiment.parameters, {})
        self.assertTrue(experiment.data.is_empty())

    def test_add_parameter_and_str(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units, self.notes)
        self.assertIsInstance(experiment.parameters[self.param_name], ExperimentParameter)
        self.assertIn(self.param_name, str(experiment))

    def test_add_trial_with_dataframe(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        df = pl.DataFrame({"value": [1, 2, 3]})
        experiment.add_trial(df, Temperature=25)
        self.assertEqual(len(experiment), 3)
        self.assertIn("Temperature", experiment.data.columns)

    def test_add_trial_with_dict(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        trial_dict = {"value": 42}
        experiment.add_trial(trial_dict, Temperature=30)
        self.assertEqual(len(experiment), 1)
        self.assertIn("Temperature", experiment.data.columns)

    def test_add_trial_with_list(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        trial_list = [{"value": 1}, {"value": 2}]
        experiment.add_trial(trial_list, Temperature=22)
        self.assertEqual(len(experiment), 2)
        self.assertIn("Temperature", experiment.data.columns)

    def test_add_trial_undefined_parameter(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        with self.assertRaises(ValueError):
            experiment.add_trial({"value": 1}, UndefinedParam=100)

    def test_add_trial_schema_incompatibility(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        experiment.add_trial({"value": 1}, Temperature=25)
        # Now try to add a trial with a different schema
        with self.assertRaises(ValueError):
            experiment.add_trial({"other": 2}, Temperature=25)

    def test_iter_and_len(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        experiment.add_trial({"value": 1}, Temperature=25)
        rows = list(iter(experiment))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(experiment), 1)

    def test_str_and_list_trials(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        experiment.add_trial({"value": 1}, Temperature=25)
        s = str(experiment)
        self.assertIn(self.experiment_name, s)
        self.assertIn("Trial Data", s)
        # list_trials just prints, so we check it doesn't error
        experiment.list_trials()

    def test_save_parquet(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        experiment.add_trial({"value": 1}, Temperature=25)
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            experiment.save_parquet(tmp.name)
            self.assertTrue(os.path.exists(tmp.name))
        os.remove(tmp.name)

if __name__ == "__main__":
    unittest.main()
