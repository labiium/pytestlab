from __future__ import annotations

import time
from typing import Any, Optional

from pytestlab import InstrumentCollection

class InstrumentManager:
    def __init__(self) -> None:
        self.instrument_collection: InstrumentCollection = InstrumentCollection()
        self.instruments: dict[str, Any] = {} # Assuming instruments are stored in a dict

    # Instrument management methods
    def add_instrument(self, name: str, instrument: Any) -> None:
        # Add an instrument to the manager's collection
        self.instruments[name] = instrument

    def remove_instrument(self, name: str) -> None:
        # Remove an instrument from the manager's collection
        del self.instruments[name]

    def get_instrument(self, name: str) -> Any:
        # Get an instrument from the manager's collection
        return self.instruments[name]

    def list_instruments(self) -> None:
        # List all instruments currently added to the manager
        print(self.instrument_collection) # Or print(self.instruments.keys())

    def disconnect_all_instruments(self) -> None:
        # Disconnect all instruments in the manager's collection
        for i in self.instruments:
            self.instruments[i].close()
        pass

    def is_all_instruments_connected(self) -> Optional[bool]: # Assuming it might return None or bool
        # Check if all instruments are connected
        pass

    def is_instrument_connected(self, name: str) -> Optional[bool]: # Assuming it might return None or bool
        # Check if a specific instrument is connected
        pass
    # Measurement methods
    def measure_voltage(self, voltage: float, channel: int = 1) -> None:
        # Perform a voltage measurement
        pass

    def measure_current(self, current: float, channel: int = 1) -> None:
        # Perform a current measurement
        pass

    def measure_power(self, power: float, channel: int = 1) -> None:
        # Perform a power measurement
        pass

    def measure_eye_diagram(self, test_pattern: Any, voltage: float = 1.0, current: float = 0.5, channel: int = 1, eye_duration: float = 0.1) -> Any:
        power_supply: Any = self.instrument_collection["power_supply"]
        oscilloscope: Any = self.instrument_collection["oscilloscope"]
        pattern_generator: Any = self.instrument_collection["pattern_generator"]

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
        data: Any = oscilloscope.get_measurement_data()

        power_supply.disable_output()
        pattern_generator.disable_output()

        #Data needs to be processed to generate Eye Diagram by frontend
        # eye_diagram = process_eye_data(data)
        return data
        # return eye_diagram

    def perform_s21_measurement(self, frequency: float, power_level: float, channel: int = 1, measurement_time: float = 0.1) -> Any:
        signal_generator: Any = self.instrument_collection["signal_generator"]
        vna: Any = self.instrument_collection["vna"]

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

        s21_result: Any = vna.get_measurement_data("S21")

        signal_generator.disable_output()
        vna.stop_measurement()

        return s21_result

    
    # Calibration methods
    def calibrate_power_supply(self) -> None:
        # Calibrate the power supply
        pass

    def calibrate_oscilloscope(self) -> None:
        # Calibrate the oscilloscope
        pass

    def calibrate_vna(self) -> None:
        # Calibrate the Vector Network Analyzer
        pass

    # Data handling methods
    def save_measurement_data(self, data: Any, file_name: str) -> None:
        # Save measurement data to a file
        pass

    def load_measurement_data(self, file_name: str) -> Any:
        # Load measurement data from a file
        pass

    # Instrument configuration methods
    def configure_power_supply(self, settings: Any) -> None:
        # Configure power supply settings (e.g., voltage limits, current limits)
        pass

    def configure_oscilloscope(self, settings: Any) -> None:
        # Configure oscilloscope settings (e.g., timebase, trigger settings)
        pass

    def configure_vna(self, settings: Any) -> None:
        # Configure Vector Network Analyzer settings (e.g., frequency range, calibration)
        pass

    # Additional utility methods as needed
    def check_instrument_compatibility(self) -> None: # Or Optional[bool] if it returns a status
        # Check if the connected instruments are compatible for the planned measurements
        pass

    def perform_full_system_check(self) -> None: # Or Optional[bool]
        # Perform a comprehensive system check before starting measurements
        pass

    def report_system_status(self) -> None: # Or str if it returns a report string
        # Generate a report on the status of connected instruments and overall system health
        pass
