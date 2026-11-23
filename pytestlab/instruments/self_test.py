"""Shared results for deliberate instrument self-tests."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class InstrumentSelfTestResult:
    """Native result and host completion time from a supported self-test."""

    model: str
    serial_number: str
    code: int
    completed_at_utc: datetime
    raw_response: str
    channel: int | None = None

    @property
    def passed(self) -> bool:
        """Whether the instrument reported a successful self-test."""
        return self.code == 0
