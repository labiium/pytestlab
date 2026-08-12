from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from typing import Generic
from typing import TypeVar

import numpy as np

from ..common.health import HealthReport  # Adjusted import
from ..config import InstrumentConfig  # Assuming InstrumentConfig is the base Pydantic model
from ..devices.base import Device
from ..devices.base import DeviceIO
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from .command_session import InstrumentCommandSession
from .error_queue import InstrumentErrorQueue
from .health_monitor import InstrumentHealthMonitor
from .operation_contract import OperationDescriptor
from .operation_contract import OperationSupportReport
from .operation_waiter import InstrumentOperationWaiter
from .scpi_binary import BinaryBlockParseError
from .scpi_binary import definite_length_block_to_array
from .scpi_engine import SCPIEngine

# Forward reference for ConfigType if InstrumentConfig is not fully defined/imported yet,
# or if it's defined in a way that causes circular dependencies.
# For this refactor, we assume InstrumentConfig is available.
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

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = ()

    # Class-level annotations for instance variables
    config: ConfigType
    _backend: InstrumentIO
    _command_log: list[dict[str, Any]]
    _logger: Any  # Actual type would be logging.Logger, using Any if Logger type not imported

    def __init__(self, config: ConfigType, backend: InstrumentIO, **kwargs: Any) -> None:
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
        # Get SCPI data and convert to compatible format
        if hasattr(self.config, "scpi") and self.config.scpi is not None:
            if hasattr(self.config.scpi, "model_dump"):
                scpi_section = self.config.scpi.model_dump()
            else:
                scpi_section = {}
        else:
            scpi_section = {}
        self.scpi_engine = SCPIEngine(scpi_section)
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
        # Collect available SCPI names from the engine
        available = set()
        try:
            specs = getattr(self.scpi_engine, "_specs", {})
            if isinstance(specs, dict):
                available = set(specs.keys())
        except Exception:
            available = set()

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

    def describe_operation(
        self, operation_id: str, *, include_scpi: bool = False
    ) -> dict[str, Any]:
        """Describe one high-level operation and its current support status."""

        descriptor = self._get_operation_descriptor(operation_id)
        support = self.operation_support_report(operation_id)
        result = {**descriptor.to_dict(), "support": support.to_dict()}
        if include_scpi:
            aliases = [*descriptor.required_aliases, *descriptor.optional_aliases]
            result["scpi"] = {
                alias: self.describe_scpi_alias(alias)
                for alias in aliases
                if self.scpi_engine.validate_presence([alias]).get(alias, False)
            }
            result["parameter_bindings"] = self._operation_parameter_binding_diagnostics(descriptor)
        return result

    def describe_scpi_alias(self, alias: str) -> dict[str, Any]:
        """Describe one loaded SCPI command/query alias from the profile."""

        return self.scpi_engine.describe(alias)

    def build_scpi_alias(self, alias: str, **params: Any) -> list[str]:
        """Build SCPI strings for an alias without sending them."""

        return self.scpi_engine.build(alias, **params)

    def build_required_scpi_alias(self, alias: str, **params: Any) -> list[str]:
        """Build a required SCPI alias or fail with a profile-configuration error."""

        try:
            return self.scpi_engine.build(alias, **params)
        except KeyError as exc:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile is missing required SCPI alias '{alias}'.",
            ) from exc

    def send_scpi_alias(self, alias: str, **params: Any) -> None:
        """Build and send a required SCPI command alias."""

        for command in self.build_required_scpi_alias(alias, **params):
            self._send_command(command)

    def query_scpi_alias(self, alias: str, **params: Any) -> str:
        """Build and query a required SCPI alias.

        Multi-command query aliases are treated as setup commands followed by a
        final query. This preserves the declarative SCPI sequence instead of
        guessing which element should return data.
        """

        commands = self.build_required_scpi_alias(alias, **params)
        if not commands:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile SCPI alias '{alias}' produced no query command.",
            )
        for command in commands[:-1]:
            self._send_command(command)
        return self._query(commands[-1])

    def list_operation_options(self, operation_id: str, parameter: str) -> list[dict[str, Any]]:
        """List raw SCPI options for an operation parameter.

        Explicit ``OperationDescriptor.parameters`` bindings win. Without an
        explicit binding, required aliases are scanned before optional aliases.
        Divergent multi-alias matches are rejected to avoid hidden assumptions.
        """

        descriptor = self._get_operation_descriptor(operation_id)
        bindings = self._operation_parameter_bindings(descriptor, parameter)
        option_sets: list[tuple[str, str, list[dict[str, Any]]]] = []
        for alias, alias_parameter in bindings:
            try:
                options = self.scpi_engine.list_options(alias, alias_parameter)
            except KeyError:
                continue
            if options:
                option_sets.append((alias, alias_parameter, options))

        if not option_sets:
            return []
        token_sets = {
            tuple(sorted(str(choice.get("token")) for choice in options))
            for _, _, options in option_sets
        }
        if len(token_sets) > 1:
            candidates = ", ".join(f"{alias}.{param}" for alias, param, _ in option_sets)
            raise ValueError(
                f"Ambiguous operation parameter '{operation_id}.{parameter}' across {candidates}; "
                "add explicit OperationDescriptor.parameters binding."
            )
        merged: dict[str, dict[str, Any]] = {}
        for _, _, options in option_sets:
            for choice in options:
                self._merge_operation_choice(merged, choice)
        return list(merged.values())

    @staticmethod
    def _merge_operation_choice(merged: dict[str, dict[str, Any]], choice: dict[str, Any]) -> None:
        token = str(choice.get("token"))
        existing = merged.setdefault(token, dict(choice))
        aliases = set(existing.get("aliases", []) or [])
        aliases.update(choice.get("aliases", []) or [])
        if aliases:
            existing["aliases"] = sorted(aliases)
        Instrument._merge_choice_text_field(existing, choice, "label", "labels")
        Instrument._merge_choice_text_field(existing, choice, "description", "descriptions")
        Instrument._merge_choice_evidence(existing, choice)

    @staticmethod
    def _merge_choice_text_field(
        existing: dict[str, Any], choice: dict[str, Any], singular: str, plural: str
    ) -> None:
        values: list[Any] = []
        current_plural = existing.get(plural)
        if isinstance(current_plural, list):
            values.extend(current_plural)
        current_singular = existing.get(singular)
        if current_singular not in (None, ""):
            values.append(current_singular)
        incoming_singular = choice.get(singular)
        if incoming_singular not in (None, ""):
            values.append(incoming_singular)
        incoming_plural = choice.get(plural)
        if isinstance(incoming_plural, list):
            values.extend(incoming_plural)
        deduped = Instrument._dedupe_preserving_order(values)
        if deduped:
            existing[plural] = deduped
            existing[singular] = deduped[0]

    @staticmethod
    def _merge_choice_evidence(existing: dict[str, Any], choice: dict[str, Any]) -> None:
        evidence_values: list[Any] = []
        current_evidence = existing.get("evidence")
        if isinstance(current_evidence, list):
            evidence_values.extend(current_evidence)
        elif current_evidence not in (None, ""):
            evidence_values.append(current_evidence)
        incoming_evidence = choice.get("evidence")
        if isinstance(incoming_evidence, list):
            evidence_values.extend(incoming_evidence)
        elif incoming_evidence not in (None, ""):
            evidence_values.append(incoming_evidence)
        deduped_evidence = Instrument._dedupe_preserving_order(evidence_values)
        if len(deduped_evidence) == 1:
            existing["evidence"] = deduped_evidence[0]
        elif deduped_evidence:
            existing["evidence"] = deduped_evidence

    @staticmethod
    def _dedupe_preserving_order(values: list[Any]) -> list[Any]:
        deduped: list[Any] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped

    def supports_operation(self, operation_id: str) -> bool:
        """Return True when the loaded profile can support this operation."""

        return self.operation_support_report(operation_id).supported

    def operation_support_report(
        self, operation_id: str, *, check_parameters: bool = False
    ) -> OperationSupportReport:
        """Return structured support information for one operation."""

        descriptor = self._get_operation_descriptor(operation_id)
        capability_enabled = self._operation_capability_enabled(descriptor)
        if not capability_enabled:
            return OperationSupportReport(
                operation_id=descriptor.operation_id,
                supported=False,
                capability_enabled=False,
                required=descriptor.required,
                reason=f"capability '{descriptor.capability}' is not enabled",
            )

        required_presence = self.scpi_engine.validate_presence(list(descriptor.required_aliases))
        optional_presence = self.scpi_engine.validate_presence(list(descriptor.optional_aliases))
        missing_required = tuple(
            alias for alias, present in required_presence.items() if not present
        )
        missing_optional = tuple(
            alias for alias, present in optional_presence.items() if not present
        )
        missing_parameter_metadata: tuple[str, ...] = ()
        if check_parameters:
            missing_parameter_metadata = tuple(
                self._missing_operation_parameter_metadata(descriptor)
            )
        return OperationSupportReport(
            operation_id=descriptor.operation_id,
            supported=not missing_required and not missing_parameter_metadata,
            capability_enabled=True,
            missing_required_aliases=missing_required,
            missing_optional_aliases=missing_optional,
            missing_parameter_metadata=missing_parameter_metadata,
            required=descriptor.required,
            reason=(
                "missing required aliases"
                if missing_required
                else "missing parameter metadata"
                if missing_parameter_metadata
                else None
            ),
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
        not considered failures. If ``strict`` is true, missing required aliases
        for enabled operations raise ``RuntimeError``.
        """

        reports = {
            descriptor.operation_id: self.operation_support_report(
                descriptor.operation_id, check_parameters=check_parameters
            )
            for descriptor in self.operation_descriptors()
        }
        failures = {
            operation_id: report
            for operation_id, report in reports.items()
            if report.required
            and report.capability_enabled
            and (report.missing_required_aliases or report.missing_parameter_metadata)
        }
        if strict and failures:
            details = "; ".join(
                f"{operation_id}: aliases={list(report.missing_required_aliases)} "
                f"parameters={list(report.missing_parameter_metadata)}"
                for operation_id, report in failures.items()
            )
            raise RuntimeError(f"Missing required operation SCPI support -> {details}")
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

    def _operation_capability_enabled(self, descriptor: OperationDescriptor) -> bool:
        if descriptor.capability is None:
            return True
        value = getattr(self.config, descriptor.capability, None)
        return bool(value)

    def _operation_parameter_binding_diagnostics(
        self, descriptor: OperationDescriptor
    ) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {}
        for parameter in descriptor.parameters:
            bindings = self._operation_parameter_bindings(descriptor, parameter)
            diagnostics[parameter] = [
                {"alias": alias, "parameter": alias_parameter}
                for alias, alias_parameter in bindings
            ]
        return diagnostics

    def _operation_parameter_bindings(
        self, descriptor: OperationDescriptor, parameter: str
    ) -> list[tuple[str, str]]:
        raw_spec = descriptor.parameters.get(parameter) if descriptor.parameters else None
        if isinstance(raw_spec, dict) and raw_spec.get("bindings"):
            bindings: list[tuple[str, str]] = []
            for binding in raw_spec["bindings"]:
                if isinstance(binding, dict):
                    bindings.append(
                        (str(binding.get("alias")), str(binding.get("parameter", parameter)))
                    )
            return bindings

        bindings = []
        for alias in [*descriptor.required_aliases, *descriptor.optional_aliases]:
            try:
                parameters = self.scpi_engine.list_parameters(alias)
            except KeyError:
                continue
            if parameter in parameters:
                bindings.append((alias, parameter))
        return bindings

    def _missing_operation_parameter_metadata(self, descriptor: OperationDescriptor) -> list[str]:
        missing: list[str] = []
        alias_placeholders: dict[str, set[str]] = {}
        for alias in [*descriptor.required_aliases, *descriptor.optional_aliases]:
            try:
                alias_placeholders[alias] = set(
                    self.scpi_engine.validate_placeholders(alias)["placeholders"]
                )
            except KeyError:
                continue

        def validate_alias_parameter(alias: str, alias_parameter: str) -> list[str]:
            binding_key = f"{alias}.{alias_parameter}"
            try:
                metadata = self.scpi_engine.describe_parameter(alias, alias_parameter)
            except KeyError:
                return [binding_key]
            source = metadata.get("metadata_source")
            if source == "inferred":
                return [f"{binding_key}:inferred"]
            if metadata.get("kind") == "raw" and not (
                metadata.get("allow_raw") or metadata.get("description") or metadata.get("evidence")
            ):
                return [f"{binding_key}:unjustified-raw"]
            return []

        covered: set[str] = set()
        for parameter in descriptor.parameters:
            bindings = self._operation_parameter_bindings(descriptor, parameter)
            if not bindings:
                missing.append(parameter)
                continue
            for alias, alias_parameter in bindings:
                binding_key = f"{alias}.{alias_parameter}"
                if alias_parameter not in alias_placeholders.get(alias, set()):
                    missing.append(f"{binding_key}:binding-not-placeholder")
                    continue
                covered.add(binding_key)
                missing.extend(validate_alias_parameter(alias, alias_parameter))

        exemptions = getattr(descriptor, "parameter_exemptions", {}) or {}
        for alias, placeholders in alias_placeholders.items():
            for placeholder in placeholders:
                binding_key = f"{alias}.{placeholder}"
                if binding_key in covered or binding_key in exemptions:
                    continue
                alias_missing = validate_alias_parameter(alias, placeholder)
                if alias_missing:
                    missing.extend(alias_missing)
                    continue
                covered.add(binding_key)
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
        if lock:
            try:
                cmds = self.scpi_engine.build("panel_lock")
            except Exception:
                cmds = [":SYSTem:LOCK"]
        else:
            try:
                cmds = self.scpi_engine.build("panel_local")
            except Exception:
                cmds = [":SYSTem:LOCal"]
        for c in cmds:
            self._send_command(c)
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
        self._error_queue.check()

    def id(self) -> str:
        """
        Query the instrument for its identification string (*IDN?).
        """
        q = "*IDN?"
        try:
            candidate = self.scpi_engine.build("identify")[0]
            if isinstance(candidate, str) and "IDN" in candidate.upper():
                q = candidate
        except Exception:
            pass
        name = self._query(q)
        self._logger.debug(f"Connected to {name}")
        return name

    def close(self) -> None:
        """Close the connection to the instrument via the backend."""
        try:
            model_name_for_logger = (
                self.config.model if hasattr(self.config, "model") else self.__class__.__name__
            )
            self._logger.info(f"Instrument '{model_name_for_logger}': Closing connection.")
            self._backend.close()  # Changed to use close
            self._backend_connected = False
            self._logger.info(f"Instrument '{model_name_for_logger}': Connection closed.")
        except Exception as e:
            model_name_for_logger = (
                self.config.model if hasattr(self.config, "model") else self.__class__.__name__
            )
            self._logger.error(
                f"Instrument '{model_name_for_logger}': Error during backend close: {e}"
            )
            # Optionally re-raise if failed close is critical:
            # raise InstrumentConnectionError(f"Failed to close backend connection: {e}") from e

    def reset(self) -> None:
        """Reset the instrument to its default settings (*RST)."""
        try:
            cmds = self.scpi_engine.build("reset")
        except Exception:
            cmds = ["*RST"]
        for c in cmds:
            self._send_command(c)
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
        try:
            q = self.scpi_engine.build("self_test")[0]
        except Exception:
            q = "*TST?"
        result_str = ""
        try:
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

        if code == 0:
            self._logger.debug("Self-test query (*TST?) returned 0 (Passed).")
            errors_after_test = self.get_all_errors()
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
            errors = self.get_all_errors()
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
        return self._error_queue.get_all_errors()

    def get_error(self) -> tuple[int, str]:
        """Reads and clears the oldest error from the instrument error queue."""
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

    def get_scpi_version(self) -> str:
        """
        Queries the version of the SCPI standard the instrument complies with.
        """
        try:
            q = self.scpi_engine.build("scpi_version")[0]
        except Exception:
            q = "SYSTem:VERSion?"
        response = (self._query(q)).strip()
        self._logger.debug(f"SCPI Version reported: {response}")
        return response

    def health_check(self) -> HealthReport:
        """Performs a basic health check of the instrument."""
        return self._health_monitor.check()
