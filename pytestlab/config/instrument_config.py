import json
from .config import Config

class InstrumentConfig(Config):
    # Base configuration class for all instruments
    def __init__(self,
                 manufacturer=None,
                    model=None,
                    device_type=None,
                    serial_number=None):
    
        if manufacturer is None or model is None:
            raise ValueError("Manufacturer, Model cannot be None")

        self.manufacturer = self._validate_parameter(manufacturer, str, "Manufacturer")
        self.model = self._validate_parameter(model, str, "Model")
        self.device_type = self._validate_parameter(device_type, str, "Device Type")
        self.serial_number = serial_number

    @classmethod
    def from_json_file(cls, file_path):
        """
        Create an Oscilloscope instance from a JSON file.

        Args:
            file_path (str): Path to the JSON file.

        Returns:
            Oscilloscope: An instance of Oscilloscope initialized with data from the JSON file.
        """
        with open(file_path, 'r') as f:
            data = json.load(f)
            return cls(**data)