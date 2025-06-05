import asyncio
from pathlib import Path
from typing import Union, Dict, Any, Optional
import subprocess
import sys
from .config.bench_loader import load_bench_yaml, build_validation_context, run_custom_validations
from .config.bench_config import BenchConfigExtended
from .instruments import AutoInstrument
from .instruments.instrument import Instrument

class SafetyLimitError(Exception):
    """Raised when an operation violates safety limits."""
    pass

class SafeInstrumentWrapper:
    """
    Wraps an Instrument to enforce safety_limits from the bench config.
    Only wraps set_voltage/set_current/output for PSU, and similar for others.
    """
    def __init__(self, instrument: Instrument, safety_limits: Any):
        self._inst = instrument
        self._safety_limits = safety_limits

    def __getattr__(self, name):
        orig = getattr(self._inst, name)
        # Wrap set_voltage, set_current, output for PSU
        if name == "set_voltage":
            async def safe_set_voltage(channel, voltage, *a, **k):
                max_v = None
                if self._safety_limits and self._safety_limits.channels:
                    ch_limits = self._safety_limits.channels.get(channel)
                    if ch_limits and ch_limits.voltage and "max" in ch_limits.voltage:
                        max_v = ch_limits.voltage["max"]
                if max_v is not None and voltage > max_v:
                    raise SafetyLimitError(f"Refusing to set voltage {voltage} > safety limit {max_v} V")
                return await orig(channel, voltage, *a, **k)
            return safe_set_voltage
        if name == "set_current":
            async def safe_set_current(channel, current, *a, **k):
                max_c = None
                if self._safety_limits and self._safety_limits.channels:
                    ch_limits = self._safety_limits.channels.get(channel)
                    if ch_limits and ch_limits.current and "max" in ch_limits.current:
                        max_c = ch_limits.current["max"]
                if max_c is not None and current > max_c:
                    raise SafetyLimitError(f"Refusing to set current {current} > safety limit {max_c} A")
                return await orig(channel, current, *a, **k)
            return safe_set_current
        # TODO: Add similar wrappers for other instrument types as needed
        return orig

class Bench:
    """
    Main bench manager class.
    Loads, validates, and manages all instruments in the bench.yaml.
    Enforces safety limits, runs automation hooks, and exposes traceability/plan.
    """
    def __init__(self, config: BenchConfigExtended):
        self.config = config
        self._instrument_instances: Dict[str, Instrument] = {}
        self._instrument_wrappers: Dict[str, Any] = {}

    @classmethod
    async def open(cls, filepath: Union[str, Path]) -> "Bench":
        """Asynchronously load and initialize a bench from a YAML file."""
        config = load_bench_yaml(filepath)
        # Run custom validations
        context = build_validation_context(config)
        run_custom_validations(config, context)
        bench = cls(config)
        await bench._initialize_instruments()
        await bench._run_automation_hook("pre_experiment")
        return bench

    async def _initialize_instruments(self):
        """Initialize all instruments asynchronously."""
        for alias, entry in self.config.instruments.items():
            simulate_flag = self.config.simulate
            if entry.simulate is not None:
                simulate_flag = entry.simulate
            
            # Determine backend type hint from entry.backend
            backend_type_hint = None
            timeout_override_ms = None
            if entry.backend:
                backend_type_hint = entry.backend.get("type")
                timeout_override_ms = entry.backend.get("timeout_ms")
            
            instrument = await AutoInstrument.from_config(
                config_source=entry.profile,
                simulate=simulate_flag,
                backend_type_hint=backend_type_hint,
                address_override=entry.address,
                timeout_override_ms=timeout_override_ms
            )
            await instrument.connect_backend()
            
            # Wrap with safety limits if present
            if entry.safety_limits:
                wrapped = SafeInstrumentWrapper(instrument, entry.safety_limits)
                self._instrument_instances[alias] = instrument
                self._instrument_wrappers[alias] = wrapped
                setattr(self, alias, wrapped)
            else:
                self._instrument_instances[alias] = instrument
                setattr(self, alias, instrument)

    async def _run_automation_hook(self, hook: str):
        """Run automation hooks (pre_experiment or post_experiment)."""
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
        """Close all instruments and run post-experiment hooks."""
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
        raise AttributeError(f"Bench has no instrument '{name}'")

    def __dir__(self):
        """Include instrument aliases in dir() output for autocomplete."""
        return super().__dir__() + list(self._instrument_instances.keys())

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