from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
import math

class AccuracySpec(BaseModel):
    """
    Represents a single accuracy specification for a measurement mode.
    The standard deviation (sigma) is typically calculated as:
    sqrt((percent_reading * reading)^2 + (offset_value)^2)
    or other forms depending on how specs are given (e.g., % of range).
    """
    percent_reading: Optional[float] = Field(None, description="Accuracy as a percentage of the reading (e.g., 0.0001 for 0.01%)")
    offset_value: Optional[float] = Field(None, description="Fixed offset accuracy in units of the measurement (e.g., 0.005 V)")
    # Add other common ways accuracy is specified if needed, e.g., percent_range

    def calculate_std_dev(self, reading_value: float, range_value: Optional[float] = None) -> float:
        """
        Calculates the standard deviation (sigma) for a given reading.
        This is a simplified example; real datasheets can be more complex.
        """
        variance = 0.0
        if self.percent_reading is not None:
            variance += (self.percent_reading * reading_value)**2
        if self.offset_value is not None:
            variance += self.offset_value**2
        
        # Example for percent_range if it were added:
        # if self.percent_range is not None and range_value is not None:
        #     variance += (self.percent_range * range_value)**2

        if variance == 0.0: # No spec provided, or spec results in zero uncertainty
            return 0.0 # Or raise an error, or return a very small number
        
        return math.sqrt(variance)

# Example of how it might be structured in the main instrument config:
# class SomeInstrumentConfig(InstrumentConfig):
#   ...
#   measurement_accuracy: Optional[dict[str, AccuracySpec]] = None
#   ...