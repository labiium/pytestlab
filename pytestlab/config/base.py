from __future__ import annotations

from pydantic import ConfigDict

from ._mixins import RangeMixin
from .config import BaseConfig as BaseConfig


class Range(RangeMixin):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
