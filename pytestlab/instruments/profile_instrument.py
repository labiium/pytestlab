from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..config.instrument_config import InstrumentConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentParameterError
from ..profile_transport import ProfileTransport
from .instrument import Instrument
from .operation_contract import OperationDescriptor


class ProfileInstrument(Instrument[InstrumentConfig]):
    """Generic instrument driver whose executable surface is profile-defined.

    The profile owns operation names, semantic parameter validation, and SCPI
    aliases.  This class supplies only the transport-neutral execution policy;
    vendor/model-specific Python setup is intentionally not part of the path.
    """

    def connect_backend(self) -> None:
        """Apply explicit profile message-I/O settings before backend connect."""

        with self._backend_lock:
            if self._backend_connected:
                return
            backend = self._backend
            capabilities = getattr(self.config, "capabilities", {}) or {}
            message_io = (
                capabilities.get("message_io") if isinstance(capabilities, Mapping) else None
            )
            if (
                not isinstance(backend, ProfileTransport)
                and isinstance(message_io, Mapping)
                and "read_termination" in message_io
            ):
                termination = message_io["read_termination"]
                if termination is not None and not isinstance(termination, str):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "capabilities.message_io.read_termination must be a string or null.",
                    )
                setter = getattr(backend, "set_read_termination", None)
                if not callable(setter):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "The selected backend does not support read-termination configuration.",
                    )
                setter(termination)
            if isinstance(backend, ProfileTransport):
                for key in backend.message_io:
                    if not callable(getattr(backend.io, f"set_{key}", None)):
                        raise InstrumentConfigurationError(
                            self.config.model,
                            f"The selected backend does not support {key.replace('_', '-')} configuration.",
                        )
            super().connect_backend()

    def operation_descriptors(self) -> tuple[OperationDescriptor, ...]:
        """Return the base contract plus descriptors declared by this profile."""

        descriptors = list(super().operation_descriptors())
        declared = {descriptor.operation_id for descriptor in descriptors}
        options = getattr(self.config, "operation_options", None)
        operations = getattr(options, "operations", {}) if options is not None else {}
        for operation_id, spec in operations.items():
            if operation_id in declared:
                continue
            safety_class = spec.safety_class or (
                "read" if spec.mode in {"query", "native"} else "state-changing"
            )
            descriptors.append(
                OperationDescriptor(
                    operation_id=operation_id,
                    safety_class=safety_class,
                    public_method="execute_profile_operation",
                )
            )
        return tuple(descriptors)

    def _operation_support_report(self, operation_id: str, *, check_parameters: bool = False):
        report = super()._operation_support_report(
            operation_id,
            check_parameters=check_parameters,
        )
        options = getattr(self.config, "operation_options", None)
        spec = options.operation(operation_id) if options is not None else None
        if report.supported and spec is not None and spec.mode == "native":
            available = self._native_backend_method_available(spec.backend_method or "")
            if available is False:
                return replace(
                    report,
                    supported=False,
                    reason="selected backend does not provide native status-byte reading",
                )
        return report

    def describe_operation(
        self,
        operation_id: str,
        *,
        context: dict[str, Any] | None = None,
        include_unsupported: bool = False,
    ) -> dict[str, Any]:
        """Describe a profile operation without allocating or touching its backend."""

        description = super().describe_operation(
            operation_id,
            context=context,
            include_unsupported=include_unsupported,
        )
        options = getattr(self.config, "operation_options", None)
        spec = options.operation(operation_id) if options is not None else None
        if spec is not None:
            effective_safety = spec.safety_class or (
                "read" if spec.mode in {"query", "native"} else "state-changing"
            )
            description["execution"] = {
                "mode": spec.mode,
                "safety_class": effective_safety,
                "requires_context": list(spec.requires_context),
                "response_pattern": spec.response_pattern,
            }
            if (
                spec.mode == "native"
                and self._native_backend_method_available(spec.backend_method or "") is False
            ):
                description["support"] = {
                    **description.get("support", {}),
                    "supported": False,
                    "reason": "selected backend does not provide native status-byte reading",
                }
        return description

    def execute_profile_operation(
        self,
        operation_id: str,
        *,
        safety_context: Mapping[str, Any] | None = None,
        **params: Any,
    ) -> Any:
        """Execute a named profile operation after semantic and safety checks.

        ``safety_context`` is deliberately separate from operation parameters:
        profile-declared guards must be satisfied before any backend allocation,
        connection, or I/O.  Native operations are limited to the backend
        capability explicitly whitelisted by the profile schema.
        """

        options = getattr(self.config, "operation_options", None)
        spec = options.operation(operation_id) if options is not None else None
        if spec is None:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile does not declare operation '{operation_id}'.",
            )

        descriptor = self._get_operation_descriptor(operation_id)
        if descriptor.python_only:
            reason = (
                "requires caller-provided Python objects"
                if descriptor.python_arguments
                else "is available only as a direct Python call"
            )
            raise InstrumentConfigurationError(
                self.config.model,
                f"Operation '{operation_id}' {reason}. Call its typed method directly.",
            )

        if spec.mode is None:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile operation '{operation_id}' must declare an explicit execution mode.",
            )

        context = dict(safety_context or {})
        missing = [key for key in spec.requires_context if context.get(key) is not True]
        if missing:
            raise InstrumentConfigurationError(
                self.config.model,
                "Profile operation requires safety context: " + ", ".join(missing),
            )

        # Fill declared defaults and reject missing required parameters before
        # any resolver/transport work can reach the backend.
        arguments = dict(params)
        for parameter, parameter_spec in spec.parameters.items():
            if parameter not in arguments or arguments[parameter] is None:
                if parameter_spec.default is not None:
                    arguments[parameter] = parameter_spec.default
                elif parameter_spec.required:
                    raise InstrumentParameterError(
                        parameter=parameter,
                        message=f"Required profile parameter '{parameter}' was not supplied.",
                    )

        # Resolver validation is entirely offline and must precede any backend
        # access, including native backend allocation.
        resolved = self._resolve_operation_arguments(operation_id, arguments)

        if spec.mode == "native":
            if spec.backend_method != "read_status_byte":
                raise InstrumentConfigurationError(
                    self.config.model,
                    f"Unsupported native backend method for '{operation_id}'.",
                )
            return self.read_status_byte()

        transport_aliases = {
            str(kind): str(alias) for kind, alias in spec.transport.items() if alias
        }
        aliases = list(dict.fromkeys(transport_aliases.values()))
        if not aliases:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile operation '{operation_id}' has no SCPI transport alias.",
            )

        query_alias: str | None = None
        if spec.mode == "query":
            query_alias = transport_aliases.get("query")
            if query_alias is None:
                if len(aliases) != 1:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Profile query operation '{operation_id}' must declare exactly one "
                        "query transport alias.",
                    )
                query_alias = aliases[0]

        # Format every command before the first send/query so a later missing
        # placeholder cannot leave a multi-alias write partially applied.
        formatted = {
            alias: self._build_profile_alias(alias, **resolved.get(alias, {})) for alias in aliases
        }

        if spec.mode == "query":
            assert query_alias is not None
            for alias in aliases:
                if alias == query_alias:
                    continue
                for command in formatted[alias]:
                    self._send_command(command)
            query_commands = formatted[query_alias]
            for command in query_commands[:-1]:
                self._send_command(command)
            raw = self._query(query_commands[-1])
            if spec.response_pattern and re.match(spec.response_pattern, raw) is None:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=query_commands[-1],
                    message="Profile query response did not match response_pattern.",
                )
            return self._scpi_engine.parse(query_alias, raw)

        for alias in aliases:
            for command in formatted[alias]:
                self._send_command(command)
        return None
