from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict # Added ConfigDict
from typing import Optional
import math

class AccuracySpec(BaseModel):
    """
    Represents a single accuracy specification for a measurement mode.
    The standard deviation (sigma) is typically calculated as:
    sqrt((percent_reading * reading)^2 + (offset_value)^2)
    or other forms depending on how specs are given (e.g., % of range).
    """
    model_config = ConfigDict(validate_assignment=True, extra='forbid')

    percent_reading: Optional[float] = Field(None, ge=0, description="Accuracy as a percentage of the reading (e.g., 0.0001 for 0.01%)")
    offset_value: Optional[float] = Field(None, ge=0, description="Fixed offset accuracy in units of the measurement (e.g., 0.005 V)")
    # Add other common ways accuracy is specified if needed, e.g., percent_range

    def calculate_std_dev(self, reading_value: float, range_value: Optional[float] = None) -> float:
        """
        Calculates the standard deviation (sigma) for a given reading.
        This is a simplified example; real datasheets can be more complex.
        Assumes reading_value is positive for typical instrument readings.
        """
        if reading_value < 0:
            # Or handle as per specific instrument/measurement context
            # For now, using absolute value for calculation if negative readings are possible and meaningful
            # reading_value = abs(reading_value)
            pass # Assuming reading_value is typically positive or magnitude.

        variance = 0.0
        if self.percent_reading is not None:
            if self.percent_reading < 0:
                raise ValueError("percent_reading must be non-negative.")
            variance += (self.percent_reading * reading_value)**2
        
        if self.offset_value is not None:
            if self.offset_value < 0:
                raise ValueError("offset_value must be non-negative.")
            variance += self.offset_value**2
        
        # Example for percent_range if it were added:
        # percent_range: Optional[float] = Field(None, ge=0, description="Accuracy as a percentage of the range")
        # if self.percent_range is not None and range_value is not None:
        #     if self.percent_range < 0:
        #         raise ValueError("percent_range must be non-negative.")
        #     if range_value <= 0: # Range should be positive
        #         raise ValueError("range_value must be positive for percent_range calculation.")
        #     variance += (self.percent_range * range_value)**2

        if variance < 0.0: # Should not happen with non-negative inputs and squaring
             raise ValueError("Calculated variance is negative, check inputs and logic.")
        if variance == 0.0: # No spec provided, or spec results in zero uncertainty
            return 0.0 # Or raise an error, or return a very small number if appropriate
        
        return math.sqrt(variance)

# Example of how it might be structured in the main instrument config:
# class SomeInstrumentConfig(InstrumentConfig):
#   model_config = ConfigDict(validate_assignment=True, extra='forbid')
#   measurement_accuracy: Optional[dict[str, AccuracySpec]] = Field(default_factory=dict)
#   ...