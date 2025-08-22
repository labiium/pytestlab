# pytestlab/config/multimeter_config.py

from enum import Enum
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from pytestlab.config.accuracy import AccuracySpec
from pytestlab.config.instrument_config import InstrumentConfig

try:
    from uncertainties.core import UFloat
except ImportError:
    UFloat = float


class DMMFunction(str, Enum):
    """Enum for DMM measurement functions corresponding to SCPI commands."""

    VOLTAGE_DC = "VOLT:DC"
    VOLTAGE_AC = "VOLT:AC"
    CURRENT_DC = "CURR:DC"
    CURRENT_AC = "CURR:AC"
    RESISTANCE = "RES"
    FRESISTANCE = "FRES"
    FREQUENCY = "FREQ"
    TEMPERATURE = "TEMP"
    DIODE = "DIOD"
    CONTINUITY = "CONT"
    CAPACITANCE = "CAP"

    def __str__(self) -> str:
        return self.value


# NOTE: AccuracySpec is imported from pytestlab.config.accuracy (see import above).
# The previous duplicate local definition has been removed to avoid redefinition (F811).


class RangeSpec(BaseModel):
    """Models a single measurement range with its specifications."""

    model_config = ConfigDict(extra="allow")  # Allow other fields like test_current_A

    nominal_V: float | None = None
    nominal_ohm: float | None = None
    nominal_A: float | None = None
    nominal_F: float | None = None

    accuracy: AccuracySpec | None = None
    typical_accuracy: AccuracySpec | None = None
    accuracy_45Hz_10kHz: AccuracySpec | None = None
    accuracy_45Hz_1kHz: AccuracySpec | None = None

    @field_validator("nominal_V", "nominal_ohm", "nominal_A", "nominal_F", mode="before")
    @classmethod
    def validate_float_notation(cls, v):
        if v is None:
            return v
        try:
            return float(v)
        except (ValueError, TypeError):
            return v

    @property
    def nominal(self) -> float:
        """Returns the nominal value of the range, regardless of the unit."""
        for val in [self.nominal_V, self.nominal_ohm, self.nominal_A, self.nominal_F]:
            if val is not None:
                return val
        raise ValueError("RangeSpec has no nominal value defined.")

    @property
    def default_accuracy(self) -> AccuracySpec | None:
        """Returns the primary accuracy spec available."""
        return (
            self.accuracy
            or self.typical_accuracy
            or self.accuracy_45Hz_10kHz
            or self.accuracy_45Hz_1kHz
        )


class FunctionSpec(BaseModel):
    """Models the specifications for a single measurement function."""

    model_config = ConfigDict(extra="allow")
    ranges: list[RangeSpec] | None = None


class MeasurementFunctionsSpec(BaseModel):
    """Container for all measurement function specifications from the YAML."""

    model_config = ConfigDict(extra="allow")
    dc_voltage: FunctionSpec | None = None
    resistance_4wire: FunctionSpec | None = None
    dc_current: FunctionSpec | None = None
    ac_voltage: FunctionSpec | None = None
    ac_current: FunctionSpec | None = None
    frequency: FunctionSpec | None = None
    temperature: FunctionSpec | None = None
    capacitance: FunctionSpec | None = None
    # 2-wire resistance is often not explicitly listed but can be inferred or added
    resistance: FunctionSpec | None = None


class MultimeterConfig(InstrumentConfig):
    """Pydantic model for Multimeter configuration, designed to load from a device spec YAML."""

    model_config = ConfigDict(validate_assignment=True, extra="ignore")

    # Relaxed to plain str to maintain compatibility with base class (avoids variance issues).
    device_type: str = Field("multimeter", description="Device type identifier for multimeters.")
    # Runtime/Session settings
    default_measurement_function: DMMFunction = Field(
        default=DMMFunction.VOLTAGE_DC,
        description="Primary or default measurement function for the DMM.",
    )
    trigger_source: Literal["IMM", "EXT", "BUS"] = Field(
        default="IMM",
        description="Default trigger source: IMM (Immediate), EXT (External), BUS (Software/System).",
    )
    autorange: bool = Field(
        default=True, description="Enable (True) or disable (False) autoranging for measurements."
    )

    # Fields mapping directly to the YAML specification file
    limits: dict[str, Any] | None = Field(default_factory=dict)
    measurement_functions: MeasurementFunctionsSpec | None = Field(
        default_factory=MeasurementFunctionsSpec
    )
    math_functions: list[str] | None = Field(default_factory=list)
    sampling_rates_rps: dict[str, Any] | None = Field(default_factory=dict)
