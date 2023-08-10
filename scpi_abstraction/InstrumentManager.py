import time
from scpi_abstraction import InstrumentCollection

class InstrumentManager:
    def __init__(self):
        self.instrument_collection = InstrumentCollection()

    # Instrument management methods
    def add_instrument(self, name, instrument):
        # Add an instrument to the manager's collection
        self.instrument[name] = instrument

    def remove_instrument(self, name):
        # Remove an instrument from the manager's collection
        del self.instruments[name]

    def get_instrument(self, name):
        # Get an instrument from the manager's collection
        return self.instruments[name]

    def list_instruments(self):
        # List all instruments currently added to the manager
        print(self.instrument_collection)

    def disconnect_all_instruments(self):
        # Disconnect all instruments in the manager's collection
        for i in self.instruments:
            self.instruments[i].close()
        pass

    def is_all_instruments_connected(self):
        # Check if all instruments are connected
        pass

    def is_instrument_connected(self, name):
        # Check if a specific instrument is connected
        

    # Measurement methods
    def measure_voltage(self, voltage, channel=1):
        # Perform a voltage measurement
        pass

    def measure_current(self, current, channel=1):
        # Perform a current measurement
        pass

    def measure_power(self, power, channel=1):
        # Perform a power measurement
        pass

    def measure_eye_diagram(self, test_pattern, voltage=1.0, current=0.5, channel=1, eye_duration=0.1):
        power_supply = self.instrument_collection["power_supply"]
        oscilloscope = self.instrument_collection["oscilloscope"]
        pattern_generator = self.instrument_collection["pattern_generator"]

        power_supply.set_voltage(voltage, channel)
        power_supply.set_current(current, channel)
        power_supply.enable_output(channel)

        pattern_generator.load_pattern(test_pattern)
        pattern_generator.enable_output()

        oscilloscope.set_channel(channel)
        oscilloscope.start_measurement()

        # Wait for the test pattern to stabilize and the oscilloscope to capture data
        time.sleep(eye_duration)

        oscilloscope.stop_measurement()
        data = oscilloscope.get_measurement_data()

        power_supply.disable_output()
        pattern_generator.disable_output()

        #Data needs to be processed to generate Eye Diagram by frontend
        # eye_diagram = process_eye_data(data)
        return data
        # return eye_diagram

    def perform_s21_measurement(self, frequency, power_level, channel=1, measurement_time=0.1):
        signal_generator = self.instrument_collection["signal_generator"]
        vna = self.instrument_collection["vna"]

        signal_generator.set_frequency(frequency)
        signal_generator.set_power_level(power_level)
        signal_generator.enable_output()

        vna.set_channel(channel)
        vna.set_frequency(frequency)
        vna.set_power_level(power_level)
        vna.set_s_parameter("S21")
        vna.start_measurement()

        # Wait for the measurement to stabilize and complete
        time.sleep(measurement_time)

        s21_result = vna.get_measurement_data("S21")

        signal_generator.disable_output()
        vna.stop_measurement()

        return s21_result

        
    # Calibration methods
    def calibrate_power_supply(self):
        # Calibrate the power supply
        pass

    def calibrate_oscilloscope(self):
        # Calibrate the oscilloscope
        pass

    def calibrate_vna(self):
        # Calibrate the Vector Network Analyzer
        pass

    # Data handling methods
    def save_measurement_data(self, data, file_name):
        # Save measurement data to a file
        pass

    def load_measurement_data(self, file_name):
        # Load measurement data from a file
        pass

    # Instrument configuration methods
    def configure_power_supply(self, settings):
        # Configure power supply settings (e.g., voltage limits, current limits)
        pass

    def configure_oscilloscope(self, settings):
        # Configure oscilloscope settings (e.g., timebase, trigger settings)
        pass

    def configure_vna(self, settings):
        # Configure Vector Network Analyzer settings (e.g., frequency range, calibration)
        pass

    # Additional utility methods as needed
    def check_instrument_compatibility(self):
        # Check if the connected instruments are compatible for the planned measurements
        pass

    def perform_full_system_check(self):
        # Perform a comprehensive system check before starting measurements
        pass

    def report_system_status(self):
        # Generate a report on the status of connected instruments and overall system health
        pass
