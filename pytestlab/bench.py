import copy
import json
import logging
import math
import os
import shlex
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

from .accessories import BoundAccessory
from .accessories import MeasurementChain
from .common.health import HealthReport
from .common.health import HealthStatus
from .config.bench_config import BenchConfigExtended
from .config.bench_config import DeviceEntry
from .config.bench_config import InstrumentEntry
from .config.bench_config import MeasurementPlanEntry
from .config.bench_loader import build_validation_context
from .config.bench_loader import entry_backend_options
from .config.bench_loader import load_bench_yaml
from .config.bench_loader import run_custom_validations
from .config.device_config import DeviceConfig
from .devices import AutoDevice
from .devices import Device
from .devices import SwitchMatrixDevice
from .devices.providers import BackendResourceScope
from .devices.providers import prepare_backend_resources
from .errors import InstrumentConfigurationError
from .experiments import Experiment
from .experiments.database import MeasurementDatabase
from .instruments import Instrument
from .instruments.AutoInstrument import AutoInstrument
from .measurement_plan import PreparedMeasurementPlan
from .measurement_plan import describe_declared_measurement
from .measurement_plan import describe_declared_route
from .measurement_plan import execute_declared_measurement
from .measurement_plan import measurement_chain_for
from .measurement_plan import prepare_declared_measurements
from .measurement_plan import raise_for_declared_measurement_errors

# Configure logging
logger = logging.getLogger("pytestlab.bench")


class SafetyLimitError(Exception):
    """Raised when an operation violates safety limits."""

    def __init__(self, *args: object):
        super().__init__(*args)
        audit_path = os.getenv("PYTESTLAB_SAFETY_AUDIT_PATH")
        if not audit_path:
            return
        event = {
            "event": "safety_limit_rejection",
            "exception": type(self).__name__,
            "message": str(self),
            "source": sys._getframe(1).f_code.co_filename,
            "timestamp_ns": time.time_ns(),
        }
        try:
            with Path(audit_path).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        except OSError:
            logger.warning(
                "Could not append the configured safety audit sink",
                exc_info=True,
            )


class InstrumentMacroError(Exception):
    """Raised when an automation macro fails to execute."""

    pass


_RAW_COMMAND_METHODS = frozenset({"write", "query", "query_raw"})


def _public_names(value: Any) -> set[str]:
    """Return discoverable names without exposing private implementation state."""
    return {name for name in dir(value) if not name.startswith("_")}


class _SafeChannelFacade:
    """Keep fluent channel operations inside the parent safety boundary."""

    __slots__ = ("__safe_device", "__facade", "__channel")

    def __init__(self, safe_device: "SafeDeviceWrapper", facade: Any, channel: int):
        self.__safe_device = safe_device
        self.__facade = facade
        self.__channel = channel

    def set(
        self, voltage: float | None = None, current_limit: float | None = None
    ) -> "_SafeChannelFacade":
        """Apply voltage and current limit to this channel, enforcing the bench safety limits.


        Values above a configured limit raise :class:`SafetyLimitError` instead of
        reaching the instrument.

        Returns:
            This facade, so calls can be chained.
        """
        validate_setpoints = getattr(self.__facade, "_validate_setpoints", None)
        if callable(validate_setpoints):
            validate_setpoints(voltage=voltage, current_limit=current_limit)
        if voltage is not None:
            self.__safe_device._check_set_voltage_limit(self.__channel, voltage)
        if current_limit is not None:
            self.__safe_device._check_set_current_limit(self.__channel, current_limit)

        self.__safe_device._preflight_channel(
            self.__channel, voltage=voltage, current_limit=current_limit
        )
        result = self.__facade.set(voltage=voltage, current_limit=current_limit)
        if result is not self.__facade:
            return result
        return self

    def force_current(self, current: float, voltage_compliance: float) -> "_SafeChannelFacade":
        self.__safe_device._preflight_channel(
            self.__channel, current=current, voltage_compliance=voltage_compliance
        )
        result = self.__facade.force_current(current=current, voltage_compliance=voltage_compliance)
        return self if result is self.__facade else result

    def on(self) -> "_SafeChannelFacade":
        self.__safe_device._preflight_output(self.__channel)
        result = self.__facade.on()
        return self if result is self.__facade else result

    def off(self) -> "_SafeChannelFacade":
        result = self.__facade.off()
        return self if result is self.__facade else result

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise SafetyLimitError("Raw channel-facade internals are not publicly accessible.")
        attribute = getattr(self.__facade, name)
        if not callable(attribute):
            return attribute

        def preserve_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = attribute(*args, **kwargs)
            return self if result is self.__facade else result

        return preserve_wrapper

    def __dir__(self) -> list[str]:
        """Expose public channel operations without revealing wrapped internals."""
        wrapper_names = {
            name for cls in type(self).__mro__ for name in vars(cls) if not name.startswith("_")
        }
        return sorted((wrapper_names | _public_names(self.__facade)) - _RAW_COMMAND_METHODS)


