from .Oscilloscope import Oscilloscope
from .Multimeter import Multimeter
from .WaveformGenerator import WaveformGenerator
from .PowerSupply import PowerSupply
from .DCActiveLoad import DCActiveLoad
from .instrument import Instrument
from pytestlab.errors import InstrumentConfigurationError
import os
import yaml
import requests

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
    def get_config_from_cdn(cls, identifier):
        """
        Fetches the configuration from the CDN with caching.
        
        Args:
            identifier (str): The identifier of the configuration to fetch.
            
        Returns:
            dict: The loaded configuration data.
            
        Raises:
            FileNotFoundError: If the configuration file is not found on the CDN.
        """
        import pytestlab as ptl
        
        # Create cache directory if it doesn't exist
        cache_dir = os.path.join(os.path.dirname(ptl.__file__), "cache", "configs")
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_file = os.path.join(cache_dir, f"{identifier}.yaml")
        
        # Check if cache exists
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    return yaml.safe_load(f.read())
            except Exception:
                # If cache reading fails, continue to fetch from CDN
                pass
        
        # Fetch from CDN if cache miss or cache read failed
        url = f"https://pytestlab.org/config/{identifier}.yaml"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Cache the content
                with open(cache_file, 'w') as f:
                    f.write(response.text)
                
                return yaml.safe_load(response.text)
            else:
                raise FileNotFoundError(f"Configuration file not found at {url}")
        except requests.RequestException as e:
            raise FileNotFoundError(f"Failed to fetch configuration from CDN: {str(e)}")

    @classmethod
    def get_config_from_local(cls, identifier, normalized_identifier=None):
        """
        Attempts to load configuration from local file paths.
        
        Args:
            identifier (str): The identifier or path of the configuration file.
            normalized_identifier (str, optional): Pre-normalized identifier.
            
        Returns:
            dict: The loaded configuration data.
            
        Raises:
            FileNotFoundError: If no configuration file is found.
        """
        import pytestlab as ptl
        
        if normalized_identifier is None:
            normalized_identifier = os.path.normpath(identifier)
        
        # Getting the directory of the pytestlab module
        current_file_directory = os.path.dirname(ptl.__file__)
        
        # Try loading from profiles directory first
        preset_path = os.path.join(current_file_directory, "profiles", normalized_identifier + '.yaml')
        
        if os.path.exists(preset_path):
            with open(preset_path, 'r') as file:
                return yaml.safe_load(file)
        
        # If not found in presets, check if it's a user-provided file path
        elif os.path.exists(identifier) and (identifier.endswith('.yaml') or identifier.endswith('.json')):
            with open(identifier, 'r') as file:
                return yaml.safe_load(file)
        
        raise FileNotFoundError(f"No configuration found for identifier '{identifier}'")

    @classmethod
    def from_config(cls, identifier: str, serial_number=None, debug_mode=False) -> Instrument:
        """
        Initializes an instrument from a configuration.
        
        The method tries to obtain the configuration in the following order:
        1. From the CDN (pytestlab.org/config/)
        2. From the local profiles directory or user-provided file path
        
        Args:
            identifier (str): The identifier of the configuration or path to a config file.
            serial_number (str, optional): The serial number of the instrument. Defaults to None.
            debug_mode (bool, optional): Whether to print debug messages. Defaults to False.
            
        Returns:
            Instrument: The initialized instrument instance.
            
        Raises:
            FileNotFoundError: If no configuration could be found.
            InstrumentConfigurationError: If the instrument type is unknown.
        """
        normalized_identifier = os.path.normpath(identifier)
        
        # Try to get the config from CDN first
        try:
            config_data = cls.get_config_from_cdn(normalized_identifier)
        except FileNotFoundError:
            # If CDN fails, try local paths
            try:
                config_data = cls.get_config_from_local(identifier, normalized_identifier)
            except FileNotFoundError as e:
                raise FileNotFoundError(f"No configuration found for '{identifier}'. Tried both CDN and local paths.") from e
        
        # Add serial number to config if provided
        config_data["serial_number"] = config_data.get("serial_number", None)
        
        # Initialize the appropriate instrument type
        if "device_type" not in config_data:
            raise InstrumentConfigurationError(f"Missing 'device_type' in configuration for '{identifier}'")
        
        device_type = config_data["device_type"]
        if device_type not in cls._instrument_mapping:
            raise InstrumentConfigurationError(f"Unknown instrument type: {device_type}")
        
        return cls._instrument_mapping[device_type].from_config(config=config_data, debug_mode=debug_mode)

    @classmethod
    def register_instrument(cls, instrument_type, instrument_class) -> None:
        if instrument_type in cls._instrument_mapping:
            raise InstrumentConfigurationError(f"Instrument type '{instrument_type}' already registered")
        cls._instrument_mapping[instrument_type] = instrument_class