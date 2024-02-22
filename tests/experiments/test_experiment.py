import unittest
from io import StringIO
from unittest.mock import patch
from pytestlab.experiments import Experiment, Trial, ExperimentParameter  # Adjust import path as needed

class TestExperimentClasses(unittest.TestCase):

    def setUp(self):
    # Set up common resources needed across tests
        self.experiment_name = "Test Experiment"
        self.description = "Test Description"
        self.param_name = "Temperature"
        self.param_units = "Celsius"
        self.notes = "Room temperature"
        self.data = [1, 2, 3]
        self.parameters = {self.param_name: "25"}

    def test_experiment_parameter_initialization(self):
        parameter = ExperimentParameter(self.param_name, self.param_units, self.notes)
        self.assertEqual(parameter.name, self.param_name)
        self.assertEqual(parameter.units, self.param_units)
        self.assertEqual(parameter.notes, self.notes)

    def test_experiment_parameter_str(self):
        parameter = ExperimentParameter(self.param_name, self.param_units)
        self.assertEqual(str(parameter), f"{self.param_name} ({self.param_units})")


    def test_trial_initialization_and_str(self):
        trial = Trial(self.data, self.parameters)
        expected_repr = f"Trial({{Temperature='25'}}\n{self.data})"
        self.assertEqual(repr(trial), expected_repr)
        self.assertEqual(str(trial), expected_repr)


    def test_experiment_initialization(self):
        experiment = Experiment(self.experiment_name, self.description)
        self.assertEqual(experiment.name, self.experiment_name)
        self.assertEqual(experiment.description, self.description)
        self.assertDictEqual(experiment.parameters, {})
        self.assertListEqual(experiment.trials, [])

    def test_add_parameter_and_str(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units, self.notes)
        self.assertIsInstance(experiment.parameters[self.param_name], ExperimentParameter)
        self.assertIn(self.param_name, str(experiment))

    def test_add_trial_success(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        experiment.add_trial(self.data, Temperature="25")
        self.assertEqual(len(experiment.trials), 1)

    def test_add_trial_incorrect_number_of_parameters(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        with self.assertRaises(ValueError):
            experiment.add_trial(self.data)

    def test_add_trial_undefined_parameter(self):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        with self.assertRaises(ValueError):
            experiment.add_trial(self.data, UndefinedParameter="100")

    @patch('sys.stdout', new_callable=StringIO)
    def test_list_trials(self, mock_stdout):
        experiment = Experiment(self.experiment_name)
        experiment.add_parameter(self.param_name, self.param_units)
        experiment.add_trial(self.data, Temperature="25")
        
        experiment.list_trials()
        # Check that something was printed to stdout
        self.assertGreater(len(mock_stdout.getvalue()), 0)
