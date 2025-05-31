# pytestlab/config/bench_config.py
from pathlib import Path
from typing import Literal, Optional, List, Dict
from pydantic import BaseModel, Field, model_validator, ConfigDict

BackendType = Literal["visa", "lamb", "sim"]

class BackendSettings(BaseModel):
    model_config = ConfigDict(extra='forbid') # Forbid extra fields
    type: BackendType = "visa"
    timeout_ms: int = 5000
    # future: adapter-specific kwargs (baudrate, tls, user/pass …)

class InstrumentEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # alias: str = Field(..., pattern=r"^[A-Za-z_][A-Za-z0-9_]*$") # alias is key in dict, not field here
    profile: str  # dotted key or path to YAML
    address: Optional[str] = None  # VISA resource string, lamb id, "sim"
    backend: Optional[BackendSettings] = None # Allow full BackendSettings override
    simulate: Optional[bool] = None

    @model_validator(mode="before") # Use before to default address if missing from YAML
    @classmethod # model_validator in Pydantic v2 needs @classmethod if mode='before'
    def _default_address_if_none(cls, values: Dict) -> Dict:
        if values.get("address") is None: # Check if 'address' is missing or None
            values["address"] = "sim"  # Default to "sim"
        return values

class BenchConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bench_name: str
    description: Optional[str] = None
    simulate: bool = False # Global simulate flag
    backend_defaults: BackendSettings = Field(default_factory=BackendSettings)
    instruments: Dict[str, InstrumentEntry] # Use Dict for alias mapping

    # Convenience: dict lookup by alias is now direct via self.instruments
    # def instrument_map(self) -> dict[str, InstrumentEntry]:
    #     return {i.alias: i for i in self.instruments} # Not needed if instruments is Dict