from __future__ import annotations
from .._log import get_logger

from typing import Optional, Tuple, Any, Callable, Type, List as TypingList, Dict, Union, Protocol, TypeVar, Generic
from abc import abstractmethod
import numpy as np
# polars.List is a DataType, not for type hinting Python lists.
# from polars import List
from ..errors import InstrumentConnectionBusy, InstrumentConfigurationError, InstrumentNotFoundError, InstrumentCommunicationError, InstrumentConnectionError, InstrumentParameterError
from ..config import InstrumentConfig # Assuming InstrumentConfig is the base Pydantic model
from ..common.health import HealthReport, HealthStatus # Adjusted import
from .scpi_engine import SCPIEngine
import time

# Forward reference for ConfigType if InstrumentConfig is not fully defined/imported yet,
# or if it's defined in a way that causes circular dependencies.
# For this refactor, we assume InstrumentConfig is available.
ConfigType = TypeVar('ConfigType', bound='InstrumentConfig')

class InstrumentIO(Protocol):
    """Defines the interface for a synchronous instrument communication backend.

    This protocol specifies the essential methods that a synchronous backend
    (like a traditional VISA wrapper) must implement to be compatible with the
    instrument driver framework.
    """
    def connect(self) -> None:
        """Establishes the connection to the instrument."""
        ...
    def disconnect(self) -> None:
        """Terminates the connection to the instrument."""
        ...
    def write(self, cmd: str) -> None:
        """Sends a command to the instrument."""
        ...
    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """Sends a command and reads a string response."""
        ...
    def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        """Sends a command and reads a raw byte response."""
        ...
    def close(self) -> None:
        """Closes the instrument session, often an alias for disconnect."""
        ...

    def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout in milliseconds."""
        ...
    def get_timeout(self) -> int:
        """Gets the communication timeout in milliseconds."""
        ...

class AsyncInstrumentIO(Protocol):
    """Defines the interface for an asynchronous instrument communication backend.

    This protocol specifies the essential async methods that an asynchronous
    backend (e.g., using async VISA, HTTP, or a simulation) must implement.
    This is the primary interface used by the `Instrument` class.
    """
    def connect(self) -> None:
        """Establishes the connection to the instrument asynchronously."""
        ...
    def disconnect(self) -> None:
        """Terminates the connection to the instrument asynchronously."""
        ...
    def write(self, cmd: str) -> None:
        """Sends a command to the instrument asynchronously."""
        ...
    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """Sends a command and reads a string response asynchronously."""
        ...
    def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        """Sends a command and reads a raw byte response asynchronously."""
        ...
    def close(self) -> None:
        """Closes the instrument session asynchronously."""
        ...

    def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout in milliseconds asynchronously."""
        ...
    def get_timeout(self) -> int:
        """Gets the communication timeout in milliseconds asynchronously."""
        ...

