from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from ..common.health import HealthReport
from ..common.health import HealthStatus

if TYPE_CHECKING:
    from .instrument import Instrument


class InstrumentHealthMonitor:
    """Base instrument health check helper."""

    def __init__(self, instrument: Instrument[Any]) -> None:
        self.instrument = instrument

    def check(self) -> HealthReport:
        instrument = self.instrument
        report = HealthReport()
        try:
            report.instrument_idn = instrument.id()
            instrument_errors = instrument.get_all_errors()
            if instrument_errors:
                report.warnings.extend(
                    [f"Stored Error: {code} - {msg}" for code, msg in instrument_errors]
                )

            if not report.errors and not report.warnings:
                report.status = HealthStatus.OK
            elif report.warnings and not report.errors:
                report.status = HealthStatus.WARNING
            else:
                report.status = HealthStatus.ERROR

        except Exception as e:
            report.status = HealthStatus.ERROR
            report.errors.append(f"Health check failed during IDN/Error Query: {str(e)}")
        return report
