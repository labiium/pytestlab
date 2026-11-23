from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from importlib import metadata
from typing import Any
from typing import cast

from pydantic import BaseModel

from .._lamb_url import resolve_lamb_url
from .._log import get_logger
from ..config.device_config import DeviceConfig
from ..errors import InstrumentConfigurationError
from .base import Device
from .base import DeviceBackend

BackendFactory = Callable[[Any], DeviceBackend]


@dataclass(frozen=True)
class BackendBuildContext:
    """Inputs supplied to a registered backend factory for one device instance."""

    config: DeviceConfig
    config_source: Any
    address: str | None
    timeout_ms: int
    simulate: bool
    backend_type: str
    backend_spec: dict[str, Any] | None = None
    profile_path: str | None = None
    debug_mode: bool = False
    sim_session: Any | None = None
    backend_resources: Mapping[str, Any] | None = None
    force_builtin_sim: bool = False

    def shared_resource(self, backend_type: str, default: Any = None) -> Any:
        """Return the bench-scoped resource prepared for ``backend_type``."""
        if self.backend_resources is None:
            return default
        return self.backend_resources.get(backend_type.lower(), default)


_device_drivers: dict[str, type[Device[Any]]] = {}
_device_driver_specs: dict[str, tuple[str, str]] = {}
_config_models: dict[str, type[DeviceConfig]] = {}
_config_model_specs: dict[str, tuple[str, str]] = {}
_backends: dict[str, BackendFactory] = {}
_entry_points_loaded = False
_builtins_registered = False
_entry_point_diagnostics: list[dict[str, str]] = []
_LOG = get_logger("devices.registry")


def load_import_path(path: str) -> Any:
    """Load an import path or a built-in generic driver alias."""
    if builtin_simulation_only() and not any(
        is_builtin_profile_import(path, key, config=kind)
        for key in _BUILTIN_DEVICE_SPECS
        for kind in (False, True)
    ):
        raise InstrumentConfigurationError(
            path, "Custom imports are disabled in simulation-only benches."
        )

    if path in {"instrument", "profile_instrument", "generic_instrument"}:
        module = import_module("pytestlab.instruments.profile_instrument")
        return module.ProfileInstrument
    if ":" in path:
        module_name, attr_name = path.split(":", 1)
    else:
        module_name, _, attr_name = path.rpartition(".")
    if not module_name or not attr_name:
        raise InstrumentConfigurationError(path, "Import path must be 'module:attribute'.")
    try:
        module = import_module(module_name)
        return getattr(module, attr_name)
    except Exception as exc:
        raise InstrumentConfigurationError(path, f"Could not import '{path}': {exc}") from exc


def _load_spec(spec: tuple[str, str]) -> Any:
    module_name, attr_name = spec
    module = import_module(module_name)
    return getattr(module, attr_name)


def clear_entry_point_diagnostics() -> None:
    _entry_point_diagnostics.clear()


def get_entry_point_diagnostics() -> list[dict[str, str]]:
    return [dict(item) for item in _entry_point_diagnostics]


