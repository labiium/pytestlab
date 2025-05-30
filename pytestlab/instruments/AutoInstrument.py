from __future__ import annotations

from typing import Any, Dict, Type, Optional
from .Oscilloscope import Oscilloscope
from .Multimeter import Multimeter
from .WaveformGenerator import WaveformGenerator
from .PowerSupply import PowerSupply
from .DCActiveLoad import DCActiveLoad
from .instrument import Instrument
from pytestlab.errors import InstrumentConfigurationError
from ..config.loader import load_config
import os
import yaml
import requests

class AutoInstrument:
    _instrument_mapping: Dict[str, Type[Instrument]] = {
        'oscilloscope': Oscilloscope,
        'waveform_generator': WaveformGenerator,
        'power_supply': PowerSupply,
        'multimeter': Multimeter,
        "dc_active_load": DCActiveLoad
    }

    @classmethod
    def from_type(cls: Type[AutoInstrument], instrument_type: str, *args: Any, **kwargs: Any) -> Instrument:
        """
        Initializes an instrument from a type.
        
        Args:
        instrument_type (str): The type of the instrument to initialize.
        *args: Arguments to pass to the instrument's constructor.
        **kwargs: Keyword arguments to pass to the instrument's constructor.
        """
        instrument_class = cls._instrument_mapping.get(instrument_type.lower())
        if instrument_class:
            return instrument_class(*args, **kwargs) # type: ignore
        else:
            raise InstrumentConfigurationError(f"Unknown instrument type: {instrument_type}")
    
    @classmethod
    def get_config_from_cdn(cls: Type[AutoInstrument], identifier: str) -> Dict[str, Any]:
        """
        Fetches the configuration from the CDN with caching.
        
        Args:
            identifier (str): The identifier of the configuration to fetch.
            
        Returns:
            dict: The loaded configuration data.
            
        Raises:
            FileNotFoundError: If the configuration file is not found on the CDN or fetch fails.
            InstrumentConfigurationError: If the fetched config is not a valid dictionary.
        """
        import pytestlab as ptl 
        
        cache_dir = os.path.join(os.path.dirname(ptl.__file__), "cache", "configs")
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_file = os.path.join(cache_dir, f"{identifier}.yaml")
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    loaded_config = yaml.safe_load(f.read())
                    if not isinstance(loaded_config, dict):
                        os.remove(cache_file) 
                        raise InstrumentConfigurationError("Cached config is not a valid dictionary.")
                    return loaded_config
            except Exception as e:
                print(f"Cache read failed for {identifier}: {e}. Fetching from CDN.")
                if os.path.exists(cache_file):
                    try:
                        os.remove(cache_file)
                    except OSError:
                        pass 
        
        url = f"https://pytestlab.org/config/{identifier}.yaml"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status() 
            
            config_text = response.text
            loaded_config = yaml.safe_load(config_text)
            if not isinstance(loaded_config, dict):
                raise InstrumentConfigurationError(f"CDN config for {identifier} is not a valid dictionary.")

            with open(cache_file, 'w') as f:
                f.write(config_text)
            
            return loaded_config
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 404:
                 raise FileNotFoundError(f"Configuration file not found at {url} (HTTP 404).") from http_err
            else:
                 raise FileNotFoundError(f"Failed to fetch configuration from CDN ({url}): HTTP {http_err.response.status_code}") from http_err
        except requests.exceptions.RequestException as e:
            raise FileNotFoundError(f"Failed to fetch configuration from CDN ({url}): {str(e)}") from e
        except yaml.YAMLError as ye:
            raise InstrumentConfigurationError(f"Error parsing YAML from CDN for {identifier}: {ye}") from ye


    @classmethod
    def get_config_from_local(cls: Type[AutoInstrument], identifier: str, normalized_identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Attempts to load configuration from local file paths.
        
        Args:
            identifier (str): The identifier or path of the configuration file.
            normalized_identifier (str, optional): Pre-normalized identifier.
            
        Returns:
            dict: The loaded configuration data.
            
        Raises:
            FileNotFoundError: If no configuration file is found.
            InstrumentConfigurationError: If loaded YAML is not a dictionary or parsing fails.
        """
        import pytestlab as ptl 
        
        norm_id = normalized_identifier if normalized_identifier is not None else os.path.normpath(identifier)
        
        current_file_directory = os.path.dirname(ptl.__file__)
        preset_path = os.path.join(current_file_directory, "profiles", norm_id + '.yaml')
        
        path_to_try: Optional[str] = None
        if os.path.exists(preset_path):
            path_to_try = preset_path
        elif os.path.exists(identifier) and (identifier.endswith('.yaml') or identifier.endswith('.json')):
            path_to_try = identifier
        
        if path_to_try:
            try:
                with open(path_to_try, 'r') as file:
                    loaded_config = yaml.safe_load(file)
                    if not isinstance(loaded_config, dict):
                        raise InstrumentConfigurationError(f"Local config file '{path_to_try}' did not load as a dictionary.")
                    return loaded_config
            except yaml.YAMLError as ye:
                raise InstrumentConfigurationError(f"Error parsing YAML from local file '{path_to_try}': {ye}") from ye
            except Exception as e: 
                raise FileNotFoundError(f"Error reading local config file '{path_to_try}': {e}") from e

        raise FileNotFoundError(f"No configuration found for identifier '{identifier}' in local paths.")

    @classmethod
    def from_config(cls: Type[AutoInstrument], config_source: str | Dict, serial_number: Optional[str] = None, debug_mode: bool = False, simulate: bool = False) -> Instrument:
        """
        Initializes an instrument from a configuration source (file path or dict).
        Tries CDN first, then falls back to local if config_source is a string identifier.
        Allows enabling simulation mode.
        """
        config_data: Dict[str, Any]
        
        if isinstance(config_source, dict):
            # If config_source is already a dict, use it directly
            config_data = config_source
        elif isinstance(config_source, str):
            # If config_source is a string, try CDN first, then local fallback
            try:
                # First, try to get configuration from CDN
                config_data = cls.get_config_from_cdn(config_source)
                if debug_mode:
                    print(f"Successfully loaded configuration for '{config_source}' from CDN.")
            except FileNotFoundError:
                # If CDN fails, fall back to local
                try:
                    config_data = cls.get_config_from_local(config_source)
                    if debug_mode:
                        print(f"Successfully loaded configuration for '{config_source}' from local.")
                except FileNotFoundError:
                    # If both CDN and local fail, raise an informative error
                    raise FileNotFoundError(f"Configuration '{config_source}' not found in CDN or local paths.")
        else:
            raise TypeError("config_source must be a file path (str) or a dict")

        # Load the configuration using the new Pydantic-based loader
        # load_config returns a specific Pydantic model instance (e.g., OscilloscopeConfig, PowerSupplyConfig)
        # which is a subclass of InstrumentConfig.
        config_model = load_config(config_data)

        # Override serial number if provided in arguments.
        # The Pydantic model InstrumentConfig (base for all specific instrument configs)
        # has a 'serial_number' field.
        if serial_number is not None:
            # Ensure that config_model is not None and has the serial_number attribute
            if hasattr(config_model, 'serial_number'):
                config_model.serial_number = serial_number
            else:
                # This case should ideally not happen if load_config returns a valid InstrumentConfig model
                # or one of its Pydantic subclasses that includes serial_number.
                # Handle appropriately, e.g., log a warning or raise an error if serial_number is critical.
                # For now, we assume InstrumentConfig and its Pydantic versions will have serial_number.
                pass # Or log a warning: print(f"Warning: config_model of type {type(config_model)} does not have serial_number attribute.")

        
        # device_type is a required string field in the base InstrumentConfig Pydantic model,
        # so its presence and type are guaranteed by successful validation in load_config.
        device_type_str: str = config_model.device_type
        
        instrument_class_to_init = cls._instrument_mapping.get(device_type_str.lower())
        
        # Although load_config checks device_type against its registry of Pydantic models,
        # this check ensures the device_type maps to an actual instrument driver class.
        if instrument_class_to_init is None:
            raise InstrumentConfigurationError(f"Unknown instrument type: '{device_type_str}'. No registered instrument class.")
        
        # Instantiate the specific instrument class directly, passing the Pydantic config model,
        # debug_mode, and the simulate flag.
        # This requires that the __init__ method of Instrument (and its subclasses)
        # accepts 'config', 'debug_mode', and 'simulate' parameters.
        # The Instrument.__init__ has been updated to accept 'simulate'.
        return instrument_class_to_init(config=config_model, debug_mode=debug_mode, simulate=simulate)

    @classmethod
    def register_instrument(cls: Type[AutoInstrument], instrument_type: str, instrument_class: Type[Instrument]) -> None:
        """
        Registers a new instrument type and its corresponding class.
        Args:
            instrument_type (str): The string identifier for the instrument type.
            instrument_class (Type[Instrument]): The class to instantiate for this type.
        Raises:
            InstrumentConfigurationError: If the instrument type is already registered or class is not Instrument subclass.
        """
        type_key = instrument_type.lower() 
        if type_key in cls._instrument_mapping:
            raise InstrumentConfigurationError(f"Instrument type '{instrument_type}' already registered with class {cls._instrument_mapping[type_key].__name__}")
        if not issubclass(instrument_class, Instrument):
             raise InstrumentConfigurationError(f"Cannot register class {instrument_class.__name__}. It must be a subclass of Instrument.")
        cls._instrument_mapping[type_key] = instrument_class
        # Consider using a logger if available, instead of print
        print(f"Instrument type '{instrument_type}' registered with class {instrument_class.__name__}.")