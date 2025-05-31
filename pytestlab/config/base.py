from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict # validator is not used in the example, Field might be useful later. Added ConfigDict
from ._mixins import RangeMixin

class Range(RangeMixin): # RangeMixin already inherits from BaseModel
    model_config = ConfigDict(validate_assignment=True, extra='forbid')
    # Fields min_val and max_val are inherited from RangeMixin
    # No need to redefine them here unless overriding or adding more specific constraints
    # that cannot be handled in RangeMixin itself.
    pass

# Add other core/common Pydantic models here if identified or needed later.