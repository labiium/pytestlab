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
from .VirtualInstrument import VirtualInstrument
from .instrument import Instrument, InstrumentIO # Import InstrumentIO
from ..errors import InstrumentConfigurationError # Removed InstrumentNotFoundError as it's not used here
from ..config.loader import load_profile
from ..config.instrument_config import InstrumentConfig as PydanticInstrumentConfig # Base Pydantic config

# Import new backend classes
from .backends.async_visa_backend import AsyncVisaBackend
from .backends.sim_backend import SimBackend
from .backends.lamb import AsyncLambBackend  # Class name changed from LambInstrument
from .backends.replay_backend import ReplayBackend # Add this import

import os
import warnings
import yaml
import httpx
# import aiofiles  # Removed for synchronous operation
import tempfile


class AutoInstrument:
    """A factory class for creating and configuring instrument objects.

    This class provides a high-level interface to instantiate various types of
    instruments based on configuration files, instrument types, or other
    identifiers. It handles the complexities of locating configuration data,
    selecting the appropriate communication backend (e.g., VISA, simulation),
    and initializing the correct instrument driver.

    The primary methods are `from_config` for creating an instrument from a
    configuration source and `from_type` for creating one based on a generic
    instrument category.
    """
    _instrument_mapping: Dict[str, Type[Instrument[Any]]] = { # Make Instrument generic type more specific
        'oscilloscope': Oscilloscope,
        'waveform_generator': WaveformGenerator,
        'power_supply': PowerSupply,
        'multimeter': Multimeter,
        "dc_active_load": DCActiveLoad,
        "vna": VectorNetworkAnalyser,
        "spectrum_analyzer": SpectrumAnalyser,
        "power_meter": PowerMeter,
        "virtual_instrument": VirtualInstrument,
    }

    @classmethod
    def from_type(cls: Type[AutoInstrument], instrument_type: str, *args: Any, **kwargs: Any) -> Instrument:
        """Initializes a specific instrument driver based on its type string.

        This factory method uses a mapping to find the appropriate instrument class
        for a given `instrument_type` string (e.g., 'oscilloscope') and passes
        any additional arguments to its constructor.

        Args:
            instrument_type: The type of the instrument to initialize.
            *args: Positional arguments to pass to the instrument's constructor.
            **kwargs: Keyword arguments to pass to the instrument's constructor.

        Returns:
            An instance of a specific Instrument subclass.

        Raises:
            InstrumentConfigurationError: If the instrument_type is not recognized.
        """
        instrument_class = cls._instrument_mapping.get(instrument_type.lower())
        if instrument_class:
            return instrument_class(*args, **kwargs) # type: ignore
        else:
            raise InstrumentConfigurationError(
                instrument_type, f"Unknown instrument type: {instrument_type}"
            )

    @classmethod
    def get_config_from_cdn(cls: Type[AutoInstrument], identifier: str) -> Dict[str, Any]:
        """Fetches an instrument configuration from a CDN with local caching.

        This method attempts to retrieve a configuration file from a predefined
        CDN URL. For efficiency, it caches the configuration locally. If a cached
        version is available, it's used directly. Otherwise, the file is
        downloaded, cached for future use, and then returned.

        Args:
            identifier: The unique identifier for the configuration, which is
                        used to construct the CDN URL (e.g., 'keysight/dsox1204g').

        Returns:
            The loaded configuration data as a dictionary.

        Raises:
            FileNotFoundError: If the configuration is not found on the CDN.
            InstrumentConfigurationError: If the downloaded configuration is invalid.
        """
        import pytestlab as ptl

        cache_dir = os.path.join(os.path.dirname(ptl.__file__), "cache", "configs")
        os.makedirs(cache_dir, exist_ok=True)

        cache_file = os.path.join(cache_dir, f"{identifier}.yaml")

        # Check for a cached version of the configuration first
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    content = f.read()
                    loaded_config = yaml.safe_load(content)
                    # Validate the cached content; if corrupt, proceed to download
                    if not isinstance(loaded_config, dict):
                        os.remove(cache_file)
                        raise InstrumentConfigurationError(
                            identifier, "Cached config is not a valid dictionary."
                        )
                    return loaded_config
            except Exception as e:
                # If reading the cache fails, remove the broken file and fetch from CDN
                print(f"Cache read failed for {identifier}: {e}. Fetching from CDN.")
                if os.path.exists(cache_file):
                    try:
                        os.remove(cache_file)
                    except OSError:
                        pass

        # If not cached, fetch from the official CDN
        url = f"https://pytestlab.org/config/{identifier}.yaml"
        with httpx.Client() as client:
            try:
                response = client.get(url, timeout=10)
                response.raise_for_status()  # Raise an exception for bad status codes

                config_text = response.text
                loaded_config = yaml.safe_load(config_text)
                if not isinstance(loaded_config, dict):
                    raise InstrumentConfigurationError(
                        identifier,
                        f"CDN config for {identifier} is not a valid dictionary.",
                    )

                # Cache the newly downloaded configuration
                with open(cache_file, 'w') as f:
                    f.write(config_text)

                return loaded_config
            except httpx.HTTPStatusError as http_err:
                # Handle HTTP errors, specifically 404 for not found
                if http_err.response.status_code == 404:
                     raise FileNotFoundError(f"Configuration file not found at {url} (HTTP 404).") from http_err
                else:
                     raise FileNotFoundError(f"Failed to fetch configuration from CDN ({url}): HTTP {http_err.response.status_code}") from http_err
            except httpx.RequestError as e:
                # Handle network-related errors
                raise FileNotFoundError(f"Failed to fetch configuration from CDN ({url}): {str(e)}") from e
            except yaml.YAMLError as ye:
                # Handle errors in parsing the YAML content
                raise InstrumentConfigurationError(
                    identifier, f"Error parsing YAML from CDN for {identifier}: {ye}"
                ) from ye


    @classmethod
    def get_config_from_local(cls: Type[AutoInstrument], identifier: str, normalized_identifier: Optional[str] = None) -> Dict[str, Any]:
        """Loads an instrument configuration from the local filesystem.

        This method searches for a configuration file in two primary locations:
        1. A built-in 'profiles' directory within the PyTestLab package.
        2. A direct file path provided by the user.

        Args:
            identifier: The identifier for the profile (e.g., 'keysight/dsox1204g')
                        or a direct path to a .yaml or .json file.
            normalized_identifier: A pre-normalized version of the identifier.

        Returns:
            The loaded configuration data as a dictionary.

        Raises:
            FileNotFoundError: If no configuration file can be found at any of the
                               searched locations.
            InstrumentConfigurationError: If the file is found but is not a valid
                                          YAML/JSON dictionary.
        """
        import pytestlab as ptl

        norm_id = normalized_identifier if normalized_identifier is not None else os.path.normpath(identifier)

        current_file_directory = os.path.dirname(ptl.__file__)
        preset_path = os.path.join(current_file_directory, "profiles", norm_id + '.yaml')

        # Determine the correct file path to load from
        path_to_try: Optional[str] = None
        if os.path.exists(preset_path):
            # First, check for a built-in profile matching the identifier
            path_to_try = preset_path
        elif os.path.exists(identifier) and (identifier.endswith('.yaml') or identifier.endswith('.json')):
            # Next, check if the identifier is a direct path to an existing file
            path_to_try = identifier

        if path_to_try:
            try:
                with open(path_to_try, 'r') as file:
                    content = file.read()
                    loaded_config = yaml.safe_load(content)
                    if not isinstance(loaded_config, dict):
                        raise InstrumentConfigurationError(
                            identifier,
                            f"Local config file '{path_to_try}' did not load as a dictionary.",
                        )
                    return loaded_config
            except yaml.YAMLError as ye:
                raise InstrumentConfigurationError(
                    identifier,
                    f"Error parsing YAML from local file '{path_to_try}': {ye}",
                ) from ye
            except Exception as e:
                raise FileNotFoundError(f"Error reading local config file '{path_to_try}': {e}") from e

        raise FileNotFoundError(f"No configuration found for identifier '{identifier}' in local paths.")

    @classmethod
    def from_config(cls: Type[AutoInstrument],
                          config_source: Union[str, Dict[str, Any], PydanticInstrumentConfig], # Adjusted type hint
                          *args,
                          serial_number: Optional[str] = None,
                          debug_mode: bool = False,
                          simulate: Optional[bool] = None,
                          backend_type_hint: Optional[str] = None,
                          address_override: Optional[str] = None,
                          timeout_override_ms: Optional[int] = None,
                          backend_override: Optional[InstrumentIO] = None # Add this new parameter
                         ) -> Instrument[Any]:
        """Initializes an instrument from a configuration source.

        This is the primary factory method for creating instrument instances. It
        orchestrates the entire setup process:
        1. Loads configuration from a dictionary, a local file, or a CDN URL.
        2. Determines whether to run in simulation or live mode.
        3. Selects and instantiates the appropriate communication backend (Sim, VISA, Lamb).
        4. Instantiates the final instrument driver with the config and backend.

        Note: This method creates and configures the instrument object but does not
        establish the connection. The caller must explicitly call `instrument.connect_backend()` on the returned object.

        Args:
            config_source: A dictionary containing the configuration, a string
                           identifier for a CDN/local profile, or a file path.
            serial_number: An optional serial number to override the one in the config.
            debug_mode: If True, prints detailed logs during the setup process.
            simulate: Explicitly enable or disable simulation mode, overriding
                      environment variables and config settings.
            backend_type_hint: Manually specify the backend ('visa' or 'lamb'),
                               bypassing automatic detection.
            address_override: Use a specific communication address, overriding the
                              one in the config.
            timeout_override_ms: Use a specific communication timeout in milliseconds.

        Returns:
            An initialized instrument object ready to be connected.

        Raises:
            FileNotFoundError: If the configuration source is a string and the
                               corresponding file cannot be found.
            InstrumentConfigurationError: If the configuration is invalid or a
                                          required setting is missing.
            TypeError: If `config_source` is not a dictionary or a string.
        """
        # Support serial_number as positional second argument
        if len(args) > 0 and isinstance(args[0], str):
            serial_number = args[0]

        config_data: Dict[str, Any]

        # Step 1: Add the backend_override check at the beginning
        backend_instance: InstrumentIO

        if backend_override:
            backend_instance = backend_override
            if debug_mode:
                print(f"Using provided backend override: {type(backend_instance).__name__}")
            # When overriding, we still need the config model. The rest of the logic can be simplified.
            if isinstance(config_source, PydanticInstrumentConfig):
                config_model = config_source
            else:
                config_model = load_profile(config_source)
        else:
            # Step 1: Load configuration data from the provided source
            config_model: PydanticInstrumentConfig
            if isinstance(config_source, PydanticInstrumentConfig):
                config_model = config_source
                config_data = config_model.model_dump(mode='python')
            elif isinstance(config_source, dict):
                config_data = config_source
                config_model = load_profile(config_data)
            elif isinstance(config_source, str):
                # Determine if this looks like a file path or a CDN identifier
                # File paths typically contain path separators or file extensions
                is_file_path = (
                    os.path.sep in config_source or
                    '/' in config_source or
                    config_source.endswith('.yaml') or
                    config_source.endswith('.json') or
                    os.path.exists(config_source)
                )

                if is_file_path:
                    # Try local file system first for file paths
                    try:
                        config_data = cls.get_config_from_local(config_source)
                        if debug_mode: print(f"Successfully loaded configuration for '{config_source}' from local.")
                    except FileNotFoundError:
                        # Fallback to CDN if local fails (unlikely for file paths)
                        try:
                            config_data = cls.get_config_from_cdn(config_source)
                            if debug_mode: print(f"Successfully loaded configuration for '{config_source}' from CDN.")
                        except FileNotFoundError:
                            raise FileNotFoundError(f"Configuration '{config_source}' not found in local paths or CDN.")
                else:
                    # Try CDN first for identifiers
                    try:
                        config_data = cls.get_config_from_cdn(config_source)
                        if debug_mode: print(f"Successfully loaded configuration for '{config_source}' from CDN.")
                    except FileNotFoundError:
                        try:
                            # Fallback to local file system if not found on CDN
                            config_data = cls.get_config_from_local(config_source)
                            if debug_mode: print(f"Successfully loaded configuration for '{config_source}' from local.")
                        except FileNotFoundError:
                            # If not found in either location, raise an error
                            raise FileNotFoundError(f"Configuration '{config_source}' not found in CDN or local paths.")
                config_model = load_profile(config_data)
            else:
                raise TypeError("config_source must be a file path (str), a dict, or an InstrumentConfig object.")

            # Override the serial number in the config if one is provided as an argument
            if serial_number is not None and hasattr(config_model, 'serial_number'):
                config_model.serial_number = serial_number # type: ignore

            # Step 2: Determine the final simulation mode based on a clear priority
            final_simulation_mode: bool
            if simulate is not None:
                # Highest priority: explicit argument to the function
                final_simulation_mode = simulate
                if debug_mode: print(f"Simulation mode explicitly set to {final_simulation_mode} by argument.")
            else:
                # Second priority: environment variable
                env_simulate = os.getenv("PYTESTLAB_SIMULATE")
                if env_simulate is not None:
                    final_simulation_mode = env_simulate.lower() in ('true', '1', 'yes')
                    if debug_mode: print(f"Simulation mode set to {final_simulation_mode} by PYTESTLAB_SIMULATE environment variable.")
                else:
                    # Lowest priority: default to False
                    final_simulation_mode = False
                    if debug_mode: print(f"Simulation mode defaulted to {final_simulation_mode} (no explicit argument or PYTESTLAB_SIMULATE).")

            # Step 3: Determine the actual communication address and timeout
            actual_address: Optional[str]
            if address_override is not None:
                # Argument override has the highest priority for address
                actual_address = address_override
                if debug_mode: print(f"Address overridden to '{actual_address}'.")
            else:
                # Otherwise, get the address from the configuration data
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


            # Step 4: Instantiate the appropriate backend based on the mode and configuration
            if final_simulation_mode:
                # Helper to resolve sim profile path
                def resolve_sim_profile_path(profile_key_or_path: str) -> str:
                    # 1. User override in ~/.pytestlab/profiles
                    user_profile = os.path.expanduser(os.path.join("~/.pytestlab/profiles", profile_key_or_path + ".yaml"))
                    if os.path.exists(user_profile):
                        return user_profile
                    # 2. User sim_profiles (legacy)
                    user_sim_profile = os.path.expanduser(os.path.join("~/.pytestlab/sim_profiles", profile_key_or_path + ".yaml"))
                    if os.path.exists(user_sim_profile):
                        return user_sim_profile
                    # 3. Package profile
                    import pytestlab as ptl
                    pkg_profile = os.path.join(os.path.dirname(ptl.__file__), "profiles", profile_key_or_path + ".yaml")
                    if os.path.exists(pkg_profile):
                        return pkg_profile
                    # 4. Direct path
                    if os.path.exists(profile_key_or_path):
                        return profile_key_or_path
                    raise FileNotFoundError(f"Simulation profile not found for '{profile_key_or_path}'")

                device_model_str = getattr(config_model, "model", "GenericSimulatedModel")
                if isinstance(config_source, str):
                    sim_profile_path = os.path.abspath(resolve_sim_profile_path(config_source))
                    if debug_mode:
                        print(f"Resolved sim profile path: {sim_profile_path}")
                else:
                    # Write dict config to a temp file
                    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
                        yaml.dump(config_data, tf)
                        sim_profile_path = os.path.abspath(tf.name)
                    if debug_mode:
                        print(f"Wrote temp sim profile: {sim_profile_path}")
                backend_instance = SimBackend(
                    profile_path=sim_profile_path,
                    model=device_model_str,
                    timeout_ms=actual_timeout,
                )
                if debug_mode:
                    print(
                        f"Using SimBackend for {device_model_str} with timeout {actual_timeout}ms. Profile: {sim_profile_path}"
                    )
            else:
                # For live hardware, determine the backend type (VISA or Lamb)
                if backend_type_hint:
                    # Explicit hint overrides any inference
                    chosen_backend_type = backend_type_hint.lower()
                    if debug_mode: print(f"Backend type hint provided: '{chosen_backend_type}'.")
                elif actual_address and "LAMB::" in actual_address.upper():
                    # Infer 'lamb' backend from the address format
                    chosen_backend_type = 'lamb'
                    if debug_mode: print(f"Inferred backend type: 'lamb' from address '{actual_address}'.")
                elif actual_address:
                    # Infer 'visa' for any other address type
                    chosen_backend_type = 'visa'
                    if debug_mode: print(f"Inferred backend type: 'visa' from address '{actual_address}'.")
                else:
                    # Default to 'lamb' if no address is provided (e.g., for remote discovery)
                    chosen_backend_type = 'lamb'
                    if debug_mode: print(f"Defaulting backend type to 'lamb' (no address present).")

                if chosen_backend_type == 'visa':
                    if actual_address is None:
                        raise InstrumentConfigurationError(
                            config_source, "Missing address/resource_name for VISA backend."
                        )
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
                            config_source,
                            "Lamb backend requires either an address or both model and serial_number in the config.",
                        )
                    if debug_mode:
                        print(f"Using AsyncLambBackend for model='{getattr(config_model, 'model', None)}', serial='{getattr(config_model, 'serial_number', None)}' via '{lamb_server_url}' with timeout {actual_timeout}ms.")
                else:
                    raise InstrumentConfigurationError(
                        config_source, f"Unsupported backend_type '{chosen_backend_type}'."
                    )

        # Step 5: Instantiate the final instrument driver class
        device_type_str: str = config_model.device_type
        instrument_class_to_init = cls._instrument_mapping.get(device_type_str.lower())

        if instrument_class_to_init is None:
            raise InstrumentConfigurationError(
                config_source,
                f"Unknown device_type: '{device_type_str}'. No registered instrument class.",
            )

        # The instrument's constructor receives the parsed configuration model and the
        # instantiated backend.
        instrument = instrument_class_to_init(config=config_model, backend=backend_instance)

        if debug_mode:
            print(f"Instantiated {instrument_class_to_init.__name__} with {type(backend_instance).__name__}.")
            print("Note: Backend connection is not established by __init__. Call 'instrument.connect_backend()' explicitly.")

        return instrument

    @classmethod
    def register_instrument(cls: Type[AutoInstrument], instrument_type: str, instrument_class: Type[Instrument[Any]]) -> None:
        """Dynamically registers a new custom instrument class.

        This allows users to extend PyTestLab with their own instrument drivers.
        Once registered, the new instrument type can be used with the factory
        methods like `from_config` and `from_type`.

        Args:
            instrument_type: The string identifier for the new instrument type
                             (e.g., 'my_custom_scope'). This is case-insensitive.
            instrument_class: The class object that implements the instrument driver.
                              It must be a subclass of `pytestlab.Instrument`.

        Raises:
            InstrumentConfigurationError: If the instrument type name is already
                                          in use or if the provided class is not a
                                          valid subclass of `Instrument`.
        """
        type_key = instrument_type.lower()
        if type_key in cls._instrument_mapping:
            raise InstrumentConfigurationError(
                instrument_type,
                f"Instrument type '{instrument_type}' already registered with class {cls._instrument_mapping[type_key].__name__}",
            )
        if not issubclass(instrument_class, Instrument):
            raise InstrumentConfigurationError(
                instrument_type,
                f"Cannot register class {instrument_class.__name__}. It must be a subclass of Instrument.",
            )
        cls._instrument_mapping[type_key] = instrument_class
        # Consider using a logger if available, instead of print
        print(f"Instrument type '{instrument_type}' registered with class {instrument_class.__name__}.")