class Instrument(Generic[ConfigType]):
    """Base class for all instrument drivers.

    This class provides the core functionality for interacting with an instrument
    through a standardized, asynchronous interface. It handles command sending,
    querying, error checking, and logging. It is designed to be subclassed for
    specific instrument types (e.g., Oscilloscope, PowerSupply).

    The `Instrument` class is generic and typed with `ConfigType`, which allows
    each subclass to specify its own Pydantic configuration model.

    Attributes:
        config (ConfigType): The Pydantic configuration model instance for this
                             instrument.
        _backend (AsyncInstrumentIO): The communication backend used to interact
                                      with the hardware or simulation.
        _command_log (List[Dict[str, Any]]): A log of all commands sent and
                                             responses received.
        _logger: The logger instance for this instrument.
    """

    # Class-level annotations for instance variables
    config: ConfigType
    _backend: AsyncInstrumentIO # Changed to AsyncInstrumentIO as per "True Async" approach
    _command_log: TypingList[Dict[str, Any]]
    _logger: Any # Actual type would be logging.Logger, using Any if Logger type not imported

    def __init__(self, config: ConfigType, backend: AsyncInstrumentIO, **kwargs: Any) -> None: # Changed to AsyncInstrumentIO
        """
        Initialize the Instrument class.

        Args:
            config (ConfigType): Configuration for the instrument.
            backend (AsyncInstrumentIO): The communication backend instance.
            **kwargs: Additional keyword arguments.
        """
        if not isinstance(config, InstrumentConfig): # Check against the bound base
            raise InstrumentConfigurationError(
                self.__class__.__name__,
                f"A valid InstrumentConfig-compatible object must be provided, but got {type(config).__name__}.",
            )

        self.config = config
        self._backend = backend # This will be an AsyncInstrumentIO instance
        self._command_log = []

        logger_name = self.config.model if hasattr(self.config, 'model') else self.__class__.__name__
        self._logger = get_logger(logger_name)

        self._logger.info(f"Instrument '{logger_name}': Initializing with backend '{type(backend).__name__}'.")
        self.scpi_engine = SCPIEngine(self.config.scpi)
    # Note: from_config might need to become async or handle async backend instantiation.
    # This will be addressed when AutoInstrument is updated.
    @classmethod
    def from_config(cls: Type[Instrument], config: InstrumentConfig, debug_mode: bool = False) -> Instrument:
        # This method will likely need significant changes to support async backends.
        # For now, it's a placeholder and might not work correctly with async backends.
        # It should ideally accept an async_mode flag or similar to determine backend type.
        if not isinstance(config, InstrumentConfig):
            raise InstrumentConfigurationError(
                cls.__name__, "from_config expects an InstrumentConfig object."
            )
        # The backend instantiation is missing here and is crucial.
        # This will be handled by AutoInstrument.from_config later.
        raise NotImplementedError(
            "from_config needs to be updated for async backend instantiation."
        )


    def connect_backend(self) -> None:
        """Establishes the connection to the instrument via the backend.

        This method must be called after the instrument is instantiated to open
        the communication channel. It delegates the connection logic to the
        underlying backend.

        Raises:
            InstrumentConnectionError: If the backend fails to connect.
        """
        logger_name = self.config.model if hasattr(self.config, 'model') else self.__class__.__name__
        try:
            self._backend.connect()
            self._logger.info(f"Instrument '{logger_name}': Backend connected.")
        except Exception as e:
            self._logger.error(f"Instrument '{logger_name}': Failed to connect backend: {e}")
            if hasattr(self._backend, 'disconnect'): # Check if disconnect is available (it should be for AsyncInstrumentIO)
                try:
                    self._backend.disconnect()
                except Exception as disc_e:
                    self._logger.error(f"Instrument '{logger_name}': Error disconnecting backend during failed connect: {disc_e}")
            raise InstrumentConnectionError(
                instrument=logger_name, message=f"Failed to connect backend: {e}"
            ) from e

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
        # The first character must be '#' to indicate a binary block.
        if not data.startswith(b'#'):
            self._logger.debug(f"Warning: Data for _read_to_np does not start with '#'. Attempting direct conversion. Raw data (first 20 bytes): {data[:20]}")
            # Fallback for non-standard data, which might be a simple header-less stream.
            # This is a best-effort attempt and may not work for all instruments.
            if len(data) > 10:
                end_slice = -1 if data.endswith(b'\n') else None
                return np.frombuffer(data[10:end_slice], dtype=np.uint8)
            return np.array([], dtype=np.uint8)

        try:
            len_digits_char = data[1:2].decode('ascii')
            if not len_digits_char.isdigit():
                raise InstrumentDataError(
                    self.config.model,
                    f"Invalid SCPI binary block: Length digit char '{len_digits_char}' is not a digit.",
                )

            num_digits_for_length = int(len_digits_char)
            if num_digits_for_length == 0:
                raise InstrumentDataError(
                    self.config.model,
                    "Indefinite length SCPI binary block (#0) not supported for waveform data.",
                )

            data_length_str = data[2 : 2 + num_digits_for_length].decode('ascii')
            actual_data_length = int(data_length_str)

            data_start_index = 2 + num_digits_for_length
            waveform_bytes_segment = data[data_start_index : data_start_index + actual_data_length]

            # Data type (e.g., np.uint8, np.int16, np.float32) should ideally be determined
            # by the instrument's :WAVeform:FORMat setting. Defaulting to uint8.
            np_array = np.frombuffer(waveform_bytes_segment, dtype=np.uint8)

            if len(waveform_bytes_segment) != actual_data_length:
                self._logger.debug(f"Warning: SCPI binary block data length mismatch. Expected {actual_data_length} bytes, got {len(waveform_bytes_segment)} bytes in segment.")

            return np_array
        except Exception as e:
            self._logger.debug(f"Error parsing SCPI binary block in _read_to_np: {e}. Raw data (first 50 bytes): {data[:50]}")
            raise InstrumentDataError(
                self.config.model, "Failed to parse binary data from instrument."
            ) from e

    def _send_command(self, command: str, skip_check: bool = False) -> None:
        """Sends a command to the instrument and logs the interaction.

        This is a low-level method for sending a command that does not expect a
        response. It includes error checking unless explicitly skipped.

        Args:
            command: The SCPI command string to send.
            skip_check: If True, the instrument's error queue will not be checked
                        after sending the command. This is useful for commands
                        that clear the error queue itself (e.g., `*CLS`).

        Raises:
            InstrumentCommunicationError: If writing the command to the backend fails.
        """
        try:
            self._backend.write(command)
            if not skip_check:
                self._error_check()
            self._command_log.append({"command": command, "success": True, "type": "write", "timestamp": time.time()})
        except Exception as e:
            self._command_log.append({"command": command, "success": False, "type": "write", "timestamp": time.time()})
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=command,
                message=f"Failed to send command: {e}",
            ) from e

    def _query(self, query: str, delay: Optional[float] = None) -> str:
        """Sends a query to the instrument and returns a string response.

        This is a low-level method for interacting with the instrument when a
        textual response is expected.

        Args:
            query: The SCPI query string to send.
            delay: An optional delay in seconds to wait after sending the query
                   before reading the response.

        Returns:
            The instrument's response, stripped of leading/trailing whitespace.

        Raises:
            InstrumentCommunicationError: If the query fails.
        """
        try:
            # self._logger.debug(f"QUERY: {query}" + (f" with delay: {delay}" if delay is not None else ""))
            response: str = self._backend.query(query, delay=delay)
            # self._logger.debug(f"RESPONSE: {response}")
            self._error_check() # Keep error check as it's a SYST:ERR? query
            self._command_log.append({"command": query, "success": True, "type": "query", "timestamp": time.time(), "response": response, "delay": delay})
            return response.strip()
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query", "timestamp": time.time(), "delay": delay})
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=query,
                message=f"Failed to query instrument: {e}",
            ) from e

    def _query_raw(self, query: str, delay: Optional[float] = None) -> bytes:
        """Sends a query and returns a raw binary response.

        This method is used for queries that return binary data, such as waveform
        data or screenshots. It does not perform an error check afterward, as the
        binary response would interfere with reading the error queue.

        Args:
            query: The SCPI query string to send.
            delay: An optional delay in seconds to wait before reading.

        Returns:
            The raw `bytes` response from the instrument.

        Raises:
            InstrumentCommunicationError: If the query fails.
        """
        try:
            # self._logger.debug(f"QUERY_RAW: {query}" + (f" with delay: {delay}" if delay is not None else ""))
            response: bytes = self._backend.query_raw(query, delay=delay)
            # self._logger.debug(f"RESPONSE (bytes): {len(response)} bytes")
            # Raw queries typically don't run _error_check() as the response might not be string-parsable for errors.
            self._command_log.append({"command": query, "success": True, "type": "query_raw", "timestamp": time.time(), "response_len": len(response), "delay": delay})
            return response
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query_raw", "timestamp": time.time(), "delay": delay})
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=query,
                message=f"Failed to raw query instrument: {e}",
            ) from e

    def lock_panel(self, lock: bool = True) -> None:
        """
        Locks or unlocks the front panel of the instrument.
        """
        if lock:
            self._send_command(":SYSTem:LOCK")
        else:
            self._send_command(":SYSTem:LOCal")
        self._logger.debug(f"Panel {'locked' if lock else 'unlocked (local control enabled)'}.")

    def _wait(self) -> None:
        """
        Blocks until all previous commands have been processed by the instrument using *OPC?.
        """
        try:
            self._backend.query("*OPC?") # delay=None by default for _backend.query
            self._logger.debug("Waiting for instrument to finish processing commands (*OPC? successful).")
            self._command_log.append({"command": "*OPC?", "success": True, "type": "wait", "timestamp": time.time()})
        except Exception as e:
            self._logger.debug(f"Error during *OPC? wait: {e}")
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command="*OPC?",
                message="Failed to wait for operation complete.",
            ) from e

    def _wait_event(self) -> None:
        """
        Blocks by polling the Standard Event Status Register (*ESR?) until a non-zero value.
        This is a basic implementation; specific event setup (*ESE) might be needed.
        """
        result = 0
        max_attempts = 100
        attempts = 0
        while result == 0 and attempts < max_attempts:
            try:
                esr_response = self._backend.query("*ESR?") # Use self._backend
                result = int(esr_response.strip())
            except Exception as e:
                self._logger.debug(f"Error querying *ESR? during _wait_event: {e}")
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command="*ESR?",
                    message="Failed to query *ESR? during wait.",
                ) from e
            time.sleep(0.1)
            attempts += 1

        if attempts >= max_attempts and result == 0 :
            self._logger.debug("Warning: _wait_event timed out polling *ESR?. ESR did not become non-zero.")
        else:
            self._logger.debug(f"Instrument event occurred or ESR became non-zero (ESR: {result}).")
        self._command_log.append({"command": "*ESR? poll", "success": True, "type": "wait_event", "timestamp": time.time(), "final_esr": result})


    def _history(self) -> None:
        """
        Prints history of executed commands.
        """
        print("--- Command History ---")
        for i, entry in enumerate(self._command_log):
            ts_val = entry.get('timestamp', 'N/A')
            ts_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts_val)) if isinstance(ts_val, float) else "Invalid Timestamp"
            print(f"{i+1}. [{ts_str}] Type: {entry.get('type', 'N/A')}, Success: {entry.get('success', 'N/A')}, Command: {entry.get('command', 'N/A')}")
            if 'response' in entry:
                print(f"   Response: {entry['response']}")
        print("--- End of History ---")

    def _error_check(self) -> None:
        """
        Checks for errors on the instrument by querying SYSTem:ERRor?.
        Raises InstrumentCommunicationError if an error is found.
        """
        try:
            error_response = self._backend.query(":SYSTem:ERRor?") # delay=None by default
            # More robust check for "No error"
            if not (error_response.strip().startswith("+0,\"No error\"") or error_response.strip().startswith("0,\"No error\"")):
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    message=f"Instrument returned error: {error_response.strip()}",
                )
        except Exception as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=":SYSTem:ERRor?",
                message=f"Failed to query instrument for errors: {e}",
            ) from e

    def id(self) -> str:
        """
        Query the instrument for its identification string (*IDN?).
        """
        name = self._query("*IDN?")
        self._logger.debug(f"Connected to {name}")
        return name

    def close(self) -> None:
        """Close the connection to the instrument via the backend."""
        try:
            model_name_for_logger = self.config.model if hasattr(self.config, 'model') else self.__class__.__name__
            self._logger.info(f"Instrument '{model_name_for_logger}': Closing connection.")
            self._backend.close() # Changed to use close as per AsyncInstrumentIO
            self._logger.info(f"Instrument '{model_name_for_logger}': Connection closed.")
        except Exception as e:
            self._logger.error(f"Instrument '{model_name_for_logger}': Error during backend close: {e}")
            # Optionally re-raise if failed close is critical:
            # raise InstrumentConnectionError(f"Failed to close backend connection: {e}") from e

    def reset(self) -> None:
        """Reset the instrument to its default settings (*RST)."""
        self._send_command("*RST")
        self._logger.debug("Instrument reset to default settings (*RST).")

    def run_self_test(self, full_test: bool = True) -> str:
        """
        Executes the instrument's internal self-test routine (*TST?) and reports result.
        """
        if not full_test:
             self._logger.debug("Note: `full_test=False` currently ignored, running standard *TST? self-test.")

        self._logger.debug("Running self-test (*TST?)...")
        try:
             result_str = self._query("*TST?")
             code = int(result_str.strip())
        except ValueError:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command="*TST?",
                message=f"Unexpected non-integer response: '{result_str}'",
            )
        except InstrumentCommunicationError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command="*TST?",
                message="Failed to execute query.",
            ) from e

        if code == 0:
            self._logger.debug("Self-test query (*TST?) returned 0 (Passed).")
            errors_after_test = self.get_all_errors()
            if errors_after_test:
                 details = "; ".join([f"{c}: {m}" for c, m in errors_after_test])
                 warn_msg = f"Self-test query passed, but errors found in queue afterwards: {details}"
                 self._logger.debug(warn_msg)
            return "Passed"
        else:
            self._logger.debug(f"Self-test query (*TST?) returned non-zero code: {code} (Failed). Reading error queue...")
            errors = self.get_all_errors()
            details = "; ".join([f"{c}: {m}" for c, m in errors]) if errors else 'No specific errors reported in queue'
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
                if not hasattr(self.config, 'requires') or not callable(self.config.requires):
                    raise InstrumentConfigurationError(
                        self.config.model,
                        "Config object missing 'requires' method for decorator.",
                    )

                if self.config.requires(requirement):
                    return func(self, *args, **kwargs)
                else:
                    raise InstrumentConfigurationError(
                        self.config.model,
                        f"Method '{func.__name__}' requires '{requirement}', which is not available for this instrument model/configuration.",
                    )
            return wrapped_func
        return decorator

    def clear_status(self) -> None:
        """
        Clears the instrument's status registers and error queue (*CLS).
        """
        self._send_command("*CLS", skip_check=True)
        self._logger.debug("Status registers and error queue cleared (*CLS).")

    def get_all_errors(self) -> TypingList[Tuple[int, str]]:
        """
        Reads and clears all errors currently present in the instrument's error queue.
        """
        errors: TypingList[Tuple[int, str]] = []
        max_errors_to_read = 50
        for i in range(max_errors_to_read):
            try:
                code, message = self.get_error()
            except InstrumentCommunicationError as e:
                self._logger.debug(f"Communication error while reading error queue (iteration {i+1}): {e}")
                if errors:
                     self._logger.debug(f"Returning errors read before communication failure: {errors}")
                return errors

            if code == 0:
                break
            errors.append((code, message))
            if code == -350:
                 self._logger.debug("Error queue overflow (-350) detected. Stopping read.")
                 break
        else:
            self._logger.debug(f"Warning: Read {max_errors_to_read} errors without reaching 'No error'. "
                      "Error queue might still contain errors or be in an unexpected state.")

        if not errors:
            self._logger.debug("No errors found in instrument queue.")
        else:
             self._logger.debug(f"Retrieved {len(errors)} error(s) from queue: {errors}")
        return errors

    def get_error(self) -> Tuple[int, str]:
        """
        Reads and clears the oldest error from the instrument's error queue.
        """
        response = (self._query("SYSTem:ERRor?")).strip()
        try:
            code_str, msg_part = response.split(',', 1)
            code = int(code_str)
            message = msg_part.strip().strip('"')
        except (ValueError, IndexError) as e:
            self._logger.debug(f"Warning: Unexpected error response format: '{response}'. Raising error.")
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command="SYSTem:ERRor?",
                message=f"Could not parse error response: '{response}'",
            ) from e

        if code != 0:
             self._logger.debug(f"Instrument Error Query: Code={code}, Message='{message}'")
        return code, message

    def wait_for_operation_complete(self, query_instrument: bool = True, timeout: float = 10.0) -> Optional[str]:
        """
        Waits for the instrument to finish all pending overlapping commands.
        The 'timeout' parameter's effect depends on the backend's query timeout settings.
        """
        if query_instrument:
            # The original logic for setting/restoring instrument.timeout has been removed
            # as the _Backend protocol does not define a timeout attribute.
            # The 'timeout' argument of this method might influence a timeout if the
            # _query method or backend implementation uses it, but _query currently
            # passes 'delay', not 'timeout'. For *OPC?, no delay is typically needed.
            # The backend's own communication timeout will apply to the query.
            self._logger.debug(f"Waiting for operation complete (*OPC?). Effective timeout depends on backend (method timeout hint: {timeout}s).")
            try:
                # The timeout parameter of this method is not directly passed to _query here.
                # _query's delay parameter is for a different purpose.
                response = self._query("*OPC?") # This now uses self._backend.query
                self._logger.debug("Operation complete query (*OPC?) returned.")
                if response.strip() != "1":
                    self._logger.debug(f"Warning: *OPC? returned '{response}' instead of expected '1'.")
                return response.strip()
            except InstrumentCommunicationError as e:
                # The 'timeout' parameter of this method is noted here for context.
                err_msg = f"*OPC? query failed. This may be due to backend communication timeout (related to method's timeout param: {timeout}s)."
                self._logger.debug(err_msg)
                raise InstrumentCommunicationError(
                    instrument=self.config.model, command="*OPC?", message=err_msg
                ) from e
            # 'finally' block for restoring timeout removed.
        else:
            self._send_command("*OPC") # This now uses self._backend.write
            self._logger.debug("Operation complete command (*OPC) sent (non-blocking). Status polling required.")
            return None

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
        response = (self._query("SYSTem:VERSion?")).strip()
        self._logger.debug(f"SCPI Version reported: {response}")
        return response

    @abstractmethod
    def health_check(self) -> HealthReport: # Type hint HealthReport
        """Performs a basic health check of the instrument."""
        # Base implementation could try IDN and error queue check
        # report = HealthReport() # Initialize HealthReport
        # try:
        #     report.instrument_idn = self.id() # Direct synchronous call
        #     instrument_errors = self.get_all_errors() # Direct synchronous call
        #     if instrument_errors:
        #         report.warnings.extend([f"Stored Error: {code} - {msg}" for code, msg in instrument_errors])
        #
        #     if not report.errors and not report.warnings:
        #          report.status = HealthStatus.OK
        #     elif report.warnings and not report.errors:
        #          report.status = HealthStatus.WARNING
        #     else: # if errors are present
        #          report.status = HealthStatus.ERROR
        #
        # except Exception as e:
        #     report.status = HealthStatus.ERROR
        #     report.errors.append(f"Health check failed during IDN/Error Query: {str(e)}")
        # return report
        pass # Replace with actual base implementation
