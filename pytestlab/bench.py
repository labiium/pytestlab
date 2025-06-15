import asyncio
from pathlib import Path
from typing import Union, Dict, Any, Optional
import subprocess
import sys
import warnings
from .config.bench_loader import load_bench_yaml, build_validation_context, run_custom_validations
from .config.bench_config import BenchConfigExtended
from .instruments import AutoInstrument
from .instruments.instrument import Instrument

class SafetyLimitError(Exception):
    """Raised when an operation violates safety limits."""
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
    """
    def __init__(self, instrument: Instrument, safety_limits: Any):
        self._inst = instrument
        self._safety_limits = safety_limits

    def __getattr__(self, name):
        """Dynamically wraps methods to enforce safety checks."""
        orig = getattr(self._inst, name)
        # Currently, only wraps methods for Power Supplies. This can be extended.
        # If the method is 'set_voltage', return a new function that checks limits first.
        if name == "set_voltage":
            async def safe_set_voltage(channel, voltage, *a, **k):
                max_v = None
                # Check if channel-specific voltage limits are defined.
                if self._safety_limits and self._safety_limits.channels:
                    ch_limits = self._safety_limits.channels.get(channel)
                    if ch_limits and ch_limits.voltage and "max" in ch_limits.voltage:
                        max_v = ch_limits.voltage["max"]
                # If a limit is found, check if the requested voltage exceeds it.
                if max_v is not None and voltage > max_v:
                    raise SafetyLimitError(
                        f"Refusing to set voltage {voltage}V, which is above the safety limit of {max_v}V."
                    )
                # If safe, call the original method.
                return await orig(channel, voltage, *a, **k)
            return safe_set_voltage
        # If the method is 'set_current', do the same for current limits.
        if name == "set_current":
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
                return await orig(channel, current, *a, **k)
            return safe_set_current
        # For any other method, return it unwrapped.
        return orig

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
        """
        config = load_bench_yaml(filepath)
        # Run custom validations
        context = build_validation_context(config)
        run_custom_validations(config, context)
        bench = cls(config)
        await bench._initialize_instruments()
        await bench._run_automation_hook("pre_experiment")
        return bench

    async def _initialize_instruments(self):
        """Initializes and connects to all instruments defined in the config."""
        # Importing compliance ensures that the necessary patches are applied
        # before any instruments are created, which might generate results.
        from . import compliance  # noqa: F401

        for alias, entry in self.config.instruments.items():
            # Determine the final simulation mode, with instrument-specific settings
            # overriding the global bench setting.
            simulate_flag = self.config.simulate
            if entry.simulate is not None:
                simulate_flag = entry.simulate

            # Extract backend hints from the configuration.
            backend_type_hint = None
            timeout_override_ms = None
            if entry.backend:
                backend_type_hint = entry.backend.get("type")
                timeout_override_ms = entry.backend.get("timeout_ms")

            # Use AutoInstrument to create the instrument instance from its profile.
            instrument = await AutoInstrument.from_config(
                config_source=entry.profile,
                simulate=simulate_flag,
                backend_type_hint=backend_type_hint,
                address_override=entry.address,
                timeout_override_ms=timeout_override_ms
            )
            await instrument.connect_backend()

            # If safety limits are defined for this instrument, wrap it.
            if entry.safety_limits:
                wrapped = SafeInstrumentWrapper(instrument, entry.safety_limits)
                warnings.warn(f"Instrument '{alias}' is running with a safety wrapper.", UserWarning)
                self._instrument_instances[alias] = instrument
                self._instrument_wrappers[alias] = wrapped
                setattr(self, alias, wrapped)
            else:
                # Otherwise, add the raw instrument to the bench.
                self._instrument_instances[alias] = instrument
                setattr(self, alias, instrument)

    async def _run_automation_hook(self, hook: str):
        """Executes automation commands for a given hook (e.g., 'pre_experiment').

        This method runs a series of commands defined in the `automation` section
        of the bench config. It supports running shell commands, Python scripts,
        and simple instrument macros.

        Args:
            hook: The name of the hook to run (e.g., "pre_experiment").
        """
        hooks = getattr(self.config.automation, hook, None) if self.config.automation else None
        if not hooks:
            return
        for cmd in hooks:
            if cmd.strip().startswith("python "):
                # Run python script
                script = cmd.strip().split(" ", 1)[1]
                print(f"[Automation] Running script: {script}")
                subprocess.run([sys.executable, script], check=True)
            elif ":" in cmd:
                # Instrument macro, e.g., "psu1: output all OFF"
                alias, instr_cmd = cmd.split(":", 1)
                alias = alias.strip()
                instr_cmd = instr_cmd.strip()
                inst = self._instrument_wrappers.get(alias) or self._instrument_instances.get(alias)
                if inst is None:
                    print(f"[Automation] Instrument '{alias}' not found for macro '{cmd}'")
                    continue
                # Very basic macro parser
                if instr_cmd.lower() == "output all off":
                    if hasattr(inst, "output"):
                        # Assume 1-based channels up to 3 for demo, real code should use config
                        for ch in range(1, 4):
                            try:
                                await inst.output(ch, False)
                            except Exception:
                                pass
                elif instr_cmd.lower() == "autoscale":
                    if hasattr(inst, "auto_scale"):
                        await inst.auto_scale()
                else:
                    print(f"[Automation] Unknown macro: {instr_cmd}")
            else:
                # Shell command
                print(f"[Automation] Running shell command: {cmd}")
                subprocess.run(cmd, shell=True, check=True)

    async def close_all(self):
        """Runs post-experiment hooks and closes all instrument connections."""
        await self._run_automation_hook("post_experiment")
        close_tasks = [
            inst.close() for inst in self._instrument_instances.values() if hasattr(inst, "close")
        ]
        await asyncio.gather(*close_tasks)

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