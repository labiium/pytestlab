import unittest
import os
import numpy as np
from datetime import datetime
# Import your classes here, adjust the import paths as needed
from pytestlab.experiments import Database, MeasurementResult, Experiment

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

    def test_database_initialization_creates_tables(self):
        """Ensure tables are created upon initialization."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        self.assertIn(('experiments',), tables)
        self.assertIn(('experiment_parameters',), tables)
        self.assertIn(('trial_parameters',), tables)
        self.assertIn(('trials',), tables)
        self.assertIn(('instruments',), tables)
        self.assertIn(('measurements',), tables)
        conn.close()

    def test_store_and_retrieve_measurement(self):
        """Test storing and retrieving a measurement."""
        codename = "test_measurement"
        values = np.array([1.0, 2.0, 3.0])
        instrument_name = "test_instrument"
        units = "test_units"
        measurement_type = "test_type"
        measurement_result = MeasurementResult(values=values, instrument=instrument_name, units=units, measurement_type=measurement_type)
        
        # Store the measurement
        self.db.store_measurement(codename, measurement_result)
        
        # Retrieve the measurement
        retrieved = self.db.retrieve_measurement(codename)
        self.assertEqual(retrieved.instrument, instrument_name)
        self.assertTrue(np.array_equal(retrieved.values, values))
        self.assertEqual(retrieved.units, units)
        self.assertEqual(retrieved.measurement_type, measurement_type)


    def test_store_and_retrieve_experiment(self):
        """Test storing and retrieving an experiment with its measurements."""
        codename = "test_experiment"
        experiment_name = "Test Experiment"
        experiment_description = "A test experiment description"
        experiment = Experiment(experiment_name, experiment_description)
        
        # Add parameters and trials to the experiment as needed
        # experiment.add_parameter(...)
        # experiment.add_trial(...)

        # Store the experiment
        self.db.store_experiment(codename, experiment)
        
        # Retrieve the experiment
        retrieved = self.db.retrieve_experiment(codename)
        self.assertEqual(retrieved.name, experiment_name)
        self.assertEqual(retrieved.description, experiment_description)
        # Further checks for parameters and trials can be added here
        

