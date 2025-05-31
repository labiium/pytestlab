# pytestlab/bench.py
import asyncio # For async operations
from pathlib import Path
from typing import Union, Dict, Optional, Any
import yaml
from .config.bench_config import BenchConfig, InstrumentEntry, BackendSettings
from .config.loader import load_profile # Assuming this is sync
from .instruments import AutoInstrument # Assuming this is async
from .instruments.instrument import Instrument # Base instrument type for type hinting

class Bench:
    def __init__(self, config: BenchConfig):
        self.config = config
        self._instrument_instances: Dict[str, Instrument] = {}
        self._initialization_coroutines = [] # For async init

        for alias, entry in self.config.instruments.items():
            # Prepare a coroutine for each instrument's initialization
            coro = self._prepare_instrument_init(alias, entry)
            self._initialization_coroutines.append(coro)
            # For attribute access, we'll set them after async initialization
            # Or, could use a property that awaits if not yet initialized.

    async def _prepare_instrument_init(self, alias: str, entry: InstrumentEntry):
        # Determine effective settings, merging global and per-instrument
        simulate_flag = self.config.simulate
        if entry.simulate is not None: # Per-instrument simulate overrides global
            simulate_flag = entry.simulate

        # Backend settings resolution
        effective_backend_settings = self.config.backend_defaults.model_copy() # Start with global defaults
        if entry.backend: # If per-instrument backend settings are provided
            if entry.backend.type:
                effective_backend_settings.type = entry.backend.type
            if entry.backend.timeout_ms: # Check if timeout_ms is explicitly set
                effective_backend_settings.timeout_ms = entry.backend.timeout_ms
        
        backend_type_hint = effective_backend_settings.type
        address_override = entry.address # Already defaulted to "sim" by Pydantic if None
        timeout_override_ms = effective_backend_settings.timeout_ms

        # Load instrument profile (sync part)
        # load_profile needs to handle keys like "keysight/EDU36311A"
        instrument_config_model = load_profile(entry.profile) 

        # Instantiate (async part)
        instrument_instance = await AutoInstrument.from_config(
            config_source=instrument_config_model,
            simulate=simulate_flag,
            backend_type_hint=backend_type_hint,
            address_override=address_override,
            timeout_override_ms=timeout_override_ms
        )
        await instrument_instance.connect_backend() # Explicitly connect
        self._instrument_instances[alias] = instrument_instance
        setattr(self, alias, instrument_instance) # Make accessible via attribute

    async def initialize_instruments(self):
        """Initializes all instruments defined in the bench config asynchronously."""
        await asyncio.gather(*self._initialization_coroutines)
        self._initialization_coroutines = [] # Clear after execution

    @classmethod
    def from_yaml(cls, filepath: Union[str, Path]) -> 'Bench': # This is sync
        path = Path(filepath)
        with path.open('r') as f:
            yaml_data = yaml.safe_load(f)
        
        # Validate with Pydantic
        bench_config_model = BenchConfig.model_validate(yaml_data)
        return cls(config=bench_config_model)

    # Bench.open() would be an async constructor pattern
    @classmethod
    async def open(cls, filepath: Union[str, Path]) -> 'Bench': # Async factory
        bench_instance = cls.from_yaml(filepath) # Sync part: load and validate config
        await bench_instance.initialize_instruments() # Async part: init instruments
        return bench_instance

    async def close_all(self) -> None:
        close_tasks = [
            instrument.close() for instrument in self._instrument_instances.values() if hasattr(instrument, 'close')
        ]
        await asyncio.gather(*close_tasks)

    async def __aenter__(self) -> 'Bench':
        # await self.initialize_instruments() # Initialization now in open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close_all()

    def __getattr__(self, name: str) -> Instrument:
        if name in self._instrument_instances:
            return self._instrument_instances[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}', or instrument not initialized.")

    def __dir__(self): # For better autocompletion
        return super().__dir__() + list(self._instrument_instances.keys())