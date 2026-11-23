from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from ..errors import InstrumentParameterError


class RangeMixin(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    min_val: float = Field(..., description="Minimum value of the range (inclusive)")
    max_val: float = Field(..., description="Maximum value of the range (inclusive)")

    @field_validator("max_val")
    def _min_lt_max(cls, v: float, info):
        min_val = info.data.get("min_val")
        if min_val is not None and v < min_val:
            raise ValueError(f"max_val ({v}) must be >= min_val ({min_val})")
        return v

    def assert_in_range(self, x: float, name: str = "value") -> float:
        if not (self.min_val <= x <= self.max_val):
            raise InstrumentParameterError(
                parameter=name,
                value=x,
                valid_range=(self.min_val, self.max_val),
                message=f"{name} must be between {self.min_val} and {self.max_val}.",
            )
        return x
