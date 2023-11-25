import json
from .config import Config

class InstrumentConfig(Config):
    # Base configuration class for all instruments
    def __init__(self,
                 manufacturer=None,
                    model=None,
                    vendor_id=None,
                    product_id=None,
                    device_type=None):
    
        if manufacturer is None or model is None or vendor_id is None or product_id is None:
            raise ValueError("Manufacturer, Model, Serial, and Address cannot be None")
        
        vendor_id = int(vendor_id, 16)
        product_id = int(product_id, 16)

        self.manufacturer = self._validate_parameter(manufacturer, str, "Manufacturer")
        self.model = self._validate_parameter(model, str, "Model")
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.device_type = self._validate_parameter(device_type, str, "Device Type")

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