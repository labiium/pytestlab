import unittest
from scpi_abstraction.instrument import SCPIInstrument, SCPIConnectionError, SCPICommunicationError

class TestSCPIInstrument(unittest.TestCase):
    def setUp(self):
        # Use a VISA resource string for a simulated instrument (replace with your actual instrument resource)
        self.visa_resource = "SIM::INSTR"
        self.instrument = SCPIInstrument(self.visa_resource)

    def tearDown(self):
        self.instrument.close()

    def test_connection(self):
        self.assertIsInstance(self.instrument, SCPIInstrument)
        self.assertEqual(self.instrument.visa_resource, self.visa_resource)

    def test_reset(self):
        self.instrument.reset()

    def test_send_command(self):
        self.instrument._send_command("*IDN?")

    def test_query(self):
        response = self.instrument._query("*IDN?")
        self.assertIsInstance(response, str)

    # Add more test cases to cover other functionalities of the SCPIInstrument class

if __name__ == "__main__":
    unittest.main()
