from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from contextlib import contextmanager
from threading import RLock
from typing import Any
from typing import Generic
from typing import TypeVar
from typing import cast

import numpy as np

from ..common.health import HealthReport
from ..config import InstrumentConfig
from ..devices.base import Device
from ..devices.base import DeviceIO
from ..devices.base import _BackendFactory
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ..profile_transport import ProfileTransport
from .command_session import InstrumentCommandSession
from .error_queue import InstrumentErrorQueue
from .health_monitor import InstrumentHealthMonitor
from .operation_contract import OperationDescriptor
from .operation_contract import OperationScope
from .operation_contract import OperationSupportReport
from .operation_resolver import OperationResolver
from .operation_waiter import InstrumentOperationWaiter
from .scpi_binary import BinaryBlockParseError
from .scpi_binary import definite_length_block_to_array
from .scpi_engine import SCPIEngine

ConfigType = TypeVar("ConfigType", bound="InstrumentConfig")


InstrumentIO = DeviceIO


class Instrument(Device[ConfigType], Generic[ConfigType]):
    """Base class for all instrument drivers.

    This class provides the core functionality for interacting with an instrument
    through a standardized interface. It handles command sending,
    querying, error checking, and logging. It is designed to be subclassed for
    specific instrument types (e.g., Oscilloscope, PowerSupply).

    The `Instrument` class is generic and typed with `ConfigType`, which allows
    each subclass to specify its own Pydantic configuration model.

    Attributes:
        config (ConfigType): The Pydantic configuration model instance for this
                             instrument.
        _backend (InstrumentIO): The communication backend used to interact
                                 with the hardware or simulation.
        _command_log (List[Dict[str, Any]]): A log of all commands sent and
                                             responses received.
        _logger: The logger instance for this instrument.
    """

    # Maximum number of errors to read before stopping
    MAX_ERRORS_TO_READ = 50

    # Reset is part of every instrument's semantic interface.  The profile
    # supplies its private transport mapping; subclasses must not redeclare it.
    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor("reset", public_method="reset", required=False),
    )

    # Class-level annotations for instance variables
    config: ConfigType
    _command_log: list[dict[str, Any]]
    _logger: Any  # Actual type would be logging.Logger, using Any if Logger type not imported

    @property
    def _backend(self) -> InstrumentIO:
        return cast(InstrumentIO, super()._backend)

    @_backend.setter
    def _backend(self, backend: InstrumentIO) -> None:
        with self._backend_lock:
            self._backend_source = backend

    def __init__(
        self, config: ConfigType, backend: InstrumentIO | _BackendFactory, **kwargs: Any
    ) -> None:
        """
        Initialize the Instrument class.

        Args:
            config (ConfigType): Configuration for the instrument.
            backend (InstrumentIO): The communication backend instance.
            **kwargs: Additional keyword arguments.
        """
        if not isinstance(config, InstrumentConfig):  # Check against the bound base
            raise InstrumentConfigurationError(
                self.__class__.__name__,
                f"A valid InstrumentConfig-compatible object must be provided, but got {type(config).__name__}.",
            )

        super().__init__(config=config, backend=backend, **kwargs)
        self._operation_lock = RLock()
        capabilities = getattr(config, "capabilities", {})
        legacy = capabilities.get("message_io", {}) if isinstance(capabilities, Mapping) else {}
        transport = {**(dict(legacy) if isinstance(legacy, Mapping) else {}), **config.transport}
        if transport:
            source = self._backend_source
            if isinstance(source, _BackendFactory):
                self._backend_source = _BackendFactory(
                    lambda: ProfileTransport(source.build(), transport)
                )
            else:
                self._backend_source = ProfileTransport(source, transport)
        # Get SCPI data and convert to compatible format
        if hasattr(self.config, "scpi") and self.config.scpi is not None:
            if hasattr(self.config.scpi, "model_dump"):
                scpi_section = self.config.scpi.model_dump()
            else:
                scpi_section = {}
        else:
            scpi_section = {}
        self._scpi_engine = SCPIEngine(
            scpi_section, variant=getattr(self.config, "scpi_variant", None)
        )
        self._command_session = InstrumentCommandSession(self)
        self._error_queue = InstrumentErrorQueue(self)
        self._operation_waiter = InstrumentOperationWaiter(self)
        self._health_monitor = InstrumentHealthMonitor(self)
        self._uncertainty_instance_key = uuid.uuid4().hex

    def _uncertainty_source_key(self) -> str:
        """Stable identity-derived prefix for correlated uncertainty atoms."""

        backend = self._backend
        backend_identity = {
            name: getattr(backend, name, None)
            for name in (
                "address",
                "instrument_address",
                "base_url",
                "model_name",
                "serial_number",
                "profile_path",
            )
        }
        has_hardware_identity = any(
            backend_identity.get(name)
            for name in ("address", "instrument_address", "base_url", "serial_number")
        )
        if not has_hardware_identity:
            backend_identity["session_instance_key"] = self._uncertainty_instance_key
        config_identity = {
            "manufacturer": getattr(self.config, "manufacturer", None),
            "model": getattr(self.config, "model", self.__class__.__name__),
        }
        digest = hashlib.sha256(
            json.dumps(
                {"backend": backend_identity, "config": config_identity},
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"{config_identity['model']}:source:{digest}"

    def _validate_features_against_scpi(
        self, feature_map: dict[str, dict[str, list[str]]], strict: bool = False
    ) -> None:
        """
        Validate feature→SCPI mappings against the loaded SCPI engine.

        Parameters:
            feature_map: Mapping like
                { feature_name: { "required_scpi": [...], "optional_scpi": [...] }, ... }
            strict: When True, raise if any required SCPI names are missing.

        Behavior:
            - Ensures every entry in "required_scpi" exists in the SCPIEngine.
            - "optional_scpi" entries are informational and do not affect validation.
        """
        # The profile is authoritative.  Do not hide malformed engine state
        # behind a broad exception: ``list_names`` either returns the loaded
        # aliases or propagates the actual configuration failure.
        available = set(self._scpi_engine.list_names())

        missing: dict[str, list[str]] = {}
        for feat, spec in (feature_map or {}).items():
            spec = spec or {}
            required = list(spec.get("required_scpi", []) or [])
            missing_req = [name for name in required if name not in available]
            if missing_req:
                missing[feat] = missing_req

        if missing:
            details = "; ".join(f"{feat}: {names}" for feat, names in missing.items())
            if strict:
                raise RuntimeError(f"Missing required SCPI for features -> {details}")
            else:
                self._logger.warning(f"Missing required SCPI for features -> {details}")

    @classmethod
    def operation_descriptors(cls) -> tuple[OperationDescriptor, ...]:
        """Return merged operation descriptors declared along the class MRO."""

        merged: dict[str, OperationDescriptor] = {}
        for klass in reversed(cls.mro()):
            for descriptor in getattr(klass, "OPERATION_CONTRACT", ()) or ():
                merged[descriptor.operation_id] = descriptor
        return tuple(merged.values())

    def list_operations(self, *, include_unsupported: bool = True) -> list[str]:
        """List high-level operation IDs declared by this driver class."""

        descriptors = self.operation_descriptors()
        if include_unsupported:
            return [descriptor.operation_id for descriptor in descriptors]
        return [
            descriptor.operation_id
            for descriptor in descriptors
            if self.supports_operation(descriptor.operation_id)
        ]

    def describe_operations(
        self,
        *,
        group: str | None = None,
        scope: OperationScope | None = None,
        include_unsupported: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """Describe declared operations by semantic group, without backend I/O.

        Unannotated groups use "general". Omitted scope does not classify
        an operation. This view has no argument context; inspect an individual
        description with context for conditional options and constraints.
        """

        grouped: dict[str, list[dict[str, Any]]] = {}
        for descriptor in self.operation_descriptors():
            # Generic profile-defined methods are model-scoped in the catalog;
            # do not change the legacy single-operation description.
            operation_scope = descriptor.scope
            if operation_scope is None and descriptor.public_method == "execute_profile_operation":
                operation_scope = "model"
            if scope is not None and scope != operation_scope:
                continue
            description = self.describe_operation(
                descriptor.operation_id, include_unsupported=include_unsupported
            )
            if operation_scope is not None and descriptor.scope is None:
                description = description.copy()
                description["scope"] = operation_scope
            operation_group = description.get("group") or "general"
            if group is not None and group != operation_group:
                continue
            if not include_unsupported and not description["support"]["supported"]:
                continue
            grouped.setdefault(operation_group, []).append(description)
        return grouped

    def describe_operation(
        self,
        operation_id: str,
        *,
        context: dict[str, Any] | None = None,
        include_unsupported: bool = False,
    ) -> dict[str, Any]:
        """Describe one high-level operation using the shared resolver."""

        return self._operation_resolver().describe_operation(
            operation_id,
            context=context,
            include_unsupported=include_unsupported,
            method_owner=self,
        )

    def _build_profile_alias(self, alias: str, **params: Any) -> list[str]:
        """Build a required private profile transport alias."""

        try:
            commands = self._scpi_engine.build(alias, **params)
        except KeyError as exc:
            raise InstrumentConfigurationError(
                self.config.model,
                "Profile does not implement the requested operation.",
            ) from exc
        if not commands:
            raise InstrumentConfigurationError(
                self.config.model,
                "Profile operation produced no command.",
            )
        return commands

    def _send_profile_alias(self, alias: str, **params: Any) -> None:
        """Build and send a private profile transport alias."""

        for command in self._build_profile_alias(alias, **params):
            self._send_command(command)

    @contextmanager
    def _profile_transaction(self) -> Iterator[None]:
        """Keep an entire profile command group on one local resource transaction."""
        with self._operation_lock:
            source = self._backend_source
            # Do not allocate a pending backend merely to look for a lock.
            resource_lock = (
                None if isinstance(source, _BackendFactory) else getattr(source, "lock", None)
            )
            if resource_lock is not None and hasattr(resource_lock, "__enter__"):
                with resource_lock:
                    yield
            else:
                yield

    def _preflight_reader(self, transport: str) -> Callable[[], Any]:
        raw = transport == "read_raw"
        supported = self.supports_read_raw() if raw else self.supports_read()
        if not supported:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile requires backend {transport}(); backend does not support reads without a command.",
            )
        self._ensure_backend_connected()
        prepare = getattr(self._backend, "prepare_read", None)
        if callable(prepare):
            prepare(raw=raw)
        reader = getattr(self._backend, transport, None)
        if not callable(reader):
            raise InstrumentConfigurationError(
                self.config.model, f"Backend does not provide {transport}()."
            )
        return reader

    def _query_profile_alias(self, alias: str, **params: Any) -> str:
        """Execute a complete profile query group, including native no-write reads."""
        commands = self._build_profile_alias(alias, **params)
        response = self._scpi_engine.describe(alias).get("response") or {}
        transport = response.get("transport", "query")
        with self._profile_transaction():
            if transport == "query":
                if not commands:
                    raise InstrumentConfigurationError(
                        self.config.model, f"Alias '{alias}' has no query command."
                    )
                for command in commands[:-1]:
                    self._send_command(command)
                return self._query(commands[-1])
            if transport != "read":
                raise InstrumentConfigurationError(
                    self.config.model,
                    f"Text alias API does not support response transport {transport!r}; use the native raw I/O API for bytes.",
                )
            reader = self._preflight_reader(transport)
            for command in commands:
                if command.strip():
                    self._send_command(command)
            return reader()

    def has_profile_alias(self, alias: str) -> bool:
        """Return whether a profile declares an SCPI alias, without backend I/O."""

        if not isinstance(alias, str) or not alias.strip():
            return False
        return self._scpi_engine.validate_presence([alias]).get(alias, False)

    def supports_error_queue(self) -> bool:
        """Return whether profile-backed SCPI error-queue checks are supported."""

        capabilities = getattr(self.config, "capabilities", {}) or {}
        setting = capabilities.get("error_queue") if isinstance(capabilities, Mapping) else None
        if setting is False:
            return False
        if isinstance(setting, Mapping) and setting.get("enabled") is False:
            return False
        return self.has_profile_alias("get_error")

    def _native_backend_method_available(self, method_name: str) -> bool | None:
        """Inspect native backend capability without allocating a pending backend.

        Unknown deferred factories return None; false is reserved for an
        already supplied backend that definitively lacks the method.
        """

        source = self._backend_source
        if not isinstance(source, _BackendFactory):
            return callable(getattr(source, method_name, None))

        backend_spec = getattr(self.config, "backend", None)
        backend_type = backend_spec.get("type") if isinstance(backend_spec, Mapping) else None
        if method_name == "read_status_byte" and str(backend_type).lower() in {"visa", "lamb"}:
            return True
        return None

    def read_status_byte(self) -> int:
        """Read a native backend status byte without issuing a SCPI query."""

        available = self._native_backend_method_available("read_status_byte")
        if available is False:
            raise InstrumentConfigurationError(
                self.config.model,
                "The selected backend does not provide native status-byte reading.",
            )
        self._ensure_backend_connected()
        reader = getattr(self._backend, "read_status_byte", None)
        if not callable(reader):
            raise InstrumentConfigurationError(
                self.config.model,
                "The selected backend does not provide native status-byte reading.",
            )
        value = reader()
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFF:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                message="Backend returned an invalid status byte; expected an integer from 0 to 255.",
            )
        return value

    def list_operation_options(
        self,
        operation_id: str,
        parameter: str,
        *,
        context: dict[str, Any] | None = None,
        include_unsupported: bool = False,
    ) -> list[dict[str, Any]]:
        """List semantic profile options for one public operation parameter.

        This entry point never returns private transport tokens or aliases.
        """

        return self._operation_resolver().list_options(
            operation_id,
            parameter,
            context=context,
            include_unsupported=include_unsupported,
            method_owner=self,
        )

    def _operation_resolver(self) -> OperationResolver:
        """Return a backend-independent resolver for the current profile."""

        return OperationResolver(self.config, self.operation_descriptors(), self._scpi_engine)

    def _resolve_operation_parameter(
        self,
        operation_id: str,
        parameter: str,
        value: Any,
        *,
        context: dict[str, Any] | None = None,
    ):
        """Resolve one public operation input through the shared resolver."""

        return self._operation_resolver().resolve_parameter(
            operation_id, parameter, value, context=context
        )

    def _resolve_operation_arguments(
        self,
        operation_id: str,
        arguments: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Validate a complete public call and return private alias arguments."""

        return self._operation_resolver().resolve_arguments(
            operation_id, arguments, context=context
        )

    def _resolve_transport_response(
        self,
        operation_id: str,
        parameter: str,
        value: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        return self._operation_resolver().resolve_transport_response(
            operation_id, parameter, value, context=context
        )

    def supports_operation(self, operation_id: str) -> bool:
        """Return True when the loaded profile can support this operation."""

        return self._operation_support_report(operation_id).supported

    def _operation_support_report(
        self, operation_id: str, *, check_parameters: bool = False
    ) -> OperationSupportReport:
        """Return support information from the shared profile resolver."""

        report = self._operation_resolver().support_report(
            operation_id, check_parameters=False, method_owner=self
        )
        if not check_parameters:
            return report

        # The legacy strict contract audit also checks every SCPI placeholder,
        # including placeholders not explicitly bound by a high-level method.
        # Keep that audit for ``validate_operation_contract`` while ordinary
        # discovery remains entirely resolver-backed.
        descriptor = self._get_operation_descriptor(operation_id)
        missing = tuple(self._missing_operation_parameter_metadata(descriptor))
        if not missing:
            return report
        return OperationSupportReport(
            operation_id=report.operation_id,
            supported=False,
            capability_enabled=report.capability_enabled,
            missing_required_aliases=report.missing_required_aliases,
            missing_optional_aliases=report.missing_optional_aliases,
            missing_parameter_metadata=missing,
            missing_capability_metadata=report.missing_capability_metadata,
            required=report.required,
            reason="missing parameter metadata",
        )

    def validate_operation_contract(
        self,
        *,
        strict: bool = False,
        include_unsupported: bool = False,
        check_parameters: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Validate this profile against the driver's operation descriptors.

        By default, operations gated by disabled capabilities are reported but
        not considered failures. If ``strict`` is true, incomplete required
        profile operations raise ``RuntimeError``.
        """

        reports = {
            descriptor.operation_id: self._operation_support_report(
                descriptor.operation_id, check_parameters=check_parameters
            )
            for descriptor in self.operation_descriptors()
        }
        failures = {
            operation_id: report
            for operation_id, report in reports.items()
            if report.required
            and report.capability_enabled
            and (
                report.missing_required_aliases
                or report.missing_parameter_metadata
                or report.missing_capability_metadata
            )
        }
        if strict and failures:
            details = "; ".join(
                f"{operation_id}: transport_complete={not report.missing_required_aliases} "
                f"parameters={list(report.missing_parameter_metadata)} "
                f"capabilities={list(report.missing_capability_metadata)}"
                for operation_id, report in failures.items()
            )
            raise RuntimeError(f"Missing required profile operation support -> {details}")
        visible = (
            reports
            if include_unsupported
            else {
                operation_id: report
                for operation_id, report in reports.items()
                if report.capability_enabled
            }
        )
        return {operation_id: report.to_dict() for operation_id, report in visible.items()}

    def _get_operation_descriptor(self, operation_id: str) -> OperationDescriptor:
        for descriptor in self.operation_descriptors():
            if descriptor.operation_id == operation_id:
                return descriptor
        raise KeyError(f"Operation '{operation_id}' is not declared by {self.__class__.__name__}")

    def _operation_parameter_bindings(
        self, descriptor: OperationDescriptor, parameter: str
    ) -> list[tuple[str, str]]:
        return self._operation_resolver()._bindings(descriptor, parameter)

    def _missing_operation_parameter_metadata(self, descriptor: OperationDescriptor) -> list[str]:
        missing: list[str] = []
        operation = self.config.operation_options.operation(descriptor.operation_id)
        parameters = operation.parameters if operation else {}
        method_name = descriptor.public_method or descriptor.operation_id
        method = getattr(self, method_name, None)
        if callable(method):
            for name, parameter in inspect.signature(method).parameters.items():
                if parameter.kind in {
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                }:
                    continue
                if name not in parameters:
                    missing.append(name)
        for parameter in parameters:
            spec = parameters[parameter]
            if not spec.transport_parameter or (
                spec.source is not None and spec.source.startswith("measurement_functions")
            ):
                continue
            if not self._operation_parameter_bindings(descriptor, parameter):
                missing.append(parameter)
        return sorted(set(missing))

    @classmethod
    def from_config(
        cls: type[Instrument], config: InstrumentConfig, debug_mode: bool = False
    ) -> Instrument:
        if not isinstance(config, InstrumentConfig):
            raise InstrumentConfigurationError(
                cls.__name__, "from_config expects an InstrumentConfig object."
            )
        raise NotImplementedError(
            "Instrument.from_config() does not select communication backends. "
            "Use AutoInstrument.from_config() or instantiate the concrete driver with "
            "an explicit backend."
        )

    def _read_to_np(self, data: bytes) -> np.ndarray:
        """Parses SCPI binary block data into a NumPy array.

        This utility method decodes the standard SCPI binary block format, which
        is commonly used for transferring large datasets like waveforms. The format
        is typically `#<N><Length><Data>`, where `<N>` is the number of digits
        in `<Length>`.

        Args:
            data: The raw bytes received from the instrument, expected to be in
                  SCPI binary block format.

        Returns:
            A NumPy array containing the parsed data.

        Raises:
            InstrumentDataError: If the data is not in the expected format.
        """
        try:
            return definite_length_block_to_array(data, dtype=np.uint8)
        except (BinaryBlockParseError, UnicodeDecodeError) as e:
            self._logger.debug(
                f"Error parsing SCPI binary block in _read_to_np: {e}. Raw data (first 50 bytes): {data[:50]!r}"
            )
            raise InstrumentDataError(
                self.config.model, "Failed to parse binary data from instrument."
            ) from e

    def _send_command(
        self, command: str, skip_check: bool = False, timeout_ms: int | None = None
    ) -> None:
        """Sends a command to the instrument and logs the interaction.

        This is a low-level compatibility wrapper. The implementation lives in
        ``InstrumentCommandSession`` so command transport and logging can be
        tested independently from the base driver surface.
        """
        with self.temporary_communication_timeout(timeout_ms):
            self._command_session.send_command(command, skip_check=skip_check)

    def _query(
        self,
        query: str,
        delay: float | None = None,
        skip_check: bool = False,
        timeout_ms: int | None = None,
    ) -> str:
        """Sends a query to the instrument and returns a string response."""
        with self.temporary_communication_timeout(timeout_ms):
            return self._command_session.query(query, delay=delay, skip_check=skip_check)

    def _query_raw(
        self, query: str, delay: float | None = None, timeout_ms: int | None = None
    ) -> bytes:
        """Sends a query and returns a raw binary response."""
        with self.temporary_communication_timeout(timeout_ms):
            return self._command_session.query_raw(query, delay=delay)

    def lock_panel(self, lock: bool = True) -> None:
        """
        Locks or unlocks the front panel of the instrument.
        """
        alias = "panel_lock" if lock else "panel_local"
        self._send_profile_alias(alias)
        self._logger.debug(f"Panel {'locked' if lock else 'unlocked (local control enabled)'}.")

    def attempt_error_recovery(self) -> bool:
        """Attempts to recover from instrument error states."""
        return self._error_queue.attempt_recovery()

    def _wait(self) -> None:
        """Blocks until previous commands have completed using *OPC?."""
        self._operation_waiter.wait()

    def _wait_event(self) -> None:
        """Polls the Standard Event Status Register until a non-zero value."""
        self._operation_waiter.wait_event()

    def _history(self) -> None:
        """Prints history of executed commands."""
        self._command_session.print_history()

    def _error_check(self) -> None:
        """Checks for errors on the instrument by querying SYSTem:ERRor?."""
        if not self.supports_error_queue():
            return
        self._error_queue.check()

    def supports_identity(self) -> bool:
        """Return explicit profile identity support without performing I/O."""
        capabilities = getattr(self.config, "capabilities", {})
        setting = capabilities.get("identity") if isinstance(capabilities, Mapping) else None
        return not (
            setting is False or (isinstance(setting, Mapping) and setting.get("enabled") is False)
        )

    def id(self) -> str:
        """
        Query the instrument for its identification string (*IDN?).
        """
        if not self.supports_identity():
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not expose identity capability."
            )
        name = self._query_profile_alias("identify")
        self._logger.debug(f"Connected to {name}")
        return name

    def close(self) -> None:
        """Close an activated backend without allocating an unused one."""
        try:
            super().close()
        except Exception as exc:
            self._logger.error(
                "Instrument '%s': Error during backend close: %s", self.config.model, exc
            )
        else:
            self._logger.info("Instrument '%s': Connection closed.", self.config.model)

    def reset(self) -> None:
        """Reset the instrument to its default settings (*RST)."""
        self._send_profile_alias("reset")
        self._logger.debug("Instrument reset to default settings (*RST).")

    def run_self_test(self, full_test: bool = True) -> str:
        """
        Executes the instrument's internal self-test routine (*TST?) and reports result.
        """
        if not full_test:
            self._logger.debug(
                "Note: `full_test=False` currently ignored, running standard *TST? self-test."
            )

        self._logger.debug("Running self-test (*TST?)...")
        options = self.config.operation_options
        spec = options.operation("run_self_test")
        mapped_alias = spec.transport.get("self_test") if spec else None
        q = self._build_profile_alias(mapped_alias or "self_test")[-1]
        timeout = options.parameter("run_self_test", "timeout_ms")
        timeout_ms = int(timeout.default) if timeout and type(timeout.default) is int else None
        result_str = ""
        try:
            if mapped_alias is not None:
                # A direct diagnostic leaves any pending error queue entries to the caller.
                with self._profile_transaction():
                    result_str = self._query(q, skip_check=True, timeout_ms=timeout_ms)
            else:
                result_str = self._query(q)
            code = int(result_str.strip())
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=q,
                message=f"Unexpected non-integer response: '{result_str}'",
            ) from e
        except InstrumentCommunicationError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=q,
                message="Failed to execute query.",
            ) from e

        if mapped_alias is not None:
            return "Passed" if code == 0 else f"Failed: Code {code}. Error queue not read."

        if code == 0:
            self._logger.debug("Self-test query (*TST?) returned 0 (Passed).")
            errors_after_test = self.get_all_errors() if self.supports_error_queue() else []
            if errors_after_test:
                details = "; ".join([f"{c}: {m}" for c, m in errors_after_test])
                warn_msg = (
                    f"Self-test query passed, but errors found in queue afterwards: {details}"
                )
                self._logger.debug(warn_msg)
            return "Passed"
        else:
            self._logger.debug(
                f"Self-test query (*TST?) returned non-zero code: {code} (Failed). Reading error queue..."
            )
            errors = self.get_all_errors() if self.supports_error_queue() else []
            details = (
                "; ".join([f"{c}: {m}" for c, m in errors])
                if errors
                else "No specific errors reported in queue"
            )
            fail_msg = f"Failed: Code {code}. Errors: {details}"
            self._logger.debug(fail_msg)
            return fail_msg

    @classmethod
    def requires(cls, requirement: str) -> Callable:
        """
        Decorator to specify method requirements based on instrument configuration.
        """

        def decorator(func: Callable) -> Callable:
            def wrapped_func(self: Instrument, *args: Any, **kwargs: Any) -> Any:
                if not hasattr(self.config, "requires") or not callable(self.config.requires):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Config object missing 'requires' method for decorator.",
                    )

                if self.config.requires(requirement):
                    return func(self, *args, **kwargs)
                else:
                    func_name = getattr(func, "__name__", func.__class__.__name__)
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Method '{func_name}' requires '{requirement}', which is not available for this instrument model/configuration.",
                    )

            return wrapped_func

        return decorator

    def clear_status(self) -> None:
        """Clears the instrument's status registers and error queue (*CLS)."""
        self._error_queue.clear_status()

    def get_all_errors(self) -> list[tuple[int, str]]:
        """Reads and clears all errors currently present in the instrument error queue."""
        if not self.supports_error_queue():
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement an error queue."
            )
        return self._error_queue.get_all_errors()

    def get_error(self) -> tuple[int, str]:
        """Reads and clears the oldest error from the instrument error queue."""
        if not self.supports_error_queue():
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement an error queue."
            )
        return self._error_queue.get_error()

    def wait_for_operation_complete(
        self, query_instrument: bool = True, timeout: float = 10.0
    ) -> str | None:
        """Waits for the instrument to finish pending overlapping commands."""
        return self._operation_waiter.wait_for_operation_complete(
            query_instrument=query_instrument, timeout=timeout
        )

    @contextmanager
    def temporary_communication_timeout(self, timeout_ms: int | None) -> Iterator[None]:
        """Temporarily override the backend timeout for one long operation.

        Normal SCPI calls should keep the backend's configured default timeout
        low. Use this context for known long-running operations, such as deep
        waveform transfers or instrument-side analysis, so the larger time
        budget is scoped to exactly the operation that needs it.
        """
        if timeout_ms is None:
            yield
            return
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")

        previous_timeout_ms = self.get_communication_timeout()
        self.set_communication_timeout(timeout_ms)
        try:
            yield
        finally:
            self.set_communication_timeout(previous_timeout_ms)

    def set_communication_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout on the backend."""
        self._backend.set_timeout(timeout_ms)
        self._logger.debug(f"Communication timeout set to {timeout_ms} ms on backend.")

    def get_communication_timeout(self) -> int:
        """Gets the communication timeout from the backend."""
        timeout = self._backend.get_timeout()
        self._logger.debug(f"Communication timeout retrieved from backend: {timeout} ms.")
        return timeout

    def health_check(self) -> HealthReport:
        """Performs a basic health check of the instrument."""
        return self._health_monitor.check()
