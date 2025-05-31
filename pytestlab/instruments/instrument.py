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
import time

# Forward reference for ConfigType if InstrumentConfig is not fully defined/imported yet,
# or if it's defined in a way that causes circular dependencies.
# For this refactor, we assume InstrumentConfig is available.
ConfigType = TypeVar('ConfigType', bound='InstrumentConfig')

class InstrumentIO(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def write(self, cmd: str) -> None: ...
    def query(self, cmd: str, delay: Optional[float] = None) -> str: ...
    def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes: ...
    def close(self) -> None: ... # Often same as disconnect

    # New timeout methods
    def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout in milliseconds."""
        ...
    def get_timeout(self) -> int:
        """Gets the communication timeout in milliseconds."""
        ...

class AsyncInstrumentIO(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def write(self, cmd: str) -> None: ...
    async def query(self, cmd: str, delay: Optional[float] = None) -> str: ...
    async def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes: ... # Add async query_raw
    async def close(self) -> None: ... # Add async close

    # New async timeout methods
    async def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout in milliseconds."""
        ...
    async def get_timeout(self) -> int:
        """Gets the communication timeout in milliseconds."""
        ...

class Instrument(Generic[ConfigType]):
    """
    A class representing an SCPI-compliant instrument.

    Attributes:
        config (InstrumentConfig): The configuration object for the instrument.
        instrument (Any): The backend instrument object (e.g., LambInstrument or SimBackend).
        debug_mode (bool): Flag to enable/disable debug logging.
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
                 "A valid InstrumentConfig-compatible object must be provided. "
                 f"Got {type(config).__name__}."
             )

        self.config = config
        self._backend = backend # This will be an AsyncInstrumentIO instance
        self._command_log = []
        
        logger_name = self.config.model if hasattr(self.config, 'model') else self.__class__.__name__
        self._logger = get_logger(logger_name)
        
        self._logger.info(f"Instrument '{logger_name}': Initializing with backend '{type(backend).__name__}'.")
        # Connection will be handled asynchronously, typically by an explicit connect method or within an async context manager.
        # For now, we remove the synchronous connect from __init__.
        # The user of the Instrument class will be responsible for calling an `async def connect()` method if needed.

    # Note: from_config might need to become async or handle async backend instantiation.
    # This will be addressed when AutoInstrument is updated.
    @classmethod
    def from_config(cls: Type[Instrument], config: InstrumentConfig, debug_mode: bool = False) -> Instrument:
        # This method will likely need significant changes to support async backends.
        # For now, it's a placeholder and might not work correctly with async backends.
        # It should ideally accept an async_mode flag or similar to determine backend type.
        if not isinstance(config, InstrumentConfig):
             raise InstrumentConfigurationError("from_config expects an InstrumentConfig object.")
        # The backend instantiation is missing here and is crucial.
        # This will be handled by AutoInstrument.from_config later.
        raise NotImplementedError("from_config needs to be updated for async backend instantiation.")


    async def connect_backend(self) -> None:
        """Connects the backend. To be called after Instrument instantiation."""
        logger_name = self.config.model if hasattr(self.config, 'model') else self.__class__.__name__
        try:
            await self._backend.connect()
            self._logger.info(f"Instrument '{logger_name}': Backend connected.")
        except Exception as e:
            self._logger.error(f"Instrument '{logger_name}': Failed to connect backend: {e}")
            if hasattr(self._backend, 'disconnect'): # Check if disconnect is available (it should be for AsyncInstrumentIO)
                try:
                    await self._backend.disconnect()
                except Exception as disc_e:
                    self._logger.error(f"Instrument '{logger_name}': Error disconnecting backend during failed connect: {disc_e}")
            raise InstrumentConnectionError(f"Failed to connect backend for {logger_name}: {e}") from e

    async def _read_to_np(self, data: bytes) -> np.ndarray:
        """
        Parses SCPI binary block data into a NumPy array.
        Assumes data format like #<N><LengthBytes><DataBytes>[\n]
        and that the data itself is uint8 as per typical :WAVeform:FORMat BYTE.
        """
        if not data.startswith(b'#'):
            self._logger.debug(f"Warning: Data for _read_to_np does not start with '#'. Attempting direct conversion of data[10:-1] if applicable. Raw data (first 20 bytes): {data[:20]}")
            if len(data) > 10:
                # Fallback for non-standard data, trying to mimic original slicing logic
                # This is risky and might need instrument-specific handling if '#' is truly absent.
                end_slice = -1 if data.endswith(b'\n') else None
                return np.frombuffer(data[10:end_slice], dtype=np.uint8)
            return np.array([], dtype=np.uint8)

        try:
            len_digits_char = data[1:2].decode('ascii')
            if not len_digits_char.isdigit():
                raise ValueError(f"Invalid SCPI binary block: Length digit char '{len_digits_char}' is not a digit.")
            
            num_digits_for_length = int(len_digits_char)
            if num_digits_for_length == 0:
                raise ValueError("Indefinite length SCPI binary block (#0) not supported for waveform data.")

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
            raise InstrumentCommunicationError("Failed to parse binary data from instrument.") from e

    async def _send_command(self, command: str, skip_check: bool = False) -> None:
        """
        Send an SCPI command to the instrument.
        """
        try:
            await self._backend.write(command)
            if not skip_check:
                await self._error_check()
            self._command_log.append({"command": command, "success": True, "type": "write", "timestamp": time.time()})
        except Exception as e:
            self._command_log.append({"command": command, "success": False, "type": "write", "timestamp": time.time()})
            raise InstrumentCommunicationError(f"Failed to send command `{str(command)}`\n{str(e)}") from e

    async def _query(self, query: str, delay: Optional[float] = None) -> str:
        """
        Query the instrument and return the response.
        """
        try:
            # self._logger.debug(f"QUERY: {query}" + (f" with delay: {delay}" if delay is not None else ""))
            response: str = await self._backend.query(query, delay=delay)
            # self._logger.debug(f"RESPONSE: {response}")
            await self._error_check() # Keep error check as it's a SYST:ERR? query
            self._command_log.append({"command": query, "success": True, "type": "query", "timestamp": time.time(), "response": response, "delay": delay})
            return response.strip()
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query", "timestamp": time.time(), "delay": delay})
            raise InstrumentCommunicationError(f"Failed to query instrument with '{query}': {str(e)}") from e
        
    async def _query_raw(self, query: str, delay: Optional[float] = None) -> bytes:
        """
        Query the instrument and return the raw response.
        """
        try:
            # self._logger.debug(f"QUERY_RAW: {query}" + (f" with delay: {delay}" if delay is not None else ""))
            response: bytes = await self._backend.query_raw(query, delay=delay)
            # self._logger.debug(f"RESPONSE (bytes): {len(response)} bytes")
            # Raw queries typically don't run _error_check() as the response might not be string-parsable for errors.
            self._command_log.append({"command": query, "success": True, "type": "query_raw", "timestamp": time.time(), "response_len": len(response), "delay": delay})
            return response
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query_raw", "timestamp": time.time(), "delay": delay})
            raise InstrumentCommunicationError(f"Failed to raw query instrument with '{query}': {str(e)}") from e

    async def lock_panel(self, lock: bool = True) -> None:
        """
        Locks or unlocks the front panel of the instrument.
        """
        if lock:
            await self._send_command(":SYSTem:LOCK")
        else:
            await self._send_command(":SYSTem:LOCal")
        self._logger.debug(f"Panel {'locked' if lock else 'unlocked (local control enabled)'}.")

    async def _wait(self) -> None:
        """
        Blocks until all previous commands have been processed by the instrument using *OPC?.
        """
        try:
            await self._backend.query("*OPC?") # delay=None by default for _backend.query
            self._logger.debug("Waiting for instrument to finish processing commands (*OPC? successful).")
            self._command_log.append({"command": "*OPC?", "success": True, "type": "wait", "timestamp": time.time()})
        except Exception as e:
            self._logger.debug(f"Error during *OPC? wait: {e}")
            raise InstrumentCommunicationError("Failed to wait for operation complete (*OPC?).") from e

    async def _wait_event(self) -> None:
        """
        Blocks by polling the Standard Event Status Register (*ESR?) until a non-zero value.
        This is a basic implementation; specific event setup (*ESE) might be needed.
        """
        result = 0
        max_attempts = 100 
        attempts = 0
        while result == 0 and attempts < max_attempts:
            try:
                esr_response = await self._backend.query("*ESR?") # Use self._backend
                result = int(esr_response.strip())
            except Exception as e:
                self._logger.debug(f"Error querying *ESR? during _wait_event: {e}")
                raise InstrumentCommunicationError("Failed to query *ESR? during wait.") from e
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

    async def _error_check(self) -> None:
        """
        Checks for errors on the instrument by querying SYSTem:ERRor?.
        Raises InstrumentCommunicationError if an error is found.
        """
        try:
            error_response = await self._backend.query(":SYSTem:ERRor?") # delay=None by default
            # More robust check for "No error"
            if not (error_response.strip().startswith("+0,\"No error\"") or error_response.strip().startswith("0,\"No error\"")):
                raise InstrumentCommunicationError(f"Instrument returned error: {error_response.strip()}")
        except Exception as e:
            raise InstrumentCommunicationError(f"Failed to query instrument for errors: {str(e)}") from e

    async def id(self) -> str:
        """
        Query the instrument for its identification string (*IDN?).
        """
        name = await self._query("*IDN?")
        self._logger.debug(f"Connected to {name}")
        return name
    
    async def close(self) -> None:
        """Close the connection to the instrument via the backend."""
        try:
            model_name_for_logger = self.config.model if hasattr(self.config, 'model') else self.__class__.__name__
            self._logger.info(f"Instrument '{model_name_for_logger}': Closing connection.")
            await self._backend.close() # Changed to use close as per AsyncInstrumentIO
            self._logger.info(f"Instrument '{model_name_for_logger}': Connection closed.")
        except Exception as e:
            self._logger.error(f"Instrument '{model_name_for_logger}': Error during backend close: {e}")
            # Optionally re-raise if failed close is critical:
            # raise InstrumentConnectionError(f"Failed to close backend connection: {e}") from e

    async def reset(self) -> None:
        """Reset the instrument to its default settings (*RST)."""
        await self._send_command("*RST")
        self._logger.debug("Instrument reset to default settings (*RST).")

    async def run_self_test(self, full_test: bool = True) -> str:
        """
        Executes the instrument's internal self-test routine (*TST?) and reports result.
        """
        if not full_test:
             self._logger.debug("Note: `full_test=False` currently ignored, running standard *TST? self-test.")

        self._logger.debug("Running self-test (*TST?)...")
        try:
             result_str = await self._query("*TST?")
             code = int(result_str.strip())
        except ValueError:
            raise InstrumentCommunicationError(f"Unexpected non-integer response from *TST?: '{result_str}'")
        except InstrumentCommunicationError as e:
             raise InstrumentCommunicationError("Failed to execute *TST? query.", cause=e) from e

        if code == 0:
            self._logger.debug("Self-test query (*TST?) returned 0 (Passed).")
            errors_after_test = await self.get_all_errors()
            if errors_after_test:
                 details = "; ".join([f"{c}: {m}" for c, m in errors_after_test])
                 warn_msg = f"Self-test query passed, but errors found in queue afterwards: {details}"
                 self._logger.debug(warn_msg)
            return "Passed"
        else:
            self._logger.debug(f"Self-test query (*TST?) returned non-zero code: {code} (Failed). Reading error queue...")
            errors = await self.get_all_errors()
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
                    raise InstrumentConfigurationError("Config object missing 'requires' method for decorator.")
                
                if self.config.requires(requirement):
                    return func(self, *args, **kwargs)
                else:
                    raise InstrumentConfigurationError(f"Method '{func.__name__}' requires '{requirement}'. This functionality is not available for this instrument model/configuration.")
            return wrapped_func
        return decorator

    async def clear_status(self) -> None:
        """
        Clears the instrument's status registers and error queue (*CLS).
        """
        await self._send_command("*CLS", skip_check=True)
        self._logger.debug("Status registers and error queue cleared (*CLS).")

    async def get_all_errors(self) -> TypingList[Tuple[int, str]]:
        """
        Reads and clears all errors currently present in the instrument's error queue.
        """
        errors: TypingList[Tuple[int, str]] = []
        max_errors_to_read = 50
        for i in range(max_errors_to_read):
            try:
                code, message = await self.get_error()
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
    
    async def get_error(self) -> Tuple[int, str]:
        """
        Reads and clears the oldest error from the instrument's error queue.
        """
        response = (await self._query("SYSTem:ERRor?")).strip()
        try:
            code_str, msg_part = response.split(',', 1)
            code = int(code_str)
            message = msg_part.strip().strip('"')
        except (ValueError, IndexError) as e:
            self._logger.debug(f"Warning: Unexpected error response format: '{response}'. Raising error.")
            raise InstrumentCommunicationError(f"Could not parse error response: '{response}'", cause=e) from e

        if code != 0:
             self._logger.debug(f"Instrument Error Query: Code={code}, Message='{message}'")
        return code, message

    async def wait_for_operation_complete(self, query_instrument: bool = True, timeout: float = 10.0) -> Optional[str]:
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
                response = await self._query("*OPC?") # This now uses self._backend.query
                self._logger.debug("Operation complete query (*OPC?) returned.")
                if response.strip() != "1":
                    self._logger.debug(f"Warning: *OPC? returned '{response}' instead of expected '1'.")
                return response.strip()
            except InstrumentCommunicationError as e:
                # The 'timeout' parameter of this method is noted here for context.
                err_msg = f"*OPC? query failed. This may be due to backend communication timeout (related to method's timeout param: {timeout}s)."
                self._logger.debug(err_msg)
                raise InstrumentCommunicationError(err_msg, cause=e) from e
            # 'finally' block for restoring timeout removed.
        else:
            await self._send_command("*OPC") # This now uses self._backend.write
            self._logger.debug("Operation complete command (*OPC) sent (non-blocking). Status polling required.")
            return None
        
    async def set_communication_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout on the backend."""
        await self._backend.set_timeout(timeout_ms)
        self._logger.debug(f"Communication timeout set to {timeout_ms} ms on backend.")

    async def get_communication_timeout(self) -> int:
        """Gets the communication timeout from the backend."""
        timeout = await self._backend.get_timeout()
        self._logger.debug(f"Communication timeout retrieved from backend: {timeout} ms.")
        return timeout

    async def get_scpi_version(self) -> str:
        """
        Queries the version of the SCPI standard the instrument complies with.
        """
        response = (await self._query("SYSTem:VERSion?")).strip()
        self._logger.debug(f"SCPI Version reported: {response}")
        return response

    @abstractmethod
    async def health_check(self) -> HealthReport: # Type hint HealthReport
        """Performs a basic health check of the instrument."""
        # Base implementation could try IDN and error queue check
        # report = HealthReport() # Initialize HealthReport
        # try:
        #     report.instrument_idn = await self.id() # Ensure await for async calls
        #     instrument_errors = await self.get_all_errors() # Ensure await for async calls
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
