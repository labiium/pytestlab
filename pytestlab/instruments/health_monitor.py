from __future__ import annotations

from collections.abc import Mapping
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

    def _capability(self, name: str) -> Any:
        """Read one profile health capability without requiring a schema version."""

        config = self.instrument.config
        capabilities = getattr(config, "capabilities", None)
        if isinstance(capabilities, Mapping) and name in capabilities:
            return capabilities[name]
        return getattr(config, name, None)

    def _has_profile_alias(self, alias: str) -> bool:
        """Use the instrument's offline alias helper when available."""

        helper = getattr(self.instrument, "has_profile_alias", None)
        if callable(helper):
            return bool(helper(alias))

        # Legacy collaborators predate profile introspection. Their old
        # behaviour was to attempt the operation and report its failure.
        return True

    def _supports_error_queue(self) -> bool:
        helper = getattr(self.instrument, "supports_error_queue", None)
        if callable(helper):
            return bool(helper())
        return True

    def _identity_policy(self) -> tuple[bool, bool]:
        """Return (enabled, required) for the profile identity capability."""

        configured = self._capability("identity")
        if isinstance(configured, Mapping):
            return bool(configured.get("enabled", True)), bool(configured.get("required", False))
        if configured is not None:
            # A boolean shorthand explicitly opts into identity. Keep it
            # required for compatibility; dict form can opt into optional
            # identity with ``required: false``.
            return bool(configured), bool(configured)

        return self._has_profile_alias("identify"), True

    def _status_byte_spec(self) -> tuple[bool, Mapping[str, Any]]:
        configured = self._capability("status_byte")
        if configured is None or configured is False:
            return False, {}
        if isinstance(configured, Mapping):
            return bool(configured.get("enabled", True)), configured
        return bool(configured), {}

    def _connection_verified(self) -> bool:
        ensure_connected = getattr(self.instrument, "_ensure_backend_connected", None)
        if not callable(ensure_connected):
            return True
        try:
            ensure_connected()
        except Exception:
            return False
        return True

    @staticmethod
    def _status_flag_message(name: str, spec: Mapping[str, Any]) -> str:
        description = spec.get("description")
        if description:
            return f"Status flag '{name}' active: {description}"
        return f"Status flag '{name}' active"

    def _decode_status_byte(self, report: HealthReport, spec: Mapping[str, Any]) -> None:
        flags = spec.get("flags", {})
        if not isinstance(flags, Mapping):
            return
        status_byte = report.status_byte
        if status_byte is None:
            return
        for name, raw_flag in flags.items():
            if not isinstance(raw_flag, Mapping):
                continue
            mask = raw_flag.get("mask")
            if isinstance(mask, bool) or not isinstance(mask, int):
                continue
            active = bool(status_byte & mask)
            report.status_flags[str(name)] = active
            if not active:
                continue
            message = self._status_flag_message(str(name), raw_flag)
            severity = str(raw_flag.get("severity", "info")).lower()
            if severity == "error":
                report.errors.append(message)
            elif severity == "warning":
                report.warnings.append(message)

    def check(self) -> HealthReport:
        instrument = self.instrument
        report = HealthReport()

        identity_enabled, identity_required = self._identity_policy()
        connection_verified = True
        verified = False

        if identity_enabled and self._has_profile_alias("identify"):
            connection_verified = self._connection_verified()
            try:
                report.instrument_idn = instrument.id()
                verified = True
            except Exception as exc:
                message = f"Health check failed during IDN Query: {exc}"
                if identity_required or not connection_verified:
                    report.errors.append(message)
                else:
                    report.warnings.append(message)

        if self._supports_error_queue():
            try:
                instrument_errors = instrument.get_all_errors()
                verified = True
                if instrument_errors:
                    report.warnings.extend(
                        [f"Stored Error: {code} - {msg}" for code, msg in instrument_errors]
                    )
            except Exception as exc:
                report.errors.append(f"Health check failed during Error Query: {exc}")

        status_enabled, status_spec = self._status_byte_spec()
        if status_enabled:
            read_status_byte = getattr(instrument, "read_status_byte", None)
            if callable(read_status_byte):
                try:
                    report.status_byte = read_status_byte()
                    verified = True
                    self._decode_status_byte(report, status_spec)
                except Exception as exc:
                    report.errors.append(f"Health check failed during Status Byte Query: {exc}")

        if report.errors:
            report.status = HealthStatus.ERROR
        elif report.warnings:
            report.status = HealthStatus.WARNING
        elif verified:
            report.status = HealthStatus.OK
        return report
