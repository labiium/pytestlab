from __future__ import annotations

from typing import Any, Dict, Type, Optional, Union

from .Oscilloscope import Oscilloscope
from .Multimeter import Multimeter
from .WaveformGenerator import WaveformGenerator
from .PowerSupply import PowerSupply
from .DCActiveLoad import DCActiveLoad
from .SpectrumAnalyser import SpectrumAnalyser
from .VectorNetworkAnalyser import VectorNetworkAnalyser
from .PowerMeter import PowerMeter
from .instrument import Instrument, AsyncInstrumentIO # Import AsyncInstrumentIO
from ..errors import InstrumentConfigurationError # Removed InstrumentNotFoundError as it's not used here
from ..config.loader import load_profile
from ..config.instrument_config import InstrumentConfig as PydanticInstrumentConfig # Base Pydantic config

# Import new backend classes
from .backends.async_visa_backend import AsyncVisaBackend
from .backends.sim_backend import SimBackend # Path has changed
from .backends.lamb import AsyncLambBackend # Class name changed from LambInstrument

import os
import yaml
import requests


class AutoInstrument:
    _instrument_mapping: Dict[str, Type[Instrument[Any]]] = { # Make Instrument generic type more specific
        'oscilloscope': Oscilloscope,
        'waveform_generator': WaveformGenerator,
        'power_supply': PowerSupply,
        'multimeter': Multimeter,
        "dc_active_load": DCActiveLoad,
        "vna": VectorNetworkAnalyser,
        "spectrum_analyzer": SpectrumAnalyser,
        "power_meter": PowerMeter,
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
    async def from_config(cls: Type[AutoInstrument],
                    config_source: Union[str, Dict[str, Any]],
                    *args,
                    serial_number: Optional[str] = None,
                    debug_mode: bool = False, # For logging during config load
                    simulate: Optional[bool] = None,
                    backend_type_hint: Optional[str] = None,
                    address_override: Optional[str] = None,
                    timeout_override_ms: Optional[int] = None
                   ) -> Instrument[Any]: # Returns an instance of a subclass of Instrument
        """
        Initializes an instrument from a configuration source (file path or dict).
        Handles backend instantiation based on explicit parameters and configuration.
        The Instrument class and its I/O methods are async.
        The caller is responsible for `await instrument.connect_backend()` after instantiation.
        """
        # Support serial_number as positional second argument
        if len(args) > 0 and isinstance(args[0], str):
            serial_number = args[0]

        config_data: Dict[str, Any]
        
        if isinstance(config_source, dict):
            config_data = config_source
        elif isinstance(config_source, str):
            try:
                config_data = cls.get_config_from_cdn(config_source)
                if debug_mode: print(f"Successfully loaded configuration for '{config_source}' from CDN.")
            except FileNotFoundError:
                try:
                    config_data = cls.get_config_from_local(config_source)
                    if debug_mode: print(f"Successfully loaded configuration for '{config_source}' from local.")
                except FileNotFoundError:
                    raise FileNotFoundError(f"Configuration '{config_source}' not found in CDN or local paths.")
        else:
            raise TypeError("config_source must be a file path (str) or a dict")

        config_model: PydanticInstrumentConfig = load_profile(config_data)

        if serial_number is not None and hasattr(config_model, 'serial_number'):
            config_model.serial_number = serial_number # type: ignore

        backend_instance: AsyncInstrumentIO

        # --- Determine Final Simulation Mode ---
        final_simulation_mode: bool
        if simulate is not None:
            final_simulation_mode = simulate
            if debug_mode: print(f"Simulation mode explicitly set to {final_simulation_mode} by argument.")
        else:
            env_simulate = os.getenv("PYTESTLAB_SIMULATE")
            if env_simulate is not None:
                final_simulation_mode = env_simulate.lower() in ('true', '1', 'yes')
                if debug_mode: print(f"Simulation mode set to {final_simulation_mode} by PYTESTLAB_SIMULATE environment variable.")
            else:
                # Default to False if not specified by argument or environment variable
                # Or, could check config_model for a 'simulate_by_default' field if that becomes a feature
                final_simulation_mode = False
                if debug_mode: print(f"Simulation mode defaulted to {final_simulation_mode} (no explicit argument or PYTESTLAB_SIMULATE).")

        # --- Determine Actual Address and Timeout ---
        actual_address: Optional[str]
        if address_override is not None:
            actual_address = address_override
            if debug_mode: print(f"Address overridden to '{actual_address}'.")
        else:
            actual_address = getattr(config_model, 'address', getattr(config_model, 'resource_name', None))
            if debug_mode: print(f"Address from config: '{actual_address}'.")

        actual_timeout: int
        default_communication_timeout_ms = 30000 # Default if not in override or config
        if timeout_override_ms is not None:
            actual_timeout = timeout_override_ms
            if debug_mode: print(f"Timeout overridden to {actual_timeout}ms.")
        else:
            # Assuming 'communication.timeout_ms' or 'communication_timeout_ms' might exist
            # Prefer 'communication_timeout_ms' as per previous logic if 'communication' object isn't standard
            timeout_from_config = getattr(config_model, 'communication_timeout_ms', None)
            if hasattr(config_model, 'communication') and hasattr(config_model.communication, 'timeout_ms'): # type: ignore
                 timeout_from_config = config_model.communication.timeout_ms # type: ignore
            
            if isinstance(timeout_from_config, int) and timeout_from_config > 0:
                actual_timeout = timeout_from_config
                if debug_mode: print(f"Timeout from config: {actual_timeout}ms.")
            else:
                actual_timeout = default_communication_timeout_ms
                if debug_mode: print(f"Warning: Invalid or missing timeout in config, using default {actual_timeout}ms.")
        
        if not isinstance(actual_timeout, int) or actual_timeout <= 0: # Final safety check
            actual_timeout = default_communication_timeout_ms
            if debug_mode: print(f"Warning: Corrected invalid timeout to default {actual_timeout}ms.")


        # --- Backend Instantiation ---
        if final_simulation_mode:
            device_model_str = getattr(config_model, 'model', 'GenericSimulatedModel')
            backend_instance = SimBackend(profile=config_model, device_model=device_model_str, timeout_ms=actual_timeout)
            if debug_mode: print(f"Using SimBackend for {device_model_str} with timeout {actual_timeout}ms.")
        else:
            if backend_type_hint:
                chosen_backend_type = backend_type_hint.lower()
                if debug_mode: print(f"Backend type hint provided: '{chosen_backend_type}'.")
            elif actual_address and "LAMB::" in actual_address.upper():
                chosen_backend_type = 'lamb'
                if debug_mode: print(f"Inferred backend type: 'lamb' from address '{actual_address}'.")
            elif actual_address:
                chosen_backend_type = 'visa'
                if debug_mode: print(f"Inferred backend type: 'visa' from address '{actual_address}'.")
            else:
                chosen_backend_type = 'lamb'
                if debug_mode: print(f"Defaulting backend type to 'lamb' (no address present).")

            if chosen_backend_type == 'visa':
                if actual_address is None:
                    raise InstrumentConfigurationError("Missing address/resource_name for VISA backend.")
                backend_instance = AsyncVisaBackend(address=actual_address, timeout_ms=actual_timeout)
                if debug_mode: print(f"Using AsyncVisaBackend for '{actual_address}' with timeout {actual_timeout}ms.")
            elif chosen_backend_type == 'lamb':
                lamb_server_url = getattr(config_model, 'lamb_url', 'http://lamb-server:8000')
                if actual_address:
                    backend_instance = AsyncLambBackend(address=actual_address, url=lamb_server_url, timeout_ms=actual_timeout)
                elif hasattr(config_model, "model") and hasattr(config_model, "serial_number"):
                    backend_instance = AsyncLambBackend(
                        address=None,
                        url=lamb_server_url,
                        timeout_ms=actual_timeout,
                        model_name=getattr(config_model, "model"),
                        serial_number=getattr(config_model, "serial_number")
                    )
                else:
                    raise InstrumentConfigurationError(
                        "Lamb backend requires either an address or both model and serial_number in the config."
                    )
                if debug_mode:
                    print(f"Using AsyncLambBackend for model='{getattr(config_model, 'model', None)}', serial='{getattr(config_model, 'serial_number', None)}' via '{lamb_server_url}' with timeout {actual_timeout}ms.")
            else:
                raise InstrumentConfigurationError(f"Unsupported backend_type '{chosen_backend_type}'.")
        
        # --- Instrument Driver Instantiation ---
        device_type_str: str = config_model.device_type
        instrument_class_to_init = cls._instrument_mapping.get(device_type_str.lower())
        
        if instrument_class_to_init is None:
            raise InstrumentConfigurationError(f"Unknown device_type: '{device_type_str}'. No registered instrument class.")
        
        # Instrument subclasses __init__ now expect 'config' and 'backend'.
        # (debug_mode and simulate are handled by AutoInstrument for backend choice)
        instrument = instrument_class_to_init(config=config_model, backend=backend_instance)
        
        if debug_mode:
            print(f"Instantiated {instrument_class_to_init.__name__} with {type(backend_instance).__name__}.")
            print("Note: Backend connection is not established by __init__. Call 'await instrument.connect_backend()' explicitly.")
            
        return instrument

    @classmethod
    def register_instrument(cls: Type[AutoInstrument], instrument_type: str, instrument_class: Type[Instrument[Any]]) -> None:
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