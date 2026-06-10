from __future__ import annotations

from collections.abc import Callable
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

    def _send_command(self, command: str, skip_check: bool = False) -> None:
        """Sends a command to the instrument and logs the interaction.

        This is a low-level compatibility wrapper. The implementation lives in
        ``InstrumentCommandSession`` so command transport and logging can be
        tested independently from the base driver surface.
        """
        self._command_session.send_command(command, skip_check=skip_check)

    def _query(self, query: str, delay: float | None = None, skip_check: bool = False) -> str:
        """Sends a query to the instrument and returns a string response."""
        return self._command_session.query(query, delay=delay, skip_check=skip_check)

    def _query_raw(self, query: str, delay: float | None = None) -> bytes:
        """Sends a query and returns a raw binary response."""
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
