import asyncio
import logging
from pathlib import Path
from typing import Union, Dict, Any, Optional, List, Sequence, Type
import subprocess
import sys
import warnings
from .config.bench_loader import load_bench_yaml, build_validation_context, run_custom_validations
from .config.bench_config import BenchConfigExtended, InstrumentEntry
from .instruments import AutoInstrument
from .instruments.instrument import Instrument
from .common.health import HealthReport, HealthStatus
from .experiments.experiments import Experiment
from .experiments.database import MeasurementDatabase

# Configure logging
logger = logging.getLogger("pytestlab.bench")

class SafetyLimitError(Exception):
    """Raised when an operation violates safety limits."""
    pass

class InstrumentMacroError(Exception):
    """Raised when an automation macro fails to execute."""
    pass

class SafeInstrumentWrapper:
    """Wraps an instrument to enforce safety limits defined in the bench config.

    This class acts as a proxy to an underlying instrument object. It intercepts
    calls to methods that could be dangerous (like `set_voltage` on a power
    supply) and checks them against the defined safety limits before passing
    the call to the actual instrument. This helps prevent accidental damage to
    equipment or the device under test.

    Attributes:
        _inst: The actual instrument instance being wrapped.
        _safety_limits: The safety limit configuration for this instrument.
        _instrument_type: Type of instrument being wrapped (e.g., 'power_supply', 'waveform_generator').
    """
    def __init__(self, instrument: Instrument, safety_limits: Any, instrument_type: str = None):
        self._inst = instrument
        self._safety_limits = safety_limits
        self._instrument_type = instrument_type or self._detect_instrument_type()

    def _detect_instrument_type(self) -> str:
        """Attempt to detect instrument type based on available methods."""
        if hasattr(self._inst, "set_voltage") and hasattr(self._inst, "set_current"):
            return "power_supply"
        elif hasattr(self._inst, "set_frequency") and hasattr(self._inst, "set_amplitude"):
            return "waveform_generator"
        elif hasattr(self._inst, "set_load") and hasattr(self._inst, "set_mode"):
            return "dc_active_load"
        return "unknown"

    def __getattr__(self, name):
        """Dynamically wraps methods to enforce safety checks."""
        orig = getattr(self._inst, name)
        
        # Power Supply safety limits
        if self._instrument_type == "power_supply":
            if name == "set_voltage":
                return self._safe_set_voltage_wrapper(orig)
            elif name == "set_current":
                return self._safe_set_current_wrapper(orig)
        
        # Waveform Generator safety limits
        elif self._instrument_type == "waveform_generator":
            if name == "set_amplitude":
                return self._safe_set_amplitude_wrapper(orig)
            elif name == "set_frequency":
                return self._safe_set_frequency_wrapper(orig)
        
        # DC Active Load safety limits
        elif self._instrument_type == "dc_active_load":
            if name == "set_load":
                return self._safe_set_load_wrapper(orig)
        
        # For any other method, return it unwrapped
        return orig

    def _safe_set_voltage_wrapper(self, orig_method):
        """Wraps set_voltage method with safety checks."""
        async def safe_set_voltage(channel, voltage, *a, **k):
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
            return await orig_method(channel, voltage, *a, **k)
        return safe_set_voltage

    def _safe_set_current_wrapper(self, orig_method):
        """Wraps set_current method with safety checks."""
        async def safe_set_current(channel, current, *a, **k):
            max_c = None
            if self._safety_limits and self._safety_limits.channels:
                ch_limits = self._safety_limits.channels.get(channel)
                if ch_limits and ch_limits.current and "max" in ch_limits.current:
                    max_c = ch_limits.current["max"]
            if max_c is not None and current > max_c:
                raise SafetyLimitError(
                    f"Refusing to set current {current}A, which is above the safety limit of {max_c}A."
                )
            return await orig_method(channel, current, *a, **k)
        return safe_set_current

    def _safe_set_amplitude_wrapper(self, orig_method):
        """Wraps set_amplitude method with safety checks."""
        async def safe_set_amplitude(channel, amplitude, *a, **k):
            max_amp = None
            if self._safety_limits and self._safety_limits.channels:
                ch_limits = self._safety_limits.channels.get(channel)
                if ch_limits and ch_limits.amplitude and "max" in ch_limits.amplitude:
                    max_amp = ch_limits.amplitude["max"]
            if max_amp is not None and amplitude > max_amp:
                raise SafetyLimitError(
                    f"Refusing to set amplitude {amplitude}V, which is above the safety limit of {max_amp}V."
                )
            return await orig_method(channel, amplitude, *a, **k)
        return safe_set_amplitude

    def _safe_set_frequency_wrapper(self, orig_method):
        """Wraps set_frequency method with safety checks."""
        async def safe_set_frequency(channel, frequency, *a, **k):
            max_freq = None
            if self._safety_limits and self._safety_limits.channels:
                ch_limits = self._safety_limits.channels.get(channel)
                if ch_limits and ch_limits.frequency and "max" in ch_limits.frequency:
                    max_freq = ch_limits.frequency["max"]
            if max_freq is not None and frequency > max_freq:
                raise SafetyLimitError(
                    f"Refusing to set frequency {frequency}Hz, which is above the safety limit of {max_freq}Hz."
                )
            return await orig_method(channel, frequency, *a, **k)
        return safe_set_frequency

    def _safe_set_load_wrapper(self, orig_method):
        """Wraps set_load method with safety checks for DC Active Loads."""
        async def safe_set_load(value, *a, **k):
            max_load = None
            if self._safety_limits and self._safety_limits.load and "max" in self._safety_limits.load:
                max_load = self._safety_limits.load["max"]
            if max_load is not None and value > max_load:
                raise SafetyLimitError(
                    f"Refusing to set load to {value}, which is above the safety limit of {max_load}."
                )
            return await orig_method(value, *a, **k)
        return safe_set_load

