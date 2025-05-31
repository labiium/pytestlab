# pytestlab/config/_mixins.py
from pydantic import BaseModel, field_validator, Field, ConfigDict # Added Field, ConfigDict

class EnumMapMixin(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    """Automatic mapping from user option to SCPI value list[str]."""
    @classmethod
    def _map(cls, src: str, options: dict[str, str]) -> str:
        key = src.upper()
        if key in options:
            return options[key]
        raise ValueError(f"'{src}' not in available options: {list(options.keys())}")

class RangeMixin(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    min_val: float = Field(..., description="Minimum value of the range (inclusive)")
    max_val: float = Field(..., description="Maximum value of the range (inclusive)")

    @field_validator("max_val")
    def _min_lt_max(cls, v: float, info): # Added type hint for v
        # Pydantic V2: info is a ValidationInfo object
        # info.data is a dict of the fields that have already been validated.
        if "min_val" in info.data and info.data["min_val"] is not None: # Ensure min_val was successfully validated
            if v < info.data["min_val"]: # Changed to < to allow min_val == max_val for fixed point ranges
                raise ValueError(f"max_val ({v}) must be >= min_val ({info.data['min_val']})")
        # If min_val is not in info.data, it means min_val validation failed or hasn't run.
        # Pydantic handles the error for min_val separately.
        # This validator should only focus on the relationship if min_val is valid.
        return v

    def assert_in_range(self, x: float, name: str = "value") -> float:
        if not (self.min_val <= x <= self.max_val):
            # from ..errors import InstrumentParameterError # Lazy import or move error definition
            # For now, using ValueError as per the mixin's original context.
            # Consider making this more specific, e.g. OutOfRangeError
            raise ValueError(f"{name} '{x}' is outside the valid range [{self.min_val}…{self.max_val}]")
        return x