class SafeDeviceWrapper:
    """Wraps a device to enforce safety limits defined in the bench config.

    This class acts as a proxy to an underlying device object. It intercepts
        calls to methods that could be dangerous (like `set_voltage` on a power
        supply) and checks them against the defined safety limits before passing
        the call to the actual device. This helps prevent accidental damage to
        equipment or the device under test.

    """

    __slots__ = ("__device", "__safety_limits", "__role")

    def __init__(self, device: Device, safety_limits: Any, role: str):
        self.__device = device
        self.__safety_limits = copy.deepcopy(safety_limits)
        self.__role = role

    @property
    def safety_limits(self) -> Any:
        """A read-only snapshot of the limits enforced by this handle."""
        return copy.deepcopy(self.__safety_limits)

    @property
    def role(self) -> str:
        """The resolved safety role for this device."""
        return self.__role

    @property
    def is_instrument(self) -> bool:
        """Whether the protected resource is an instrument."""
        return isinstance(self.__device, Instrument)

    def __getattr__(self, name):
        """Dynamically wraps methods to enforce safety checks."""
        if name.startswith("_"):
            raise SafetyLimitError("Raw device internals are not publicly accessible.")
        if name in _RAW_COMMAND_METHODS:
            return self._reject_unvalidated_command(name)
        orig = getattr(self.__device, name)

        if name == "channel" and self.__role in {
            "stimulus",
            "source_measure",
            "conditioning",
            "load",
        }:

            def safe_channel(channel: int, *args: Any, **kwargs: Any) -> _SafeChannelFacade:
                return _SafeChannelFacade(self, orig(channel, *args, **kwargs), channel)

            return safe_channel

        if name in {"set_voltage", "set_current"} and self.__role in {
            "stimulus",
            "source_measure",
            "conditioning",
            "load",
        }:
            return (
                self._safe_set_voltage_wrapper(orig)
                if name == "set_voltage"
                else self._safe_set_current_wrapper(orig)
            )
        if name == "force_current" and self.__role == "source_measure":
            return self._safe_force_current_wrapper(orig)
        if name == "output" and self.__role in {
            "stimulus",
            "source_measure",
            "conditioning",
            "load",
        }:
            return self._safe_output_wrapper(orig)
        if name in {"set_amplitude", "set_frequency"} and self.__role == "stimulus":
            return (
                self._safe_set_amplitude_wrapper(orig)
                if name == "set_amplitude"
                else self._safe_set_frequency_wrapper(orig)
            )
        if name == "set_load" and self.__role == "load":
            return self._safe_set_load_wrapper(orig)

        # For any other method, return it unwrapped
        return orig

    def __dir__(self) -> list[str]:
        """Expose public guarded operations without revealing wrapped internals."""
        wrapper_names = {
            name for cls in type(self).__mro__ for name in vars(cls) if not name.startswith("_")
        }
        return sorted((wrapper_names | _public_names(self.__device)) - _RAW_COMMAND_METHODS)

    @staticmethod
    def _finite_value(value: Any, name: str) -> float:
        if isinstance(value, bool):
            raise SafetyLimitError(f"{name} must be a finite number, not a boolean.")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise SafetyLimitError(f"{name} must be a finite number.") from exc
        if not math.isfinite(numeric):
            raise SafetyLimitError(f"{name} must be a finite number.")
        return numeric

    def _check_channel_limit(self, channel: int, name: str, value: Any) -> None:
        numeric = self._finite_value(value, name)
        channels = self.__safety_limits.channels if self.__safety_limits else None
        limits = channels.get(channel) if channels else None
        bound = getattr(limits, name, None) if limits is not None else None
        if not bound:
            return
        if "min" in bound and numeric < bound["min"]:
            raise SafetyLimitError(
                f"Refusing to set {name} {numeric}, which is below the safety limit of {bound['min']}."
            )
        if "max" in bound and numeric > bound["max"]:
            raise SafetyLimitError(
                f"Refusing to set {name} {numeric}, which is above the safety limit of {bound['max']}."
            )
        if "max_abs" in bound and abs(numeric) > bound["max_abs"]:
            raise SafetyLimitError(
                f"Refusing to set {name} {numeric}, whose absolute value is above the safety limit of {bound['max_abs']}."
            )

    def _check_load_limit(self, value: Any) -> None:
        numeric = self._finite_value(value, "load")
        bound = self.__safety_limits.load if self.__safety_limits else None
        if not bound:
            return
        if "min" in bound and numeric < bound["min"]:
            raise SafetyLimitError(
                f"Refusing to set load to {numeric}, which is below the safety limit of {bound['min']}."
            )
        if "max" in bound and numeric > bound["max"]:
            raise SafetyLimitError(
                f"Refusing to set load to {numeric}, which is above the safety limit of {bound['max']}."
            )
        if "max_abs" in bound and abs(numeric) > bound["max_abs"]:
            raise SafetyLimitError(
                f"Refusing to set load to {numeric}, whose absolute value is above the safety limit of {bound['max_abs']}."
            )

    def _preflight_channel(
        self,
        channel: int,
        *,
        voltage: Any = None,
        current_limit: Any = None,
        current: Any = None,
        voltage_compliance: Any = None,
    ) -> None:
        if voltage is not None:
            self._check_channel_limit(channel, "voltage", voltage)
        if current_limit is not None:
            current_limit_value = self._finite_value(current_limit, "current_limit")
            if current_limit_value < 0:
                raise SafetyLimitError("current_limit must be non-negative.")
            self._check_channel_limit(channel, "current", current_limit)
        if current is not None:
            self._check_channel_limit(channel, "current", current)
        if voltage_compliance is not None:
            self._check_channel_limit(channel, "voltage", voltage_compliance)
        validator = getattr(self.__device, "validate_channel_settings", None)
        if callable(validator):
            kwargs = {
                key: value
                for key, value in {
                    "voltage": voltage,
                    "current_limit": current_limit,
                    "current": current,
                    "voltage_compliance": voltage_compliance,
                }.items()
                if value is not None
            }
            if kwargs:
                validator(channel, **kwargs)

    def _cached_channel_settings(self, channel: int) -> dict[str, Any] | None:
        getter = getattr(self.__device, "cached_get_channel_configuration", None)
        if not callable(getter):
            return None
        settings = getter(channel)
        if settings is None:
            return None
        if hasattr(settings, "model_dump"):
            settings = settings.model_dump()
        elif hasattr(settings, "__dict__") and not isinstance(settings, dict):
            settings = vars(settings)
        if not isinstance(settings, dict):
            raise SafetyLimitError("Device returned invalid cached channel configuration.")
        return settings

    def _preflight_output(self, channel: int) -> None:
        settings = self._cached_channel_settings(channel)
        if settings is None:
            return
        self._preflight_channel(
            channel,
            voltage=settings.get("voltage"),
            current_limit=settings.get("current_limit"),
            current=settings.get("current"),
            voltage_compliance=settings.get("voltage_compliance"),
        )

    def _reject_unvalidated_command(self, method_name: str):
        """Fail closed for raw commands that bypass operation-level limits."""

        def reject(*_args, **_kwargs):
            command_kind = (
                "Raw" if method_name in {"write", "query", "query_raw"} else "Unvalidated"
            )
            raise SafetyLimitError(
                f"{command_kind} {method_name} commands are disabled for safety-limited device "
                f"'{self.__device.config.model}'. Use a validated device operation instead."
            )

        return reject

    def _safe_set_voltage_wrapper(self, orig_method):
        """Wraps set_voltage method with safety checks."""

        def safe_set_voltage(channel, voltage, *a, **k):
            self._check_set_voltage_limit(channel, voltage)
            # If safe, call the original method
            self._preflight_channel(channel, voltage=voltage)
            return orig_method(channel, voltage, *a, **k)

        return safe_set_voltage

    def _check_set_voltage_limit(self, channel: int, voltage: float) -> None:
        """Check a configured channel voltage cap without writing."""
        max_v = None
        if self.__safety_limits and self.__safety_limits.channels:
            ch_limits = self.__safety_limits.channels.get(channel)
            if ch_limits and ch_limits.voltage and "max" in ch_limits.voltage:
                max_v = ch_limits.voltage["max"]
        if max_v is not None and voltage > max_v:
            raise SafetyLimitError(
                f"Refusing to set voltage {voltage}V, which is above the safety limit of {max_v}V."
            )

    def _safe_set_current_wrapper(self, orig_method):
        """Wraps set_current method with safety checks."""

        def safe_set_current(channel, current=None, *a, **k):
            if "current_limit" in k:
                if current is not None:
                    raise TypeError(
                        "Specify current compliance once, using current or current_limit."
                    )
                current = k.pop("current_limit")
            if current is None:
                raise TypeError("A current compliance value is required.")
            self._preflight_channel(channel, current_limit=current)
            self._check_set_current_limit(channel, current)
            return orig_method(channel, current, *a, **k)

        return safe_set_current

    def _check_set_current_limit(self, channel: int, current: float) -> None:
        """Check a configured channel current cap without writing."""
        max_c = None
        if self.__safety_limits and self.__safety_limits.channels:
            ch_limits = self.__safety_limits.channels.get(channel)
            if ch_limits and ch_limits.current and "max" in ch_limits.current:
                max_c = ch_limits.current["max"]
        if max_c is not None and current > max_c:
            raise SafetyLimitError(
                f"Refusing to set current {current}A, which is above the safety limit of {max_c}A."
            )

    def _safe_set_amplitude_wrapper(self, orig_method):
        """Wraps set_amplitude method with safety checks."""

        def safe_set_amplitude(channel, amplitude, *a, **k):
            self._check_channel_limit(channel, "amplitude", amplitude)
            return orig_method(channel, amplitude, *a, **k)

        return safe_set_amplitude

    def _safe_set_frequency_wrapper(self, orig_method):
        """Wraps set_frequency method with safety checks."""

        def safe_set_frequency(channel, frequency, *a, **k):
            self._check_channel_limit(channel, "frequency", frequency)
            return orig_method(channel, frequency, *a, **k)

        return safe_set_frequency

    def _safe_set_load_wrapper(self, orig_method):
        """Wraps set_load method with safety checks for DC Active Loads."""

        def safe_set_load(value, *a, **k):
            self._check_load_limit(value)
            return orig_method(value, *a, **k)

        return safe_set_load

    def _safe_force_current_wrapper(self, orig_method):
        def safe_force_current(channel, current, voltage_compliance, *a, **k):
            self._preflight_channel(channel, current=current, voltage_compliance=voltage_compliance)
            return orig_method(channel, current, voltage_compliance, *a, **k)

        return safe_force_current

    def _safe_output_wrapper(self, orig_method):
        def safe_output(channel, state=True, *a, **k):
            channels = [channel] if isinstance(channel, int) else list(channel)
            if state:
                for item in channels:
                    self._preflight_output(item)
            return orig_method(channel, state, *a, **k)

        return safe_output