class Bench:
    """Manages a collection of test instruments as a single entity.

    The `Bench` class is the primary entry point for interacting with a test setup
    defined in a YAML configuration file. It handles:
    - Loading and validating the bench configuration.
    - Asynchronously initializing and connecting to all specified instruments.
    - Wrapping instruments with safety limit enforcement where specified.
    - Running pre- and post-experiment automation hooks.
    - Providing easy access to instruments by their aliases (e.g., `bench.psu1`).
    - Exposing traceability and planning information from the config.
    """
    def __init__(self, config: BenchConfigExtended):
        self.config = config
        self._instrument_instances: Dict[str, Instrument] = {}
        self._instrument_wrappers: Dict[str, Any] = {}
        self._channel_config: Dict[str, List[int]] = {}  # Stores channel config for each instrument
        self._experiment: Optional[Experiment] = None
        self._db: Optional[MeasurementDatabase] = None

    @classmethod
    async def open(cls, filepath: Union[str, Path]) -> "Bench":
        """Loads, validates, and initializes a bench from a YAML configuration file.

        This class method acts as the main factory for creating a `Bench` instance.
        It orchestrates the loading of the YAML file, the execution of any custom
        validation rules, and the asynchronous initialization of all instruments.

        Args:
            filepath: The path to the bench.yaml configuration file.

        Returns:
            A fully initialized `Bench` instance, ready for use.

        Raises:
            FileNotFoundError: If the specified YAML file doesn't exist.
            ValidationError: If the configuration fails validation.
            InstrumentConfigurationError: If instrument configuration is invalid.
        """
        logger.info(f"Loading bench configuration from {filepath}")
        config = load_bench_yaml(filepath)
        
        # Run custom validations
        logger.debug("Running custom validations on bench configuration")
        context = build_validation_context(config)
        run_custom_validations(config, context)
        
        bench = cls(config)
        await bench._initialize_instruments()
        await bench._run_automation_hook("pre_experiment")
        logger.info(f"Bench '{config.bench_name}' initialized successfully")

        # Initialize the experiment and database
        bench.initialize_experiment()
        bench.initialize_database()
        
        return bench

    async def _initialize_instruments(self):
        """Initializes and connects to all instruments defined in the config."""
        # Importing compliance ensures that the necessary patches are applied
        # before any instruments are created, which might generate results.
        from . import compliance  # noqa: F401
        
        logger.info("Initializing instruments")
        connection_errors = []

        for alias, entry in self.config.instruments.items():
            try:
                await self._initialize_instrument(alias, entry)
                logger.info(f"Instrument '{alias}' initialized successfully")
            except Exception as e:
                error_msg = f"Failed to initialize instrument '{alias}': {str(e)}"
                logger.error(error_msg)
                connection_errors.append(error_msg)
                
                # Continue with other instruments even if one fails
                if getattr(self.config, 'continue_on_instrument_error', False):
                    warnings.warn(f"Failed to initialize instrument '{alias}'. Continuing with other instruments.", UserWarning)
                else:
                    raise

        if connection_errors:
            logger.warning(f"Some instruments failed to connect: {len(connection_errors)} errors")

    async def _initialize_instrument(self, alias: str, entry: InstrumentEntry):
        """Initialize a single instrument from its configuration entry."""
        # Determine the final simulation mode
        simulate_flag = self.config.simulate
        if entry.simulate is not None:
            simulate_flag = entry.simulate

        # Extract backend hints
        backend_type_hint = None
        timeout_override_ms = None
        if entry.backend:
            backend_type_hint = entry.backend.get("type")
            timeout_override_ms = entry.backend.get("timeout_ms")

        # Extract channel configuration if present
        if hasattr(entry, 'channels') and entry.channels:
            self._channel_config[alias] = entry.channels

        # Create instrument instance
        logger.debug(f"Creating instrument '{alias}' from profile '{entry.profile}'")
        instrument = await AutoInstrument.from_config(
            config_source=entry.profile,
            simulate=simulate_flag,
            backend_type_hint=backend_type_hint,
            address_override=entry.address,
            timeout_override_ms=timeout_override_ms
        )
        
        # Connect to the backend
        logger.debug(f"Connecting instrument '{alias}' to backend")
        await instrument.connect_backend()

        # Detect instrument type for safety wrapper
        instrument_type = self._detect_instrument_type(instrument)

        # Apply safety limits if configured
        if entry.safety_limits:
            wrapped = SafeInstrumentWrapper(instrument, entry.safety_limits, instrument_type)
            # Safety wrapper is applied without warning since its use is clear from bench.yaml configuration
            logger.debug(f"Instrument '{alias}' is running with a safety wrapper")
            self._instrument_instances[alias] = instrument
            self._instrument_wrappers[alias] = wrapped
            setattr(self, alias, wrapped)
        else:
            # Otherwise, add the raw instrument to the bench
            self._instrument_instances[alias] = instrument
            setattr(self, alias, instrument)

    def _detect_instrument_type(self, instrument: Instrument) -> str:
        """Detect the type of instrument based on its methods and attributes."""
        if hasattr(instrument, "set_voltage") and hasattr(instrument, "set_current"):
            return "power_supply"
        elif hasattr(instrument, "set_frequency") and hasattr(instrument, "set_amplitude"):
            return "waveform_generator"
        elif hasattr(instrument, "set_load") and hasattr(instrument, "set_mode"):
            return "dc_active_load"
        elif hasattr(instrument, "set_measurement_function") and hasattr(instrument, "measure"):
            return "multimeter"
        elif hasattr(instrument, "set_timebase") and hasattr(instrument, "read_channels"):
            return "oscilloscope"
        return "unknown"

    async def _run_automation_hook(self, hook: str):
        """Executes automation commands for a given hook (e.g., 'pre_experiment').

        This method runs a series of commands defined in the `automation` section
        of the bench config. It supports running shell commands, Python scripts,
        and instrument macros.

        Args:
            hook: The name of the hook to run (e.g., "pre_experiment").
        """
        hooks = getattr(self.config.automation, hook, None) if self.config.automation else None
        if not hooks:
            logger.debug(f"No automation hooks defined for '{hook}'")
            return
            
        logger.info(f"Executing {len(hooks)} automation hooks for '{hook}'")
        
        for i, cmd in enumerate(hooks, 1):
            logger.debug(f"Running automation hook {i}/{len(hooks)}: {cmd}")
            
            try:
                if cmd.strip().startswith("python "):
                    await self._run_python_script(cmd)
                elif ":" in cmd:
                    await self._run_instrument_macro(cmd)
                else:
                    await self._run_shell_command(cmd)
            except Exception as e:
                error_msg = f"Failed to execute automation hook: {cmd}. Error: {str(e)}"
                logger.error(error_msg)
                if not getattr(self.config, 'continue_on_automation_error', False):
                    raise

    async def _run_python_script(self, cmd: str):
        """Run a Python script as part of an automation hook."""
        script = cmd.strip().split(" ", 1)[1]
        logger.info(f"[Automation] Running Python script: {script}")
        
        try:
            result = subprocess.run(
                [sys.executable, script], 
                check=True, 
                capture_output=True, 
                text=True
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

    async def _run_shell_command(self, cmd: str):
        """Run a shell command as part of an automation hook."""
        logger.info(f"[Automation] Running shell command: {cmd}")
        
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                check=True, 
                capture_output=True, 
                text=True
            )
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

    async def _run_instrument_macro(self, cmd: str):
        """Run an instrument macro command as part of an automation hook."""
        alias, instr_cmd = cmd.split(":", 1)
        alias = alias.strip()
        instr_cmd = instr_cmd.strip()
        
        # Get the instrument instance (wrapper or raw)
        inst = self._instrument_wrappers.get(alias) or self._instrument_instances.get(alias)
        if inst is None:
            error_msg = f"Instrument '{alias}' not found for macro '{cmd}'"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg)
            
        logger.info(f"[Automation] Running instrument macro: {alias}: {instr_cmd}")
        
        # Handle common macros
        if instr_cmd.lower() == "output all off":
            await self._execute_output_all_off(inst, alias)
        elif instr_cmd.lower() == "autoscale":
            await self._execute_autoscale(inst, alias)
        else:
            await self._execute_custom_macro(inst, alias, instr_cmd)

    async def _execute_output_all_off(self, inst, alias: str):
        """Execute the 'output all OFF' macro for an instrument."""
        if not hasattr(inst, "output"):
            error_msg = f"Instrument '{alias}' does not support 'output' method"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg)
            
        # Get channels for this instrument from config or use default range
        channels = self._channel_config.get(alias, range(1, 4))
        
        # Turn off all channels
        errors = []
        for ch in channels:
            try:
                logger.debug(f"Turning off output for {alias} channel {ch}")
                await inst.output(ch, False)
            except Exception as e:
                error_msg = f"Failed to turn off output for {alias} channel {ch}: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)
                
        if errors:
            logger.warning(f"{len(errors)} errors occurred while turning off outputs")
            if not getattr(self.config, 'continue_on_automation_error', False):
                raise InstrumentMacroError(f"Failed to turn off all outputs for '{alias}'")

    async def _execute_autoscale(self, inst, alias: str):
        """Execute the 'autoscale' macro for an instrument."""
        if not hasattr(inst, "auto_scale"):
            error_msg = f"Instrument '{alias}' does not support 'auto_scale' method"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg)
            
        try:
            logger.debug(f"Executing auto scale for {alias}")
            await inst.auto_scale()
        except Exception as e:
            error_msg = f"Failed to autoscale for {alias}: {str(e)}"
            logger.error(error_msg)
            raise InstrumentMacroError(error_msg) from e

    async def _execute_custom_macro(self, inst, alias: str, macro: str):
        """Execute a custom macro command."""
        logger.warning(f"Unknown macro for {alias}: {macro}. Custom macros not implemented.")

    async def close_all(self):
        """Runs post-experiment hooks and closes all instrument connections."""
        logger.info("Closing bench and running post-experiment hooks")
        
        try:
            await self._run_automation_hook("post_experiment")
        except Exception as e:
            logger.error(f"Error in post-experiment hooks: {str(e)}")
            
        # Close all instrument connections
        logger.debug("Closing instrument connections")
        close_tasks = [
            inst.close() for inst in self._instrument_instances.values() 
            if hasattr(inst, "close")
        ]
        
        if close_tasks:
            results = await asyncio.gather(*close_tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                logger.error(f"{len(errors)} errors occurred while closing instruments")
                for err in errors:
                    logger.error(f"Instrument close error: {str(err)}")
                    
    async def health_check(self) -> Dict[str, HealthReport]:
        """Run health checks on all instruments that support it.
        
        Returns:
            A dictionary mapping instrument aliases to their health reports.
        """
        logger.info("Running health check on all instruments")
        health_reports = {}
        
        for alias, inst in self._instrument_instances.items():
            if hasattr(inst, "health_check"):
                try:
                    logger.debug(f"Running health check for {alias}")
                    health_reports[alias] = await inst.health_check()
                except Exception as e:
                    logger.error(f"Health check failed for {alias}: {str(e)}")
                    health_reports[alias] = HealthReport(
                        status=HealthStatus.ERROR,
                        messages=[f"Health check failed: {str(e)}"]
                    )
            else:
                logger.debug(f"Instrument {alias} does not support health checks")
                
        return health_reports

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_all()

    def __getattr__(self, name: str) -> Instrument:
        """Access instruments by alias."""
        if name in self._instrument_wrappers:
            return self._instrument_wrappers[name]
        if name in self._instrument_instances:
            return self._instrument_instances[name]
        raise AttributeError(f"The bench has no instrument with the alias '{name}'.")

    def __dir__(self):
        """Include instrument aliases in dir() output for autocomplete."""
        return super().__dir__() + list(self._instrument_instances.keys())

    @property
    def instruments(self) -> Dict[str, Instrument]:
        """Provides programmatic access to all instrument instances.

        Returns:
            A dictionary where keys are instrument aliases and values are the
            corresponding instrument instances.
        """
        return self._instrument_instances

    @property
    def experiment(self) -> Optional[Experiment]:
        """Access the managed Experiment object."""
        return self._experiment

    @property
    def db(self) -> Optional[MeasurementDatabase]:
        """Access the managed MeasurementDatabase object."""
        return self._db

    def initialize_experiment(self):
        """Create an Experiment object from the bench configuration."""
        if self.config.experiment:
            self._experiment = Experiment(
                name=self.config.experiment.title,
                description=self.config.experiment.description,
                notes=self.config.experiment.notes
            )
            logger.info(f"Initialized experiment '{self.config.experiment.title}'")

    def initialize_database(self, db_path: Optional[Union[str, Path]] = None):
        """Initialize the database if a path is provided in the config or arguments."""
        db_path = db_path or (self.config.experiment.database_path if self.config.experiment else None)
        if db_path:
            self._db = MeasurementDatabase(db_path)
            logger.info(f"Connected to database at '{db_path}'")

    async def save_experiment(self, notes: str = "") -> Optional[str]:
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
        return self.config.traceability

    @property
    def measurement_plan(self):
        """Access measurement plan."""
        return self.config.measurement_plan

    @property
    def experiment_notes(self):
        """Access experiment notes."""
        return self.config.experiment.notes if self.config.experiment else None

    @property
    def version(self):
        """Access bench version."""
        return self.config.version

    @property
    def changelog(self):
        """Access changelog."""
        return self.config.changelog