from __future__ import annotations
from pydantic import BaseModel, Field # validator is not used in the example, Field might be useful later

class Range(BaseModel):
    min_val: float
    max_val: float

    def in_range(self, x: float) -> bool:
        return self.min_val <= x <= self.max_val

# Add other core/common Pydantic models here if identified or needed later.