def _record_entry_point_failure(group: str, kind: str, name: str, exc: Exception) -> None:
    diagnostic = {
        "group": group,
        "kind": kind,
        "name": name,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    _entry_point_diagnostics.append(diagnostic)
    _LOG.warning(
        "Failed to load %s entry point %r from %s: %s: %s",
        kind,
        name,
        group,
        diagnostic["error_type"],
        diagnostic["message"],
    )


def register_device_type(
    device_type: str,
    driver_class: type[Device[Any]],
    config_class: type[DeviceConfig] | None = None,
    *,
    replace: bool = False,
) -> None:
    key = device_type.lower()
    if key in _device_drivers and not replace:
        raise InstrumentConfigurationError(
            device_type, f"Device type '{device_type}' is already registered."
        )
    if not isinstance(driver_class, type) or not issubclass(driver_class, Device):
        raise InstrumentConfigurationError(
            device_type, f"{driver_class!r} must be a Device subclass."
        )
    _device_drivers[key] = driver_class
    _device_driver_specs.pop(key, None)
    if config_class is not None:
        register_config_model(device_type, config_class, replace=replace)


def register_config_model(
    device_type: str, config_class: type[DeviceConfig], *, replace: bool = False
) -> None:
    key = device_type.lower()
    if key in _config_models and not replace:
        raise InstrumentConfigurationError(
            device_type, f"Config model for '{device_type}' is already registered."
        )
    if not isinstance(config_class, type) or not issubclass(config_class, DeviceConfig):
        raise InstrumentConfigurationError(
            device_type, f"{config_class!r} must be a DeviceConfig subclass."
        )
    _config_models[key] = config_class
    _config_model_specs.pop(key, None)


def register_backend(backend_type: str, factory: BackendFactory, *, replace: bool = False) -> None:
    key = backend_type.lower()
    if key in _backends and not replace:
        raise InstrumentConfigurationError(
            backend_type, f"Backend type '{backend_type}' is already registered."
        )
    if not callable(factory):
        raise InstrumentConfigurationError(backend_type, "Backend factory must be callable.")
    _backends[key] = factory


def get_device_driver(device_type: str) -> type[Device[Any]] | None:
    if builtin_simulation_only():
        spec = _BUILTIN_DEVICE_SPECS.get(device_type.lower())
        return _load_spec(spec[0]) if spec else None
    ensure_builtin_registrations()
    load_entry_points()
    key = device_type.lower()
    if key in _device_driver_specs:
        driver = _load_spec(_device_driver_specs.pop(key))
        register_device_type(key, driver, replace=True)
    return _device_drivers.get(key)


def get_config_model(device_type: str) -> type[DeviceConfig] | None:
    if builtin_simulation_only():
        spec = _BUILTIN_DEVICE_SPECS.get(device_type.lower())
        return _load_spec(spec[1]) if spec else None
    ensure_builtin_registrations()
    load_entry_points()
    key = device_type.lower()
    if key in _config_model_specs:
        config = _load_spec(_config_model_specs.pop(key))
        register_config_model(key, config, replace=True)
    return _config_models.get(key)


def get_backend_factory(backend_type: str) -> BackendFactory | None:
    ensure_builtin_registrations()
    load_entry_points()
    return _backends.get(backend_type.lower())


def get_config_registry() -> dict[str, type[DeviceConfig]]:
    if builtin_simulation_only():
        return {key: _load_spec(spec[1]) for key, spec in _BUILTIN_DEVICE_SPECS.items()}
    ensure_builtin_registrations()
    load_entry_points()
    registry: dict[str, type[DeviceConfig]] = {}
    for key in sorted(set(_config_models) | set(_config_model_specs)):
        model = get_config_model(key)
        if model is not None:
            registry[key] = model
    return registry


def get_device_registry() -> dict[str, type[Device[Any]]]:
    ensure_builtin_registrations()
    load_entry_points()
    registry: dict[str, type[Device[Any]]] = {}
    for key in sorted(set(_device_drivers) | set(_device_driver_specs)):
        driver = get_device_driver(key)
        if driver is not None:
            registry[key] = driver
    return registry


def load_entry_points() -> None:
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    groups = {
        "pytestlab.device_drivers": "device_driver",
        "pytestlab.device_configs": "device_config",
        "pytestlab.backends": "backend",
    }
    for group, kind in groups.items():
        try:
            entry_points = metadata.entry_points(group=group)
        except TypeError:
            discovered = metadata.entry_points()
            if hasattr(discovered, "select"):
                entry_points = discovered.select(group=group)
            else:
                legacy_entry_points = cast(Any, discovered)
                entry_points = legacy_entry_points.get(group, [])
        except Exception as exc:
            _record_entry_point_failure(group, kind, f"{group} discovery", exc)
            continue
        for ep in entry_points:
            try:
                loaded = ep.load()
                if kind == "device_driver":
                    register_device_type(ep.name, loaded, replace=True)
                elif kind == "device_config":
                    register_config_model(ep.name, loaded, replace=True)
                else:
                    register_backend(ep.name, loaded, replace=True)
            except Exception as exc:
                _record_entry_point_failure(group, kind, ep.name, exc)
                continue


_BUILTIN_DEVICE_SPECS = {
    "camera": (
        ("pytestlab.camera", "Camera"),
        ("pytestlab.config.camera_config", "CameraConfig"),
    ),
    "instrument": (
        ("pytestlab.instruments.profile_instrument", "ProfileInstrument"),
        ("pytestlab.config.instrument_config", "InstrumentConfig"),
    ),
    "profile_instrument": (
        ("pytestlab.instruments.profile_instrument", "ProfileInstrument"),
        ("pytestlab.config.instrument_config", "InstrumentConfig"),
    ),
    "generic_instrument": (
        ("pytestlab.instruments.profile_instrument", "ProfileInstrument"),
        ("pytestlab.config.instrument_config", "InstrumentConfig"),
    ),
    "oscilloscope": (
        ("pytestlab.instruments.Oscilloscope", "Oscilloscope"),
        ("pytestlab.config.oscilloscope_config", "OscilloscopeConfig"),
    ),
    "waveform_generator": (
        ("pytestlab.instruments.WaveformGenerator", "WaveformGenerator"),
        ("pytestlab.config.waveform_generator_config", "WaveformGeneratorConfig"),
    ),
    "power_supply": (
        ("pytestlab.instruments.PowerSupply", "PowerSupply"),
        ("pytestlab.config.power_supply_config", "PowerSupplyConfig"),
    ),
    "multimeter": (
        ("pytestlab.instruments.Multimeter", "Multimeter"),
        ("pytestlab.config.multimeter_config", "MultimeterConfig"),
    ),
    "dc_active_load": (
        ("pytestlab.instruments.DCActiveLoad", "DCActiveLoad"),
        ("pytestlab.config.dc_active_load_config", "DCActiveLoadConfig"),
    ),
    "vna": (
        ("pytestlab.instruments.VectorNetworkAnalyser", "VectorNetworkAnalyser"),
        ("pytestlab.config.vna_config", "VNAConfig"),
    ),
    "vector_network_analyzer": (
        ("pytestlab.instruments.VectorNetworkAnalyser", "VectorNetworkAnalyser"),
        ("pytestlab.config.vna_config", "VNAConfig"),
    ),
    "impedance_analyzer": (
        ("pytestlab.instruments.ImpedanceAnalyzer", "ImpedanceAnalyzer"),
        ("pytestlab.config.impedance_analyzer_config", "ImpedanceAnalyzerConfig"),
    ),
    "spectrum_analyzer": (
        ("pytestlab.instruments.SpectrumAnalyser", "SpectrumAnalyser"),
        ("pytestlab.config.spectrum_analyzer_config", "SpectrumAnalyzerConfig"),
    ),
    "power_meter": (
        ("pytestlab.instruments.PowerMeter", "PowerMeter"),
        ("pytestlab.config.power_meter_config", "PowerMeterConfig"),
    ),
    "virtual_instrument": (
        ("pytestlab.instruments.VirtualInstrument", "VirtualInstrument"),
        ("pytestlab.config.virtual_instrument_config", "VirtualInstrumentConfig"),
    ),
    "switch_matrix": (
        ("pytestlab.devices.switch_matrix", "SwitchMatrixDevice"),
        ("pytestlab.config.switch_matrix_config", "SwitchMatrixConfig"),
    ),
    "prober": (
        ("pytestlab.prober", "GenericProberDevice"),
        ("pytestlab.config.device_config", "DeviceConfig"),
    ),
    "source_measure": (
        ("pytestlab.instruments.SourceMeasure", "SourceMeasure"),
        ("pytestlab.config.source_measure_config", "SourceMeasureConfig"),
    ),
    "motion_stage": (
        ("pytestlab.motion_profile", "ProfileMotionDevice"),
        ("pytestlab.config.device_config", "DeviceConfig"),
    ),
}


_builtin_simulation_only = ContextVar("builtin_simulation_only", default=False)


def builtin_simulation_only() -> bool:
    return _builtin_simulation_only.get()


@contextmanager
def builtin_simulation_scope():
    """Do not discover or use third-party device/backend registrations."""
    token = _builtin_simulation_only.set(True)
    try:
        yield
    finally:
        _builtin_simulation_only.reset(token)


def get_builtin_sim_backend_factory(backend_type: str) -> BackendFactory:
    if backend_type == "sim":
        return _build_sim_backend
    if backend_type == "circuit_sim":
        from ..instruments.backends.circuit_sim_backend import build_circuit_sim_backend

        return build_circuit_sim_backend
    raise InstrumentConfigurationError(backend_type, "Not a built-in simulator.")


def is_builtin_profile_import(path: str, device_type: str, *, config: bool) -> bool:
    spec = _BUILTIN_DEVICE_SPECS.get(device_type)
    if spec and path in {":".join(spec[int(config)]), ".".join(spec[int(config)])}:
        return True
    return (
        not config
        and device_type in {"instrument", "profile_instrument", "generic_instrument"}
        and path
        in {
            "instrument",
            "profile_instrument",
            "generic_instrument",
            "pytestlab.instruments.profile_instrument:ProfileInstrument",
            "pytestlab.instruments.profile_instrument.ProfileInstrument",
        }
    )


def ensure_builtin_registrations() -> None:
    global _builtins_registered
    if _builtins_registered:
        return
    _builtins_registered = True
    for key, (driver_spec, config_spec) in _BUILTIN_DEVICE_SPECS.items():
        _device_driver_specs.setdefault(key, driver_spec)
        _config_model_specs.setdefault(key, config_spec)

    register_backend("visa", _build_visa_backend, replace=True)
    register_backend("lamb", _build_lamb_backend, replace=True)
    register_backend("sim", _build_sim_backend, replace=True)
    try:
        from ..instruments.backends.circuit_sim_backend import build_circuit_sim_backend

        register_backend("circuit_sim", build_circuit_sim_backend, replace=True)
    except ModuleNotFoundError:
        pass


def _build_visa_backend(context: BackendBuildContext) -> DeviceBackend:
    if context.address is None:
        raise InstrumentConfigurationError(
            context.config_source, "Missing address for VISA backend."
        )
    from ..instruments.backends.visa_backend import VisaBackend

    return VisaBackend(address=context.address, timeout_ms=context.timeout_ms)


def _build_lamb_backend(context: BackendBuildContext) -> DeviceBackend:
    if getattr(context.config, "device_type", None) == "camera":
        from ..instruments.backends.lamb_camera import build_lamb_camera_backend

        return build_lamb_camera_backend(context)

    from ..instruments.backends.lamb import LambBackend

    lamb_server_url = resolve_lamb_url(
        (context.backend_spec or {}).get("url"),
        profile_url=getattr(context.config, "lamb_url", None),
    )
    if context.address:
        return LambBackend(
            address=context.address,
            url=lamb_server_url,
            timeout_ms=context.timeout_ms,
            # Keep the profile identity even when the descriptor supplies an
            # explicit resource string.  LAMB close intentionally releases the
            # server-side handle, so a later operation needs this identity to
            # re-register the same physical resource after a 404.
            model_name=context.config.model,
            serial_number=context.config.serial_number,
        )
    return LambBackend(
        address=None,
        url=lamb_server_url,
        timeout_ms=context.timeout_ms,
        model_name=context.config.model,
        serial_number=context.config.serial_number,
    )


def _build_sim_backend(context: BackendBuildContext) -> DeviceBackend:
    if context.profile_path is None:
        raise InstrumentConfigurationError(
            context.config_source, "Missing simulation profile path."
        )
    from ..instruments.backends.sim_backend import SimBackend

    return SimBackend(
        profile_path=context.profile_path,
        model=context.config.model,
        timeout_ms=context.timeout_ms,
        allow_user_profile_overrides=not context.force_builtin_sim,
    )


def validate_config_model(candidate: Any, source: str) -> type[DeviceConfig]:
    if not isinstance(candidate, type) or not issubclass(candidate, DeviceConfig):
        raise InstrumentConfigurationError(
            source, f"{source} must resolve to a DeviceConfig class."
        )
    return candidate


def validate_driver(candidate: Any, source: str) -> type[Device[Any]]:
    if not isinstance(candidate, type) or not issubclass(candidate, Device):
        raise InstrumentConfigurationError(source, f"{source} must resolve to a Device class.")
    return candidate


def validate_backend(candidate: Any, source: str) -> BackendFactory:
    if not callable(candidate):
        raise InstrumentConfigurationError(source, f"{source} must resolve to a backend callable.")
    return cast(BackendFactory, candidate)


def is_pydantic_model(candidate: Any) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, BaseModel)
