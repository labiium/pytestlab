import unittest
import numpy as np
from pytestlab.experiments import MeasurementResult  # Adjust the import path as needed

class TestMeasurementResult(unittest.TestCase):

    def setUp(self):
        # Common setup that can be reused across tests
        self.values_array = np.array([1, 2, 3])
        self.values_matrix = np.array([[1, 2, 3], [4, 5, 6]])
        self.values_float64 = np.float64(3.14)
        self.instrument = "Test Instrument"
        self.units = "Test Units"
        self.measurement_type = "Test Type"
        self.sampling_rate = 1.0  # Hz


    def test_initialization_with_array(self):
        result = MeasurementResult(self.values_array, self.instrument, self.units, self.measurement_type)
        self.assertTrue(np.array_equal(result.values, self.values_array))

    def test_initialization_with_matrix(self):
        result = MeasurementResult(self.values_matrix, self.instrument, self.units, self.measurement_type)
        self.assertTrue(np.array_equal(result.values, self.values_matrix))

    def test_initialization_with_float64(self):
        result = MeasurementResult(self.values_float64, self.instrument, self.units, self.measurement_type)
        self.assertEqual(result.values, self.values_float64)


    def test_str_with_array(self):
        result = MeasurementResult(self.values_array, self.instrument, self.units, self.measurement_type)
        expected_str = '\n'.join([f"{val} {self.units}" for val in self.values_array])
        self.assertEqual(str(result), expected_str)

    def test_repr_with_array(self):
        result = MeasurementResult(self.values_array, self.instrument, self.units, self.measurement_type)
        expected_str = '\n'.join([f"{val} {self.units}" for val in self.values_array])
        self.assertEqual(repr(result), expected_str)


    def test_add_value_to_array(self):
        result = MeasurementResult(self.values_array, self.instrument, self.units, self.measurement_type)
        new_value = np.float64(4)
        result.add(new_value)
        self.assertTrue(np.array_equal(result.values, np.append(self.values_array, new_value)))

    def test_clear_values(self):
        result = MeasurementResult(self.values_array, self.instrument, self.units, self.measurement_type)
        result.clear()
        self.assertEqual(len(result.values), 0)

    def test_len_with_array(self):
        result = MeasurementResult(self.values_array, self.instrument, self.units, self.measurement_type)
        self.assertEqual(len(result), len(self.values_array))


    def test_perform_fft(self):
        time_signal = np.array([np.sin(2 * np.pi * 1 * t) for t in range(100)])
        result = MeasurementResult(time_signal, self.instrument, self.units, "VoltageTime", sampling_rate=100)
        fft_result = result.perform_fft()
        self.assertIsInstance(fft_result, MeasurementResult)
        self.assertEqual(fft_result.measurement_type, "FFT")
