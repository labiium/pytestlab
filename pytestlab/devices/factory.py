from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
import yaml

from ..config.device_config import DeviceConfig
from ..config.device_config import GenericDeviceConfig
from ..errors import InstrumentConfigurationError
from .base import Device
from .base import DeviceIO
from .registry import BackendBuildContext
from .registry import get_backend_factory
from .registry import get_device_driver
from .registry import load_import_path
from .registry import validate_backend
from .registry import validate_driver


class AutoDevice:
    """Factory for arbitrary automatable lab devices."""

    @classmethod
    def from_type(cls, device_type: str, *args: Any, **kwargs: Any) -> Device[Any]:
        driver_class = get_device_driver(device_type)
        if driver_class is None:
            raise InstrumentConfigurationError(device_type, f"Unknown device type: {device_type}")
        return driver_class(*args, **kwargs)

    @classmethod
    def get_config_from_cdn(cls, identifier: str) -> dict[str, Any]:
        import pytestlab as ptl

        pkg_file = getattr(ptl, "__file__", None)
        if pkg_file is None:
            raise InstrumentConfigurationError(
                identifier, "Cannot locate pytestlab package file for cache directory."
            )
        cache_dir = Path(pkg_file).resolve().parent / "cache" / "configs"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{identifier}.yaml"
        if cache_file.exists():
            try:
                loaded_config = yaml.safe_load(cache_file.read_text())
                if not isinstance(loaded_config, dict):
                    cache_file.unlink(missing_ok=True)
                    raise InstrumentConfigurationError(
                        identifier, "Cached config is not a valid dictionary."
                    )
                return loaded_config
            except Exception:
                cache_file.unlink(missing_ok=True)
        url = f"https://cdn.pytestlab.org/config/{identifier}.yaml"
        with httpx.Client() as client:
            try:
                response = client.get(url, timeout=10)
                response.raise_for_status()
                loaded_config = yaml.safe_load(response.text)
                if not isinstance(loaded_config, dict):
                    raise InstrumentConfigurationError(
                        identifier, f"CDN config for {identifier} is not a valid dictionary."
                    )
                cache_file.write_text(response.text)
                return loaded_config
            except httpx.HTTPStatusError as http_err:
                if http_err.response.status_code == 404:
                    raise FileNotFoundError(f"Configuration file not found at {url}") from http_err
                raise FileNotFoundError(
                    f"Failed to fetch configuration from CDN ({url}): "
                    f"HTTP {http_err.response.status_code}"
                ) from http_err
            except httpx.RequestError as exc:
                raise FileNotFoundError(
                    f"Failed to fetch configuration from CDN ({url}): {exc}"
                ) from exc
            except yaml.YAMLError as exc:
                raise InstrumentConfigurationError(
                    identifier, f"Error parsing YAML from CDN for {identifier}: {exc}"
                ) from exc

    @classmethod
    def get_config_from_local(
        cls, identifier: str, normalized_identifier: str | None = None
    ) -> dict[str, Any]:
        import pytestlab as ptl

        norm_id = normalized_identifier if normalized_identifier is not None else os.path.normpath(identifier)
        pkg_file = getattr(ptl, "__file__", None)
        pkg_dir = Path(pkg_file).resolve().parent if pkg_file is not None else Path(__file__).resolve().parent
        preset_path = pkg_dir / "profiles" / f"{norm_id}.yaml"
        path_to_try: str | None = None
        if preset_path.exists():
            path_to_try = str(preset_path)
        elif os.path.exists(identifier) and identifier.endswith((".yaml", ".yml", ".json")):
            path_to_try = identifier
        if path_to_try:
            try:
                with open(path_to_try) as file:
                    loaded_config = yaml.safe_load(file.read())
                if not isinstance(loaded_config, dict):
                    raise InstrumentConfigurationError(
                        identifier,
                        f"Local config file '{path_to_try}' did not load as a dictionary.",
                    )
                return loaded_config
            except yaml.YAMLError as exc:
                raise InstrumentConfigurationError(
                    identifier, f"Error parsing YAML from local file '{path_to_try}': {exc}"
                ) from exc
        raise FileNotFoundError(f"No configuration found for identifier '{identifier}'.")

    @classmethod
    def from_config(
        cls,
        config_source: str | dict[str, Any] | DeviceConfig,
        *args: Any,
        serial_number: str | None = None,
        debug_mode: bool = False,
        simulate: bool | None = None,
        backend_type_hint: str | None = None,
        address_override: str | None = None,
        timeout_override_ms: int | None = None,
        backend_override: DeviceIO | None = None,
    ) -> Device[Any]:
        if args and isinstance(args[0], str):
            serial_number = args[0]

        config_model, config_data, profile_key = cls._load_config_model(config_source)
        if serial_number is not None and hasattr(config_model, "serial_number"):
            config_model.serial_number = serial_number

        backend_instance = backend_override or cls._build_backend(
            config_model=config_model,
            config_data=config_data,
            config_source=config_source,
            profile_key=profile_key,
            debug_mode=debug_mode,
            simulate=simulate,
            backend_type_hint=backend_type_hint,
            address_override=address_override,
            timeout_override_ms=timeout_override_ms,
        )

        driver_class = cls._resolve_driver(config_model, config_data, config_source)
        device = driver_class(config=config_model, backend=backend_instance)
        if debug_mode:
            print(f"Instantiated {driver_class.__name__} with {type(backend_instance).__name__}.")
            print("Note: Backend connection is not established by __init__. Call connect_backend().")
        return device

    @classmethod
    def _load_config_model(
        cls, config_source: str | dict[str, Any] | DeviceConfig
    ) -> tuple[DeviceConfig, dict[str, Any], str | None]:
        from ..config.loader import load_device_profile

        if isinstance(config_source, DeviceConfig):
            return config_source, config_source.model_dump(mode="python"), None
        if isinstance(config_source, dict) and "profile" in config_source:
            profile_source = config_source["profile"]
            config_model = load_device_profile(profile_source)
            config_data = config_model.model_dump(mode="python")
            for key, value in config_source.items():
                if key != "profile":
                    config_data[key] = value
                    if hasattr(config_model, key):
                        setattr(config_model, key, value)
            return config_model, config_data, str(profile_source)
        if isinstance(config_source, dict):
            config_model = load_device_profile(config_source)
            return config_model, dict(config_source), None
        if isinstance(config_source, str):
            config_data = cls._load_config_data_from_string(config_source)
            config_model = load_device_profile(config_data)
            return config_model, config_data, config_source
        raise TypeError("config_source must be a file path, profile key, dict, or DeviceConfig object.")

    @classmethod
    def _load_config_data_from_string(cls, config_source: str) -> dict[str, Any]:
        is_file_path = (
            os.path.sep in config_source
            or "/" in config_source
            or config_source.endswith((".yaml", ".yml", ".json"))
            or os.path.exists(config_source)
        )
        if is_file_path:
            try:
                return cls.get_config_from_local(config_source)
            except FileNotFoundError:
                try:
                    return cls.get_config_from_cdn(config_source)
                except FileNotFoundError:
                    raise FileNotFoundError(
                        f"Configuration '{config_source}' not found in local paths or CDN."
                    ) from None
        try:
            return cls.get_config_from_cdn(config_source)
        except FileNotFoundError:
            try:
                return cls.get_config_from_local(config_source)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"Configuration '{config_source}' not found in CDN or local paths."
                ) from None

    @classmethod
    def _build_backend(
        cls,
        *,
        config_model: DeviceConfig,
        config_data: dict[str, Any],
        config_source: Any,
        profile_key: str | None,
        debug_mode: bool,
        simulate: bool | None,
        backend_type_hint: str | None,
        address_override: str | None,
        timeout_override_ms: int | None,
    ) -> DeviceIO:
        final_simulation_mode = cls._resolve_simulation_mode(simulate)
        actual_address = address_override if address_override is not None else getattr(config_model, "address", None)
        actual_timeout = cls._resolve_timeout(config_model, timeout_override_ms)
        backend_spec = cls._resolve_backend_spec(config_model, config_data)

        if final_simulation_mode:
            chosen_backend_type = "sim"
        elif backend_spec and backend_spec.get("import_path"):
            chosen_backend_type = str(backend_spec.get("type") or "custom")
        elif backend_type_hint:
            chosen_backend_type = backend_type_hint.lower()
        elif backend_spec and backend_spec.get("type"):
            chosen_backend_type = str(backend_spec["type"]).lower()
        elif actual_address and "LAMB::" in actual_address.upper():
            chosen_backend_type = "lamb"
        elif actual_address:
            chosen_backend_type = "visa"
        else:
            chosen_backend_type = "lamb"

        profile_path = None
        if chosen_backend_type == "sim":
            profile_path = cls._resolve_sim_profile_path(profile_key, config_data)

        context = BackendBuildContext(
            config=config_model,
            config_source=config_source,
            address=actual_address,
            timeout_ms=actual_timeout,
            simulate=final_simulation_mode,
            backend_type=chosen_backend_type,
            backend_spec=backend_spec,
            profile_path=profile_path,
            debug_mode=debug_mode,
        )
        if backend_spec and backend_spec.get("import_path") and chosen_backend_type != "sim":
            factory = validate_backend(load_import_path(str(backend_spec["import_path"])), str(backend_spec["import_path"]))
            return cls._call_backend_factory(factory, context)
        factory = get_backend_factory(chosen_backend_type)
        if factory is None:
            raise InstrumentConfigurationError(
                config_source, f"Unsupported backend_type '{chosen_backend_type}'."
            )
        return cls._call_backend_factory(factory, context)

    @staticmethod
    def _call_backend_factory(factory: Any, context: BackendBuildContext) -> DeviceIO:
        try:
            return factory(context)
        except TypeError:
            kwargs = dict(context.backend_spec or {})
            kwargs.pop("type", None)
            kwargs.pop("import_path", None)
            kwargs.setdefault("address", context.address)
            kwargs.setdefault("timeout_ms", context.timeout_ms)
            return factory(**kwargs)

    @staticmethod
    def _resolve_simulation_mode(simulate: bool | None) -> bool:
        if simulate is not None:
            return simulate
        env_simulate = os.getenv("PYTESTLAB_SIMULATE")
        if env_simulate is not None:
            return env_simulate.lower() in ("true", "1", "yes")
        return False

    @staticmethod
    def _resolve_timeout(config_model: DeviceConfig, timeout_override_ms: int | None) -> int:
        if timeout_override_ms is not None and timeout_override_ms > 0:
            return timeout_override_ms
        timeout_from_config = getattr(config_model, "communication_timeout_ms", None)
        comm = getattr(config_model, "communication", None)
        if comm is not None:
            timeout_from_config = getattr(comm, "timeout_ms", timeout_from_config)
        if isinstance(timeout_from_config, int) and timeout_from_config > 0:
            return timeout_from_config
        return 30000

    @staticmethod
    def _resolve_backend_spec(
        config_model: DeviceConfig, config_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        spec = config_data.get("backend")
        if isinstance(spec, dict):
            return spec
        model_spec = getattr(config_model, "backend", None)
        return model_spec if isinstance(model_spec, dict) else None

    @classmethod
    def _resolve_sim_profile_path(
        cls, profile_key: str | None, config_data: dict[str, Any]
    ) -> str:
        if profile_key is not None:
            key = profile_key
            user_profile = Path("~/.pytestlab/profiles").expanduser() / f"{key}.yaml"
            if user_profile.exists():
                return str(user_profile)
            user_sim_profile = Path("~/.pytestlab/sim_profiles").expanduser() / f"{key}.yaml"
            if user_sim_profile.exists():
                return str(user_sim_profile)
            try:
                return str(Path(cls.get_config_from_local_path(key)).resolve())
            except FileNotFoundError:
                if os.path.exists(key):
                    return os.path.abspath(key)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            yaml.dump(config_data, tf)
            return os.path.abspath(tf.name)

    @classmethod
    def get_config_from_local_path(cls, identifier: str) -> Path:
        import pytestlab as ptl

        pkg_file = getattr(ptl, "__file__", None)
        pkg_dir = Path(pkg_file).resolve().parent if pkg_file is not None else Path(__file__).resolve().parent
        path = pkg_dir / "profiles" / f"{os.path.normpath(identifier)}.yaml"
        if path.exists():
            return path
        candidate = Path(identifier)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(identifier)

    @staticmethod
    def _resolve_driver(
        config_model: DeviceConfig, config_data: dict[str, Any], config_source: Any
    ) -> type[Device[Any]]:
        driver_path = config_data.get("driver") or getattr(config_model, "driver", None)
        if driver_path:
            return validate_driver(load_import_path(str(driver_path)), str(driver_path))
        driver_class = get_device_driver(config_model.device_type)
        if driver_class is None:
            if isinstance(config_model, GenericDeviceConfig):
                raise InstrumentConfigurationError(
                    config_source,
                    f"Unknown device_type '{config_model.device_type}'. Provide a driver import path "
                    "or register the device type.",
                )
            raise InstrumentConfigurationError(
                config_source,
                f"Unknown device_type: '{config_model.device_type}'. No registered device class.",
            )
        return driver_class

