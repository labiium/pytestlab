import logging
import shlex
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

from .common.health import HealthReport
from .common.health import HealthStatus
from .config.bench_config import BenchConfigExtended
from .config.bench_config import DeviceEntry
from .config.bench_config import InstrumentEntry
from .config.bench_loader import build_validation_context
from .config.bench_loader import load_bench_yaml
from .config.bench_loader import load_sim_bench_yaml
from .config.bench_loader import run_custom_validations
from .devices import AutoDevice
from .devices import Device
from .errors import InstrumentConfigurationError
from .experiments import Experiment
from .experiments.database import MeasurementDatabase
from .instruments import AutoInstrument
from .instruments import Instrument

# Configure logging
logger = logging.getLogger("pytestlab.bench")


class SafetyLimitError(Exception):
    """Raised when an operation violates safety limits."""

    pass


class InstrumentMacroError(Exception):
    """Raised when an automation macro fails to execute."""

    pass


class SafeDeviceWrapper:
    """Wraps a device to enforce safety limits defined in the bench config.

    This class acts as a proxy to an underlying device object. It intercepts
        calls to methods that could be dangerous (like `set_voltage` on a power
        supply) and checks them against the defined safety limits before passing
        the call to the actual device. This helps prevent accidental damage to
        equipment or the device under test.

    Attributes:
        _device: The actual device instance being wrapped.
        _safety_limits: The safety limit configuration for this device.
        _device_type: Type of device being wrapped (e.g., 'power_supply', 'waveform_generator').
    """

    def __init__(self, device: Device, safety_limits: Any, role: str):
        self._device = device
        self._safety_limits = safety_limits
        self._role = role

    def __getattr__(self, name):
        """Dynamically wraps methods to enforce safety checks."""
        orig = getattr(self._device, name)

        if name in {"set_voltage", "set_current"} and self._role in {
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
        if name in {"set_amplitude", "set_frequency"} and self._role == "stimulus":
            return (
                self._safe_set_amplitude_wrapper(orig)
                if name == "set_amplitude"
                else self._safe_set_frequency_wrapper(orig)
            )
        if name == "set_load" and self._role == "load":
            return self._safe_set_load_wrapper(orig)

        # For any other method, return it unwrapped
        return orig

    def _safe_set_voltage_wrapper(self, orig_method):
        """Wraps set_voltage method with safety checks."""

        def safe_set_voltage(channel, voltage, *a, **k):
            max_v = None
            # Check if channel-specific voltage limits are defined
            if self._safety_limits and self._safety_limits.channels:
                ch_limits = self._safety_limits.channels.get(channel)
                if ch_limits and ch_limits.voltage and "max" in ch_limits.voltage:
                    max_v = ch_limits.voltage["max"]
            # If a limit is found, check if the requested voltage exceeds it
            if max_v is not None and voltage > max_v:
                raise SafetyLimitError(
                    f"Refusing to set voltage {voltage}V, which is above the safety limit of {max_v}V."
                )
            # If safe, call the original method
            return orig_method(channel, voltage, *a, **k)

        return safe_set_voltage

    def _safe_set_current_wrapper(self, orig_method):
        """Wraps set_current method with safety checks."""

        def safe_set_current(channel, current, *a, **k):
            max_c = None
            if self._safety_limits and self._safety_limits.channels:
                ch_limits = self._safety_limits.channels.get(channel)
                if ch_limits and ch_limits.current and "max" in ch_limits.current:
                    max_c = ch_limits.current["max"]
            if max_c is not None and current > max_c:
                raise SafetyLimitError(
                    f"Refusing to set current {current}A, which is above the safety limit of {max_c}A."
                )
            return orig_method(channel, current, *a, **k)

        return safe_set_current

    def _safe_set_amplitude_wrapper(self, orig_method):
        """Wraps set_amplitude method with safety checks."""

        def safe_set_amplitude(channel, amplitude, *a, **k):
            max_amp = None
            if self._safety_limits and self._safety_limits.channels:
                ch_limits = self._safety_limits.channels.get(channel)
                if ch_limits and ch_limits.amplitude and "max" in ch_limits.amplitude:
                    max_amp = ch_limits.amplitude["max"]
            if max_amp is not None and amplitude > max_amp:
                raise SafetyLimitError(
                    f"Refusing to set amplitude {amplitude}V, which is above the safety limit of {max_amp}V."
                )
            return orig_method(channel, amplitude, *a, **k)

        return safe_set_amplitude

    def _safe_set_frequency_wrapper(self, orig_method):
        """Wraps set_frequency method with safety checks."""

        def safe_set_frequency(channel, frequency, *a, **k):
            max_freq = None
            if self._safety_limits and self._safety_limits.channels:
                ch_limits = self._safety_limits.channels.get(channel)
                if ch_limits and ch_limits.frequency and "max" in ch_limits.frequency:
                    max_freq = ch_limits.frequency["max"]
            if max_freq is not None and frequency > max_freq:
                raise SafetyLimitError(
                    f"Refusing to set frequency {frequency}Hz, which is above the safety limit of {max_freq}Hz."
                )
            return orig_method(channel, frequency, *a, **k)

        return safe_set_frequency

    def _safe_set_load_wrapper(self, orig_method):
        """Wraps set_load method with safety checks for DC Active Loads."""

        def safe_set_load(value, *a, **k):
            max_load = None
            if (
                self._safety_limits
                and self._safety_limits.load
                and "max" in self._safety_limits.load
            ):
                max_load = self._safety_limits.load["max"]
            if max_load is not None and value > max_load:
                raise SafetyLimitError(
                    f"Refusing to set load to {value}, which is above the safety limit of {max_load}."
                )
            return orig_method(value, *a, **k)

        return safe_set_load


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

    def __init__(self, config: BenchConfigExtended, *, sim_session: Any | None = None):
        self._config = config
        self._sim_session = sim_session
        self._device_instances: dict[str, Device] = {}
        self._instrument_instances: dict[str, Instrument[Any]] = {}
        self._device_wrappers: dict[str, Any] = {}
        self._channel_config: dict[str, list[int]] = {}
        self._experiment: Experiment | None = None
        self._db: MeasurementDatabase | None = None

    @classmethod
    def open(cls, filepath: str | Path | dict[str, Any]) -> "Bench":
        """Loads, validates, and initializes a bench from a YAML configuration file.

        This class method acts as the main factory for creating a `Bench` instance.
        It orchestrates the loading of the YAML file, the execution of any custom
        validation rules, and the initialization of all devices.

        Args:
            filepath: The path to the bench.yaml configuration file.

        Returns:
            A fully initialized `Bench` instance, ready for use.

        Raises:
            FileNotFoundError: If the specified YAML file doesn't exist.
            ValidationError: If the configuration fails validation.
            InstrumentConfigurationError: If device configuration is invalid.
        """
        logger.info(f"Loading bench configuration from {filepath}")
        if isinstance(filepath, str | Path):
            config, sim_session = load_sim_bench_yaml(filepath)
        else:
            config = load_bench_yaml(filepath)
            if config.sim_circuit is not None:
                raise InstrumentConfigurationError(
                    "sim_circuit",
                    "Bench.open() requires a filesystem path for sim_circuit netlists.",
                )
            sim_session = None

        # Run custom validations
        logger.debug("Running custom validations on bench configuration")
        context = build_validation_context(config)
        run_custom_validations(config, context)

        bench = cls(config, sim_session=sim_session)
        bench._initialize_devices()
        bench._run_automation_hook("pre_experiment")
        logger.info(f"Bench '{config.bench_name}' initialized successfully")

        # Initialize the experiment and database
        bench.initialize_experiment()
        bench.initialize_database()

        return bench

    def _initialize_devices(self):
        """Initializes and connects to all devices defined in the config."""
        logger.info("Initializing devices")
        connection_errors = []

        entries: list[tuple[str, DeviceEntry, bool]] = [
            (alias, entry, False) for alias, entry in self._config.devices.items()
        ]
        entries.extend((alias, entry, True) for alias, entry in self._config.instruments.items())

        for alias, entry, must_be_instrument in entries:
            try:
                self._initialize_device(alias, entry, must_be_instrument=must_be_instrument)
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
        self, alias: str, entry: DeviceEntry | InstrumentEntry, *, must_be_instrument: bool = False
    ):
        """Initialize a single device from its configuration entry."""
        # Determine the final simulation mode
        simulate_flag = self._config.simulate
        if entry.simulate is not None:
            simulate_flag = entry.simulate

        # Extract backend hints
        backend_type_hint = None
        timeout_override_ms = None
        if entry.backend:
            backend_type_hint = entry.backend.get("type")
            timeout_override_ms = entry.backend.get("timeout_ms")
        backend_spec_override = dict(entry.backend or {})
        if backend_type_hint == "circuit_sim":
            backend_spec_override.setdefault("instrument_id", alias)

        logger.debug(f"Creating device '{alias}' from profile '{entry.profile}'")
        factory = AutoInstrument if must_be_instrument else AutoDevice
        device = factory.from_config(
            config_source=entry.profile,
            simulate=simulate_flag,
            backend_type_hint=backend_type_hint,
            address_override=entry.address,
            serial_number=entry.serial_number,
            timeout_override_ms=timeout_override_ms,
            backend_spec_override=backend_spec_override or None,
            sim_session=self._sim_session,
            role_override=entry.role,
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
        device.connect_backend()

        if entry.safety_limits:
            wrapped = SafeDeviceWrapper(device, entry.safety_limits, role)
            logger.debug(f"Device '{alias}' is running with a safety wrapper")
            self._device_instances[alias] = device
            if isinstance(device, Instrument):
                self._instrument_instances[alias] = device
            self._device_wrappers[alias] = wrapped
            setattr(self, alias, wrapped)
        else:
            self._device_instances[alias] = device
            if isinstance(device, Instrument):
                self._instrument_instances[alias] = device
            setattr(self, alias, device)

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

    def close_all(self):
        """Runs post-experiment hooks and closes all device connections."""
        logger.info("Closing bench and running post-experiment hooks")

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
    def devices(self) -> dict[str, Device]:
        """Compatibility alias for all bench resources.

        Deprecated: in 1.0 this will return support devices only. Use
        ``resources`` for all resources or ``support_devices`` for non-instruments.
        """
        warnings.warn(
            "Bench.devices currently returns all resources but will return support devices only in 1.0; use Bench.resources for all resources.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._device_instances

    @property
    def resources(self) -> dict[str, Device]:
        """Provides programmatic access to all bench resources."""
        return self._device_instances

    @property
    def support_devices(self) -> dict[str, Device]:
        """Provides programmatic access to non-instrument device instances."""
        return {
            alias: device
            for alias, device in self._device_instances.items()
            if not isinstance(device, Instrument)
        }

    @property
    def instruments(self) -> dict[str, Instrument[Any]]:
        """Provides programmatic access to device instances that are instruments."""
        return self._instrument_instances

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