class Bench:
    """Manages a collection of test devices as a single entity.

    The `Bench` class is the primary entry point for interacting with a test setup
    defined in a YAML configuration file. It handles:
    - Loading and validating the bench configuration.
    - Initializing and connecting to all specified devices.
    - Wrapping devices with safety limit enforcement where specified.
    - Running pre- and post-experiment automation hooks.
    - Providing easy access to devices by their aliases (e.g., `bench.psu1`).
    - Exposing traceability and planning information from the config.
    """

    def __init__(
        self,
        config: BenchConfigExtended,
        *,
        sim_session: Any | None = None,
        backend_resources: BackendResourceScope | None = None,
        prepared_measurements: PreparedMeasurementPlan | None = None,
        base_path: Path | None = None,
    ):
        self._config = config
        self._backend_resources = backend_resources
        provider_sim_session = (
            backend_resources.get("circuit_sim") if backend_resources is not None else None
        )
        self._sim_session = sim_session if sim_session is not None else provider_sim_session
        self._base_path = base_path
        self._device_instances: dict[str, Device] = {}
        self._instrument_instances: dict[str, Instrument[Any]] = {}
        self._device_wrappers: dict[str, Any] = {}
        self._channel_config: dict[str, list[int]] = {}
        prepared_measurements = prepared_measurements or prepare_declared_measurements(
            config, base_path=base_path
        )
        raise_for_declared_measurement_errors(prepared_measurements.errors)
        self._accessories: dict[str, BoundAccessory] = prepared_measurements.bound_accessories
        self._experiment: Experiment | None = None
        self._db: MeasurementDatabase | None = None
        self._opened_successfully = False
        self._run_automation_on_close = True
        self._closed = False

    @classmethod
    def open(
        cls,
        filepath: str | Path | dict[str, Any],
        *,
        aliases: set[str] | None = None,
        start_experiment: bool = True,
        force_simulation: bool = False,
    ) -> "Bench":
        """Loads, validates, and initializes a bench from a YAML configuration file.

        This class method acts as the main factory for creating a `Bench` instance.
        It orchestrates the loading of the YAML file, the execution of any custom
        validation rules, and the initialization of all devices.

        Args:
            filepath: The path to the bench.yaml configuration file.
            aliases: Limit the session to these resource aliases.
            start_experiment: False creates a lazy device session without
                startup reset, automation hooks, measurement plans, or experiment/database setup.
            force_simulation: Admit only built-in simulators and reject automation hooks.

        Returns:
            A fully initialized `Bench` instance, ready for use.

        Raises:
            FileNotFoundError: If the specified YAML file doesn't exist.
            ValidationError: If the configuration fails validation.
            InstrumentConfigurationError: If device configuration is invalid.
        """
        logger.info(f"Loading bench configuration from {filepath}")
        base_path = Path(filepath).parent if isinstance(filepath, str | Path) else None
        config = load_bench_yaml(filepath)
        if force_simulation or config.simulation_only:
            from .config.simulation_only import normalize_simulation_config
            from .devices.registry import builtin_simulation_scope

            with builtin_simulation_scope():
                config = normalize_simulation_config(config, base_path=base_path)
                return cls._open_config(
                    config, base_path=base_path, aliases=aliases, start_experiment=start_experiment
                )
        return cls._open_config(
            config, base_path=base_path, aliases=aliases, start_experiment=start_experiment
        )

    @classmethod
    def _open_config(
        cls,
        config: BenchConfigExtended,
        *,
        base_path: Path | None,
        aliases: set[str] | None,
        start_experiment: bool,
    ) -> "Bench":
        if aliases is not None:
            unknown = aliases - (set(config.devices) | set(config.instruments))
            if not aliases or unknown:
                raise ValueError(f"Unknown or empty resource selection: {sorted(unknown)}")
        if (
            base_path is None
            and config.sim_circuit is not None
            and aliases is None
            and start_experiment
        ):
            raise InstrumentConfigurationError(
                "sim_circuit",
                "Bench.open() requires a filesystem path for sim_circuit netlists.",
            )

        # Run custom validations
        logger.debug("Running custom validations on bench configuration")
        context = build_validation_context(config)
        run_custom_validations(config, context)
        if aliases is not None or not start_experiment:
            config = config.model_copy(deep=True)
            if aliases is not None:
                config.devices = {
                    key: entry for key, entry in config.devices.items() if key in aliases
                }
                config.instruments = {
                    key: entry for key, entry in config.instruments.items() if key in aliases
                }
            if not start_experiment:
                config.measurement_plan = None
                config.accessories = {}
                config.routes = {}
                config.automation = None
                config.experiment = None
                config.continue_on_device_error = False
        prepared_measurements = prepare_declared_measurements(config, base_path=base_path)
        raise_for_declared_measurement_errors(prepared_measurements.errors)

        if config.simulation_only:
            from .config.bench_loader import CircuitSimBackendProvider

            backend_resources = BackendResourceScope()
            if config.sim_circuit is not None and any(
                (entry.backend or {}).get("type") == "circuit_sim"
                for entry in [*config.devices.values(), *config.instruments.values()]
            ):
                provider = CircuitSimBackendProvider()
                backend_resources.add(
                    "circuit_sim", provider, provider.prepare(config, base_path=base_path)
                )
        elif aliases is not None or not start_experiment:
            backend_types = cls._required_backend_types(config, base_path)
            backend_resources = prepare_backend_resources(
                config, base_path=base_path, backend_types=backend_types
            )
        else:
            backend_resources = prepare_backend_resources(config, base_path=base_path)
        bench: Bench | None = None
        try:
            bench = cls(
                config,
                backend_resources=backend_resources,
                prepared_measurements=prepared_measurements,
                base_path=base_path,
            )
            bench._run_automation_on_close = start_experiment and not config.simulation_only
            bench._initialize_devices(connect=start_experiment)
            if start_experiment:
                if config.reset_on_open:
                    bench.reset()
                if not config.simulation_only:
                    bench._run_automation_hook("pre_experiment")
                bench.initialize_experiment()
                bench.initialize_database()
        except BaseException:
            # A failed or interrupted open never runs the post-experiment hook.
            # Preserve the primary error if cleanup also fails.
            if bench is not None:
                try:
                    bench._close_resources(run_post_experiment=False)
                except Exception:
                    logger.exception("Bench cleanup after failed open also failed")
            else:  # pragma: no cover - defensive constructor-failure cleanup
                try:
                    backend_resources.close()
                except Exception as cleanup_error:
                    logger.error("Backend resource cleanup failed: %s", cleanup_error)
            raise

        bench._opened_successfully = True
        logger.info(f"Bench '{config.bench_name}' initialized successfully")

        return bench

    @staticmethod
    def _load_entry_profile(
        entry: DeviceEntry, base_path: Path | None
    ) -> tuple[DeviceConfig, dict[str, Any]]:
        if entry.device_type == "camera":
            from .config.camera_config import CameraConfig

            model = CameraConfig()
            return model, model.model_dump()
        source = entry.resolved_source(base_path=base_path)
        data = (
            AutoDevice.get_config_from_file(source)
            if isinstance(source, Path)
            else AutoDevice.get_config_from_preset(source)
        )
        model, data, _ = AutoDevice._load_config_model(data, role_override=entry.role)
        return model, data

    @classmethod
    def _required_backend_types(
        cls, config: BenchConfigExtended, base_path: Path | None
    ) -> set[str]:
        result: set[str] = set()
        for entry in [*config.devices.values(), *config.instruments.values()]:
            model, data = cls._load_entry_profile(entry, base_path)
            simulate, hint, override = entry_backend_options(config, entry)
            backend = AutoDevice._resolve_backend_spec(model, data, backend_spec_override=override)
            result.add(
                AutoDevice._select_backend_type(
                    backend_spec=backend,
                    backend_type_hint=hint,
                    simulate=simulate,
                    address=entry.address if entry.address is not None else model.address,
                )
            )
        return result

    def _initialize_devices(self, *, connect: bool = True):
        """Initializes and connects to all devices defined in the config."""
        logger.info("Initializing devices")
        connection_errors = []

        entries: list[tuple[str, DeviceEntry, bool]] = [
            (alias, entry, False) for alias, entry in self._config.devices.items()
        ]
        entries.extend((alias, entry, True) for alias, entry in self._config.instruments.items())

        for alias, entry, must_be_instrument in entries:
            try:
                self._initialize_device(
                    alias, entry, must_be_instrument=must_be_instrument, connect=connect
                )
                logger.info(f"Device '{alias}' initialized successfully")
            except Exception as e:
                error_msg = f"Failed to initialize device '{alias}': {str(e)}"
                logger.error(error_msg)
                connection_errors.append(error_msg)

                # Continue with other devices even if one fails
                if getattr(self._config, "continue_on_device_error", False):
                    logger.warning(
                        f"Failed to initialize device '{alias}'. Continuing with other devices."
                    )
                else:
                    raise

        if connection_errors:
            logger.warning(f"Some devices failed to connect: {len(connection_errors)} errors")

    def _initialize_device(
        self,
        alias: str,
        entry: DeviceEntry | InstrumentEntry,
        *,
        must_be_instrument: bool = False,
        connect: bool = True,
    ):
        """Initialize a single device from its configuration entry."""
        # Determine the final simulation mode
        simulate_flag, backend_type_hint, backend_spec = entry_backend_options(self._config, entry)
        timeout_override_ms = (entry.backend or {}).get("timeout_ms")
        backend_spec_override = dict(backend_spec or {})
        if backend_type_hint == "circuit_sim":
            backend_spec_override.setdefault("instrument_id", alias)

        logger.debug(f"Creating device '{alias}' from {entry.source_kind} '{entry.source}'")
        resolved_backend_spec = backend_spec_override or None
        if entry.device_type == "camera":
            if must_be_instrument:
                raise ValueError("Cameras belong under devices, not instruments.")
            _, data = self._load_entry_profile(entry, self._base_path)
            device = AutoDevice.from_dict(
                data,
                simulate=simulate_flag,
                backend_type_hint=backend_type_hint,
                address_override=entry.address,
                timeout_override_ms=timeout_override_ms,
                backend_spec_override=resolved_backend_spec,
                role_override=entry.role,
            )
        elif entry.file is not None:
            source_path = Path(entry.file)
            if not source_path.is_absolute() and self._base_path is not None:
                source_path = self._base_path / source_path
            device = self._instantiate_device_from_file(
                source_path,
                must_be_instrument=must_be_instrument,
                simulate=simulate_flag,
                backend_type_hint=backend_type_hint,
                address_override=entry.address,
                serial_number=entry.serial_number,
                timeout_override_ms=timeout_override_ms,
                backend_spec_override=resolved_backend_spec,
                role_override=entry.role,
                transport_override=entry.transport,
            )
        elif entry.profile is not None and entry.profile_is_local_file(base_path=self._base_path):
            source_path = Path(entry.profile)
            if not source_path.is_absolute() and self._base_path is not None:
                source_path = self._base_path / source_path
            device = self._instantiate_device_from_file(
                source_path,
                must_be_instrument=must_be_instrument,
                simulate=simulate_flag,
                backend_type_hint=backend_type_hint,
                address_override=entry.address,
                serial_number=entry.serial_number,
                timeout_override_ms=timeout_override_ms,
                backend_spec_override=resolved_backend_spec,
                role_override=entry.role,
                transport_override=entry.transport,
            )
        else:
            device = self._instantiate_device_from_preset(
                entry.profile or "",
                must_be_instrument=must_be_instrument,
                simulate=simulate_flag,
                backend_type_hint=backend_type_hint,
                address_override=entry.address,
                serial_number=entry.serial_number,
                timeout_override_ms=timeout_override_ms,
                backend_spec_override=resolved_backend_spec,
                role_override=entry.role,
                transport_override=entry.transport,
            )

        role = self._resolved_device_role(device, alias)
        if role == "custom":
            warnings.warn(
                f"Device '{alias}' uses custom role; safety and reporting semantics are user-defined.",
                UserWarning,
                stacklevel=2,
            )
        if entry.safety_limits:
            self._validate_safety_limits_for_role(alias, entry.safety_limits, role)

        logger.debug(f"Connecting device '{alias}' to backend")
        try:
            if connect:
                device.connect_backend()
        except Exception:
            # connect_backend() already attempts a disconnect, but a backend may
            # have acquired another resource before raising. close() is the
            # lifecycle backstop for that partially initialized local device.
            try:
                device.close()
            except Exception as close_exc:  # pragma: no cover - defensive logging
                logger.error(
                    "Error closing partially initialized device '%s': %s", alias, close_exc
                )
            raise

        if entry.safety_limits:
            wrapped = SafeDeviceWrapper(device, entry.safety_limits, role)
            logger.debug(f"Device '{alias}' is running with a safety wrapper")
            self._device_instances[alias] = device
            if isinstance(device, Instrument):
                self._instrument_instances[alias] = device
            self._device_wrappers[alias] = wrapped
        else:
            self._device_instances[alias] = device
            if isinstance(device, Instrument):
                self._instrument_instances[alias] = device

        # Keep Bench.reset callable; the alias remains in the resource mappings.
        if alias != "reset":
            setattr(self, alias, self._device_wrappers.get(alias, device))

    def _instantiate_device_from_file(
        self,
        path: Path,
        *,
        must_be_instrument: bool,
        simulate: bool,
        backend_type_hint: str | None,
        address_override: str | None,
        serial_number: str | None,
        timeout_override_ms: int | None,
        backend_spec_override: dict[str, Any] | None,
        role_override: Any | None,
        transport_override: dict[str, Any] | None = None,
    ) -> Device[Any]:
        factory = AutoInstrument if must_be_instrument else AutoDevice
        return factory.from_file(
            path,
            simulate=simulate,
            backend_type_hint=backend_type_hint,
            address_override=address_override,
            serial_number=serial_number,
            timeout_override_ms=timeout_override_ms,
            transport_override=transport_override,
            backend_spec_override=backend_spec_override,
            sim_session=self._sim_session,
            backend_resources=(
                self._backend_resources.resources if self._backend_resources is not None else None
            ),
            role_override=role_override,
        )

    def _instantiate_device_from_preset(
        self,
        preset_key: str,
        *,
        must_be_instrument: bool,
        simulate: bool,
        backend_type_hint: str | None,
        address_override: str | None,
        serial_number: str | None,
        timeout_override_ms: int | None,
        backend_spec_override: dict[str, Any] | None,
        role_override: Any | None,
        transport_override: dict[str, Any] | None = None,
    ) -> Device[Any]:
        factory = AutoInstrument if must_be_instrument else AutoDevice
        return factory.from_preset(
            preset_key,
            simulate=simulate,
            backend_type_hint=backend_type_hint,
            address_override=address_override,
            serial_number=serial_number,
            timeout_override_ms=timeout_override_ms,
            transport_override=transport_override,
            backend_spec_override=backend_spec_override,
            sim_session=self._sim_session,
            backend_resources=(
                self._backend_resources.resources if self._backend_resources is not None else None
            ),
            role_override=role_override,
        )

    def _load_accessories(self, base_path: Path | None = None) -> None:
        prepared = prepare_declared_measurements(self._config, base_path=base_path)
        raise_for_declared_measurement_errors(prepared.errors)
        self._accessories = prepared.bound_accessories

    def _resolved_device_role(self, device: Device, alias: str) -> str:
        role = getattr(getattr(device, "config", None), "role", None)
        if role is None:
            raise InstrumentConfigurationError(alias, "Device config must declare a role.")
        return getattr(role, "value", role)

    def _validate_safety_limits_for_role(self, alias: str, safety_limits: Any, role: str) -> None:
        voltage_current_roles = {"stimulus", "source_measure", "conditioning", "load"}
        amplitude_frequency_roles = {"stimulus"}
        load_roles = {"load"}
        supported_roles = voltage_current_roles | amplitude_frequency_roles | load_roles

        if role not in supported_roles:
            raise InstrumentConfigurationError(
                alias, f"Safety limits are not supported for device role '{role}'."
            )

        for channel, limits in (safety_limits.channels or {}).items():
            if (limits.voltage or limits.current) and role not in voltage_current_roles:
                raise InstrumentConfigurationError(
                    alias,
                    f"Voltage/current safety limits on channel {channel} are not supported for role '{role}'.",
                )
            if (limits.amplitude or limits.frequency) and role not in amplitude_frequency_roles:
                raise InstrumentConfigurationError(
                    alias,
                    f"Amplitude/frequency safety limits on channel {channel} are not supported for role '{role}'.",
                )
        if safety_limits.load and role not in load_roles:
            raise InstrumentConfigurationError(
                alias, f"Load safety limits are not supported for role '{role}'."
            )

    def _run_automation_hook(self, hook: str):
        """Executes automation commands for a given hook (e.g., 'pre_experiment').

        This method runs a series of commands defined in the `automation` section
        of the bench config. It supports running shell commands, Python scripts,
        and device macros.

        Args:
            hook: The name of the hook to run (e.g., "pre_experiment").
        """
        hooks = getattr(self._config.automation, hook, None) if self._config.automation else None
        if not hooks:
            logger.debug(f"No automation hooks defined for '{hook}'")
            return

        logger.info(f"Executing {len(hooks)} automation hooks for '{hook}'")

        for i, cmd in enumerate(hooks, 1):
            logger.debug(f"Running automation hook {i}/{len(hooks)}: {cmd}")

            try:
                if cmd.strip().startswith("python "):
                    self._run_python_script(cmd)
                elif ":" in cmd:
                    self._run_device_macro(cmd)
                else:
                    self._run_shell_command(cmd)
            except Exception as e:
                error_msg = f"Failed to execute automation hook: {cmd}. Error: {str(e)}"
                logger.error(error_msg)
                if not getattr(self._config, "continue_on_automation_error", False):
                    raise

    def _run_python_script(self, cmd: str):
        """Run a Python script as part of an automation hook."""
        tokens = shlex.split(cmd)
        if len(tokens) < 2:
            raise InstrumentMacroError("Python automation hook must include a script or module.")
        logger.info(f"[Automation] Running Python command: {' '.join(tokens[1:])}")

        try:
            result = subprocess.run(
                [sys.executable, *tokens[1:]], check=True, capture_output=True, text=True
            )
            logger.debug(f"Script output: {result.stdout.strip()}")
            if result.stderr:
                logger.warning(f"Script stderr: {result.stderr.strip()}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Script execution failed: {e}")
            if e.stdout:
                logger.debug(f"Script stdout: {e.stdout.strip()}")
            if e.stderr:
                logger.error(f"Script stderr: {e.stderr.strip()}")
            raise

    def _run_shell_command(self, cmd: str):
        """Run a shell command as part of an automation hook."""
        logger.info(f"[Automation] Running shell command: {cmd}")
        tokens = shlex.split(cmd)
        if not tokens:
            return
        if tokens[0] == "echo":
            logger.info("[Automation] %s", " ".join(tokens[1:]))
            return

        try:
            result = subprocess.run(tokens, check=True, capture_output=True, text=True)
            logger.debug(f"Command output: {result.stdout.strip()}")
            if result.stderr:
                logger.warning(f"Command stderr: {result.stderr.strip()}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Command execution failed: {e}")
            if e.stdout:
                logger.debug(f"Command stdout: {e.stdout.strip()}")
            if e.stderr:
                logger.error(f"Command stderr: {e.stderr.strip()}")
            raise

    def _run_device_macro(self, cmd: str):
        """Run a device macro command as part of an automation hook."""
        alias, device_cmd = cmd.split(":", 1)
        alias = alias.strip()
        device_cmd = device_cmd.strip()

        device = self._device_wrappers.get(alias) or self._device_instances.get(alias)
        if device is None:
            error_msg = f"Device '{alias}' not found for macro '{cmd}'"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg)

        logger.info(f"[Automation] Running device macro: {alias}: {device_cmd}")

        if device_cmd.lower() == "output all off":
            self._execute_output_all_off(device, alias)
        elif device_cmd.lower() == "autoscale":
            self._execute_autoscale(device, alias)
        else:
            self._execute_custom_macro(device, alias, device_cmd)

    def _execute_output_all_off(self, device, alias: str):
        """Execute the 'output all OFF' macro for a device."""
        if not hasattr(device, "output"):
            error_msg = f"Device '{alias}' does not support 'output' method"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg)

        channels = self._channel_config.get(alias, range(1, 4))

        errors = []
        for ch in channels:
            try:
                logger.debug(f"Turning off output for {alias} channel {ch}")
                device.output(ch, False)
            except Exception as e:
                error_msg = f"Failed to turn off output for {alias} channel {ch}: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)

        if errors:
            logger.warning(f"{len(errors)} errors occurred while turning off outputs")
            if not getattr(self._config, "continue_on_automation_error", False):
                raise InstrumentMacroError(f"Failed to turn off all outputs for '{alias}'")

    def _execute_autoscale(self, device, alias: str):
        """Execute the 'autoscale' macro for a device."""
        if not hasattr(device, "auto_scale"):
            error_msg = f"Device '{alias}' does not support 'auto_scale' method"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg)

        try:
            logger.debug(f"Executing auto scale for {alias}")
            device.auto_scale()
        except Exception as e:
            error_msg = f"Failed to autoscale for {alias}: {str(e)}"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg) from e

    def _execute_custom_macro(self, inst, alias: str, macro: str):
        """Execute a custom macro command."""
        logger.warning(f"Unknown macro for {alias}: {macro}. Custom macros not implemented.")

    def reset(self) -> None:
        """Reset supported bound instruments, stopping on the first failure."""
        from .camera import Camera
        from .instruments.PowerSupply import PowerSupply
        from .motion import MotionDevice

        for alias, instrument in self._instrument_instances.items():
            if isinstance(instrument, (Camera, MotionDevice)):
                continue
            # Both built-in implementations below resolve this exact profile alias.
            if type(instrument).reset in (
                Instrument.reset,
                PowerSupply.reset,
            ) and not instrument.has_profile_alias("reset"):
                logger.debug("Skipping reset for '%s': no reset operation", alias)
                continue
            device = self._device_wrappers.get(alias, instrument)
            try:
                device.reset()
            except Exception as exc:
                raise RuntimeError(f"Bench reset failed for '{alias}': {exc}") from exc

    def close_all(self):
        """Runs post-experiment hooks and closes all device connections."""
        self._close_resources(
            run_post_experiment=self._opened_successfully and self._run_automation_on_close
        )

    def _close_resources(self, *, run_post_experiment: bool) -> None:
        """Close owned resources once, optionally running the successful-open hook."""
        if self._closed:
            return
        self._closed = True
        logger.info("Closing bench and running post-experiment hooks")

        if run_post_experiment:
            try:
                self._run_automation_hook("post_experiment")
            except Exception as e:
                logger.error(f"Error in post-experiment hooks: {str(e)}")

        logger.debug("Closing device connections")
        errors: list[Exception] = []
        for device in self._device_instances.values():
            if hasattr(device, "close"):
                try:
                    device.close()
                except Exception as exc:  # pragma: no cover - defensive logging
                    errors.append(exc)
        self._device_instances.clear()
        self._instrument_instances.clear()
        self._device_wrappers.clear()

        if self._db is not None:
            try:
                self._db.close()
            except Exception as exc:  # pragma: no cover - defensive logging
                errors.append(exc)
            self._db = None

        provider_sim_session = (
            self._backend_resources.get("circuit_sim")
            if self._backend_resources is not None
            else None
        )
        if self._backend_resources is not None:
            try:
                self._backend_resources.close()
            except Exception as exc:  # pragma: no cover - defensive logging
                errors.append(exc)
            self._backend_resources = None

        # Direct constructor users may still pass a legacy shared session. Provider-owned
        # sessions are closed by the scope above and must not be closed twice.
        if self._sim_session is not None and self._sim_session is not provider_sim_session:
            close_session = getattr(self._sim_session, "close", None)
            if not callable(close_session):
                close_session = getattr(self._sim_session, "disconnect", None)
            if callable(close_session):
                try:
                    close_session()
                except Exception as exc:  # pragma: no cover - defensive logging
                    errors.append(exc)
        self._sim_session = None

        if errors:
            logger.error(f"{len(errors)} errors occurred while closing devices")
            for err in errors:
                logger.error(f"Device close error: {str(err)}")

    def health_check(self) -> dict[str, HealthReport]:
        """Run health checks on all devices that support it.

        Returns:
            A dictionary mapping device aliases to their health reports.
        """
        logger.info("Running health check on all devices")
        health_reports = {}

        for alias, device in self._device_instances.items():
            health_check = getattr(device, "health_check", None)
            if callable(health_check):
                try:
                    logger.debug(f"Running health check for {alias}")
                    health_reports[alias] = health_check()
                except Exception as e:
                    logger.error(f"Health check failed for {alias}: {str(e)}")
                    health_reports[alias] = HealthReport(
                        status=HealthStatus.ERROR, errors=[f"Health check failed: {str(e)}"]
                    )
            else:
                logger.debug(f"Device {alias} does not support health checks")

        return health_reports

    def __enter__(self):
        """Synchronous context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Synchronous context manager exit."""
        self.close_all()

    def __getattr__(self, name: str) -> Device:
        """Access devices by alias."""
        if name in self._device_wrappers:
            return self._device_wrappers[name]
        if name in self._device_instances:
            return self._device_instances[name]
        raise AttributeError(f"The bench has no device with the alias '{name}'.")

    def __dir__(self):
        """Include device aliases in dir() output for autocomplete."""
        return list(super().__dir__()) + list(self._device_instances.keys())

    @property
    def name(self) -> str:
        """Bench name from configuration."""
        return self._config.bench_name

    @property
    def description(self) -> str | None:
        """Bench description from configuration."""
        return self._config.description

    @property
    def version(self) -> str | None:
        """Bench version from configuration."""
        return self._config.version

    @property
    def devices(self) -> dict[str, Any]:
        """All bench resources keyed by alias."""
        return self._public_resources()

    @property
    def resources(self) -> dict[str, Any]:
        """Provides programmatic access to all bench resources."""
        return self._public_resources()

    def _public_resources(self) -> dict[str, Any]:
        """Return the canonical guarded handle for every public resource."""
        return {
            alias: self._device_wrappers.get(alias, device)
            for alias, device in self._device_instances.items()
        }

    @property
    def support_devices(self) -> dict[str, Any]:
        """Provides programmatic access to non-instrument device instances."""
        return {
            alias: self._device_wrappers.get(alias, device)
            for alias, device in self._device_instances.items()
            if not isinstance(device, Instrument)
        }

    @property
    def instruments(self) -> dict[str, Any]:
        """Provides programmatic access to device instances that are instruments."""
        return {
            alias: self._device_wrappers.get(alias, device)
            for alias, device in self._instrument_instances.items()
        }

    @property
    def experiment(self) -> Experiment | None:
        """Access the managed Experiment object."""
        return self._experiment

    @property
    def db(self) -> MeasurementDatabase | None:
        """Access the managed MeasurementDatabase object."""
        return self._db

    def initialize_experiment(self):
        """Create an Experiment object from the bench configuration."""
        if self._config.experiment:
            self._experiment = Experiment(
                name=self._config.experiment.title,
                description=self._config.experiment.description,
                notes=self._config.experiment.notes or "",
            )
            logger.info(f"Initialized experiment '{self._config.experiment.title}'")

    def initialize_database(self, db_path: str | Path | None = None):
        """Initialize the database if a path is provided in the config or arguments."""
        db_path = db_path or (
            self._config.experiment.database_path if self._config.experiment else None
        )
        if db_path:
            self._db = MeasurementDatabase(db_path)
            logger.info(f"Connected to database at '{db_path}'")

    def save_experiment(self, notes: str = "") -> str | None:
        """Save the current experiment to the database.

        Args:
            notes: Optional notes to add to the experiment before saving.

        Returns:
            The codename of the saved experiment, or None if not saved.
        """
        if self._experiment and self._db:
            logger.info(f"Saving experiment '{self._experiment.name}' to database")
            return self._db.store_experiment(None, self._experiment, notes=notes)
        elif not self._db:
            logger.warning("No database is configured. Experiment will not be saved.")
        return None

    def measurement(self, name: str) -> "DeclaredMeasurement":
        """Look up a measurement declared in the bench descriptor by name."""
        for entry in self._config.measurement_plan or []:
            if entry.name == name:
                if entry.execution_target is None:
                    raise ValueError(
                        f"Measurement plan entry '{name}' is descriptive, not executable."
                    )
                return DeclaredMeasurement(self, entry)
        raise KeyError(f"No measurement_plan entry named '{name}'.")

    def describe_measurement(self, name: str) -> str:
        """Describe a declared measurement without executing it."""

        for entry in self._config.measurement_plan or []:
            if entry.name == name:
                return describe_declared_measurement(
                    entry,
                    self._accessories,
                    self._config.routes,
                )
        raise KeyError(f"No measurement_plan entry named '{name}'.")

    def measurement_chain(self, name: str) -> MeasurementChain:
        """Return the explicit accessory chain for a declared measurement."""

        return self.measurement(name).chain

    def measure(self, name: str):
        """Execute a declared, accessory-aware measurement from measurement_plan."""

        return self.measurement(name).measure()

    def route(self, name: str) -> "DeclaredRoute":
        """Look up a signal route declared in the bench descriptor by name."""
        if name in self._config.routes:
            return DeclaredRoute(self, name)
        raise KeyError(f"No route named '{name}'.")

    def _measurement_chain_for(self, entry: MeasurementPlanEntry):
        return measurement_chain_for(entry, self._accessories)

    def _execute_declared_measurement(self, entry: MeasurementPlanEntry):
        return execute_declared_measurement(self, entry, self._accessories)

    # --- Accessors for traceability, measurement plan, etc. ---
    @property
    def traceability(self):
        """Access traceability information."""
        return self._config.traceability

    @property
    def measurement_plan(self):
        """Access measurement plan."""
        return self._config.measurement_plan

    @property
    def experiment_notes(self):
        """Access experiment notes."""
        return self._config.experiment.notes if self._config.experiment else None

    @property
    def changelog(self):
        """Access changelog."""
        return self._config.changelog

    @property
    def simulate(self) -> bool:
        """Whether the bench is in simulation mode."""
        return bool(self._config.simulate)

    @property
    def automation(self):
        """Access automation hooks configuration."""
        return self._config.automation

    @property
    def safety_limits(self):
        """Access safety limits configuration."""
        return {
            alias: entry.safety_limits
            for alias, entry in (self._config.devices | self._config.instruments).items()
            if entry.safety_limits is not None
        }


