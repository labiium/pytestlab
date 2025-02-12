from .Oscilloscope import Oscilloscope
from .Multimeter import Multimeter
from .WaveformGenerator import WaveformGenerator
from .PowerSupply import PowerSupply
from .DCActiveLoad import DCActiveLoad
from .instrument import Instrument
from pytestlab.errors import InstrumentConfigurationError
import os
import yaml

class AutoInstrument:
    _instrument_mapping = {
        'oscilloscope': Oscilloscope,
        'waveform_generator': WaveformGenerator,
        'power_supply': PowerSupply,
        'multimeter': Multimeter,
        "dc_active_load": DCActiveLoad
    }

    @classmethod
    def from_type(cls, instrument_type, *args, **kwargs) -> Instrument:
        """
        Initializes an instrument from a type.
        
        Args:
        instrument_type (str): The type of the instrument to initialize.
        *args: Arguments to pass to the instrument's constructor.
        **kwargs: Keyword arguments to pass to the instrument's constructor.
        """
        if instrument_type in cls._instrument_mapping:
            return cls._instrument_mapping[instrument_type](*args, **kwargs)
        else:
            raise InstrumentConfigurationError(f"Unknown instrument type: {instrument_type}")
        
    
    @classmethod
    def from_config(cls, identifier: str, serial_number=None, debug_mode=False) -> Instrument:
        """
        Initializes an instrument from a preset.
        
        Args:
        identifier (str): The identifier of the preset. This can either be the name of a preset file in the pytestlab/instruments/profiles directory, or a path to a user-provided preset file.
        debug_mode (bool, optional): Whether to print debug messages. Defaults to False.
        """
        import pytestlab as ptl

        # Getting the directory of the pytestlab module
        current_file_directory = os.path.dirname(ptl.__file__)

        # Normalize the identifier to ensure correct path separators
        normalized_identifier = os.path.normpath(identifier)

        # Constructing the absolute path for the preset file
        preset_path = os.path.join(current_file_directory, "profiles", normalized_identifier + '.yaml')

        # Debugging print statements
        # print("current_file_directory:", os.path.abspath(current_file_directory))
        # print("preset_path:", preset_path)
        
        if os.path.exists(preset_path):
            with open(preset_path, 'r') as file:
                config_data = yaml.safe_load(file)
                config_data["serial_number"] = serial_number
                return cls._instrument_mapping[config_data["device_type"]].from_config(config=config_data, debug_mode=debug_mode)
        
        # If not found in presets, check if it's a user-provided file path
        elif os.path.exists(identifier) and identifier.endswith('.json'):
            with open(identifier, 'r') as file:
                config_data = yaml.safe_load(file)
                config_data["serial_number"] = serial_number
            return cls._instrument_mapping[config_data["device_type"]].from_config(config=config_data, debug_mode=debug_mode)

        else:
            raise FileNotFoundError(f"No preset found for identifier '{identifier}'")
        
    @classmethod
    def register_instrument(cls, instrument_type, instrument_class) -> None:
        if instrument_type in cls._instrument_mapping:
            raise InstrumentConfigurationError(f"Instrument type '{instrument_type}' already registered")
        cls._instrument_mapping[instrument_type] = instrument_class