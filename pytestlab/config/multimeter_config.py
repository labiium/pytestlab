# pytestlab/config/multimeter_config.py

from enum import Enum
from typing import List, Optional, Literal, Dict, Any, Union

from pydantic import BaseModel, Field, ConfigDict, field_validator

from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.accuracy import AccuracySpec
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


class AccuracySpec(BaseModel):
    """Models the accuracy specification for a given measurement range."""
    percent_reading: float = Field(..., description="Accuracy component as a percentage of the reading.")
    percent_range: Optional[float] = Field(default=None, description="Accuracy component as a percentage of the range.")
    counts: Optional[int] = Field(default=None, description="Accuracy component as a fixed number of counts of the least significant digit.")

    def calculate_uncertainty(self, reading: Union[float, UFloat], range_value: float) -> float:
        """Calculates the total uncertainty (1-sigma) for a given reading and range."""
        # Ensure reading is a float for calculation
        nominal_value = reading.n if isinstance(reading, UFloat) else reading
        uncertainty = 0.0

        if self.percent_reading is not None:
            uncertainty += (self.percent_reading / 100.0) * abs(nominal_value)
        if self.percent_range is not None:
            uncertainty += (self.percent_range / 100.0) * range_value

        # Note: 'counts' implementation requires knowledge of the instrument's resolution/LSD value,
        # which is complex. This implementation focuses on percentage-based uncertainty.
        if self.counts is not None:
            # A proper implementation would require the resolution value.
            # This is a placeholder for future enhancement.
            pass

        return uncertainty


class RangeSpec(BaseModel):
    """Models a single measurement range with its specifications."""
    model_config = ConfigDict(extra='allow')  # Allow other fields like test_current_A

    nominal_V: Optional[float] = None
    nominal_ohm: Optional[float] = None
    nominal_A: Optional[float] = None
    nominal_F: Optional[float] = None

    accuracy: Optional[AccuracySpec] = None
    typical_accuracy: Optional[AccuracySpec] = None
    accuracy_45Hz_10kHz: Optional[AccuracySpec] = None
    accuracy_45Hz_1kHz: Optional[AccuracySpec] = None

    @field_validator('nominal_V', 'nominal_ohm', 'nominal_A', 'nominal_F', mode='before')
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
    def default_accuracy(self) -> Optional[AccuracySpec]:
        """Returns the primary accuracy spec available."""
        return self.accuracy or self.typical_accuracy or self.accuracy_45Hz_10kHz or self.accuracy_45Hz_1kHz


class FunctionSpec(BaseModel):
    """Models the specifications for a single measurement function."""
    model_config = ConfigDict(extra='allow')
    ranges: Optional[List[RangeSpec]] = None


class MeasurementFunctionsSpec(BaseModel):
    """Container for all measurement function specifications from the YAML."""
    model_config = ConfigDict(extra='allow')
    dc_voltage: Optional[FunctionSpec] = None
    resistance_4wire: Optional[FunctionSpec] = None
    dc_current: Optional[FunctionSpec] = None
    ac_voltage: Optional[FunctionSpec] = None
    ac_current: Optional[FunctionSpec] = None
    frequency: Optional[FunctionSpec] = None
    temperature: Optional[FunctionSpec] = None
    capacitance: Optional[FunctionSpec] = None
    # 2-wire resistance is often not explicitly listed but can be inferred or added
    resistance: Optional[FunctionSpec] = None


class MultimeterConfig(InstrumentConfig):
    """Pydantic model for Multimeter configuration, designed to load from a device spec YAML."""
    model_config = ConfigDict(validate_assignment=True, extra='ignore')

    device_type: Literal["multimeter", "DMM"] = Field(
        "multimeter", description="Device type identifier for multimeters."
    )
    # Runtime/Session settings
    default_measurement_function: DMMFunction = Field(
        default=DMMFunction.VOLTAGE_DC,
        description="Primary or default measurement function for the DMM."
    )
    trigger_source: Literal["IMM", "EXT", "BUS"] = Field(
        default="IMM",
        description="Default trigger source: IMM (Immediate), EXT (External), BUS (Software/System)."
    )
    autorange: bool = Field(
        default=True,
        description="Enable (True) or disable (False) autoranging for measurements."
    )

    # Fields mapping directly to the YAML specification file
    limits: Optional[Dict[str, Any]] = Field(default_factory=dict)
    measurement_functions: Optional[MeasurementFunctionsSpec] = Field(default_factory=MeasurementFunctionsSpec)
    math_functions: Optional[List[str]] = Field(default_factory=list)
    sampling_rates_rps: Optional[Dict[str, Any]] = Field(default_factory=dict)
