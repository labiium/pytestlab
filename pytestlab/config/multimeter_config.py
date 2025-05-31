# pytestlab/config/multimeter_config.py

from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field, ConfigDict # Added ConfigDict

from pytestlab.config.instrument_config import InstrumentConfig


class DMMFunction(str, Enum):
    """Enum for DMM measurement functions."""
    VOLT_DC = "VOLT:DC"
    VOLT_AC = "VOLT:AC"
    CURR_DC = "CURR:DC"
    CURR_AC = "CURR:AC"
    RES = "RES"  # 2-wire resistance
    FRES = "FRES"  # 4-wire resistance
    FREQ = "FREQ"
    TEMP = "TEMP"
    DIOD = "DIOD"  # Diode check
    CONT = "CONT"  # Continuity check

    def __str__(self) -> str:
        return self.value


class DMMConfiguration(BaseModel):
    """
    Nested model for DMM configuration settings, primarily focused on supported ranges
    for various measurement functions.
    """
    model_config = ConfigDict(validate_assignment=True, extra='forbid', populate_by_name=True)

    voltage: List[str] = Field(
        ..., # Now required
        min_length=1,
        description="Supported DC voltage ranges (e.g., '100mV', '1V', 'AUTO'). For 'VOLT:DC'."
    )
    voltage_ac_ranges: List[str] = Field(
        ..., # Now required
        min_length=1,
        description="Supported AC voltage ranges. For 'VOLT:AC'."
    )
    current_dc_ranges: List[str] = Field(
        ..., # Now required
        min_length=1,
        description="Supported DC current ranges. For 'CURR:DC'."
    )
    current_ac_ranges: List[str] = Field(
        ..., # Now required
        min_length=1,
        description="Supported AC current ranges. For 'CURR:AC'."
    )
    resistance_ranges: List[str] = Field(
        ..., # Now required
        min_length=1,
        description="Supported 2-wire resistance ranges. For 'RES'."
    )
    # FRES, FREQ, TEMP can remain optional as not all DMMs support them
    four_wire_resistance_ranges: Optional[List[str]] = Field(
        default=None,
        min_length=1, # If provided, must not be empty
        alias="fres_ranges",
        description="Supported 4-wire resistance ranges. For 'FRES'."
    )
    frequency_settings: Optional[List[str]] = Field(
        default=None,
        min_length=1, # If provided, must not be empty
        description="Supported frequency measurement settings/configurations."
    )
    temperature_units: Optional[List[Literal["C", "F", "K"]]] = Field(
        default=None,
        min_length=1, # If provided, must not be empty
        description="Supported temperature units for 'TEMP' function."
    )


class MultimeterConfig(InstrumentConfig):
    """Pydantic model for Multimeter configuration."""
    model_config = ConfigDict(validate_assignment=True, extra='forbid', use_enum_values=True)

    # device_type is inherited from InstrumentConfig and validated there.
    # It will be overridden by the specific Literal["DMM"] here.
    device_type: Literal["DMM", "multimeter"] = Field("DMM", description="Device type identifier for DMMs (e.g. 'DMM', 'multimeter').")

    measurement_function: DMMFunction = Field(
        default=DMMFunction.VOLT_DC,
        description="Primary or default measurement function for the DMM."
    )

    configuration: DMMConfiguration = Field( # Removed Optional, ensuring it always exists
        default_factory=DMMConfiguration,
        description="Specific configuration settings for DMM measurement functions, including supported ranges."
    )

    resolution: Optional[float] = Field(
        default=None,
        gt=0, # Resolution should be positive
        description="Default measurement resolution. Can be function-specific in practice."
    )
    nplc: Optional[float] = Field(
        default=None,
        gt=0, # NPLC should be positive
        description="Default Number of Power Line Cycles for integration time. Can be function-specific."
    )
    trigger_source: Literal["IMM", "EXT", "BUS"] = Field(
        default="IMM",
        description="Default trigger source: IMM (Immediate), EXT (External), BUS (Software/System)."
    )
    autorange: bool = Field(
        default=True,
        description="Enable (True) or disable (False) autoranging for measurements."
    )