class DeclaredMeasurement:
    """Executable measurement_plan entry bound to a Bench."""

    def __init__(self, bench: Bench, entry: MeasurementPlanEntry):
        self._bench = bench
        self._entry = entry

    @property
    def chain(self) -> MeasurementChain:
        """Return the measurement chain this declaration builds."""
        return self._bench._measurement_chain_for(self._entry)

    def measure(self):
        """Run this declared measurement and return its result."""
        return self._bench._execute_declared_measurement(self._entry)

    def apply(self, result: Any):
        """Apply this measurement's corrections to an already captured result."""
        return self.chain.apply(result)

    def describe(self) -> str:
        """Return a human-readable description of this measurement declaration."""
        return describe_declared_measurement(
            self._entry,
            self._bench._accessories,
            self._bench._config.routes,
        )


class DeclaredRoute:
    """Dry-run route declaration bound to a Bench."""

    def __init__(self, bench: Bench, name: str):
        self._bench = bench
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self):
        return self._bench._config.routes[self._name]

    @property
    def device(self) -> str | None:
        return self.config.device

    @property
    def connects(self):
        return self.config.connects

    @property
    def description(self) -> str | None:
        return self.config.description

    @property
    def settling_time_s(self) -> float | None:
        return self.config.settling_time_s

    @property
    def exclusive_group(self) -> str | None:
        return self.config.exclusive_group

    def _switch(self) -> SwitchMatrixDevice:
        if self.device is None:
            raise NotImplementedError(
                "This route has no switching device; it is a dry-run physical declaration."
            )
        device = getattr(self._bench, self.device)
        if not isinstance(device, SwitchMatrixDevice):
            raise NotImplementedError(f"Route device '{self.device}' is not a SwitchMatrixDevice.")
        return device

    def describe(self) -> str:
        """Return a human-readable description of this signal route."""
        return describe_declared_route(self._name, self._bench._config.routes[self._name])

    def apply(self, *, safety_context: dict[str, Any] | None = None) -> None:
        """Switch the bench hardware to this signal route."""
        device = self._switch()
        # Command formatting/path validation is deliberately performed before
        # the first state-changing operation.  Verification is a separate
        # fresh readback operation and is never represented by this method.
        device.validate_route(self.config, name=self._name)
        device.apply_route(self._name, self.config, safety_context=safety_context)

    def open(self, *, safety_context: dict[str, Any] | None = None) -> None:
        device = self._switch()
        device.preflight_route(
            self.config,
            name=self._name,
            safety_context=safety_context,
            expected_connected=False,
        )
        device.open_route(self.config, name=self._name, safety_context=safety_context)

    def verify(self):
        return self._switch().verify_route(self.config, name=self._name)

    def verify_open(self):
        return self._switch().verify_open(self.config, name=self._name)

    def preflight_recipe(self, *, safety_context: dict[str, Any] | None = None):
        return self._switch().preflight_recipe(
            self.config, name=self._name, safety_context=safety_context
        )
