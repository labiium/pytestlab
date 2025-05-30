from __future__ import annotations
from .._log import get_logger

import os # Added import
from typing import Optional, Tuple, Any, Callable, Type, List as TypingList, Dict, Union
import numpy as np
# polars.List is a DataType, not for type hinting Python lists.
# from polars import List
from ..errors import InstrumentConnectionBusy, InstrumentConfigurationError, InstrumentNotFoundError, InstrumentCommunicationError, InstrumentConnectionError, InstrumentParameterError
from ..config import InstrumentConfig
from pyscpi import usbtmc # This import might not be used if backend is always "lamb"
from .backends.lamb import LambInstrument
from ..sim.backend import SimBackend # Added import
import time

# backend = "lamb" # This global variable might be superseded or used as a fallback

class Instrument:
    """
    A class representing an SCPI-compliant instrument.

    Attributes:
        config (InstrumentConfig): The configuration object for the instrument.
        instrument (Any): The backend instrument object (e.g., LambInstrument or SimBackend).
        debug_mode (bool): Flag to enable/disable debug logging.
    """

    def __init__(self, config: InstrumentConfig, debug_mode: bool = False, simulate: bool = False) -> None:
        """
        Initialize the Instrument class.

        Args:
            config (InstrumentConfig): Configuration for the instrument.
            debug_mode (bool): Enable debug mode.
            simulate (bool): Enable simulation mode.
        """
        # Ensure config is not None and is of the correct type.
        # The type hint InstrumentConfig (not Optional) now enforces config is provided.
        if not isinstance(config, InstrumentConfig): # type: ignore[unreachable]
            # This check might seem redundant with type hinting but can catch runtime issues
            # if type hints are ignored or if config is manipulated unexpectedly.
            # The type ignore is for linters that might see InstrumentConfig as a Pydantic model
            # which might not directly inherit from a base InstrumentConfig if it's a Protocol.
            raise InstrumentConfigurationError("A valid InstrumentConfig object must be provided.")
        
        self.config: InstrumentConfig = config
        self.instrument: Any
        self._command_log: TypingList[Dict[str, Any]] = []
        self.debug_mode: bool = debug_mode
        self._logger = get_logger(self.config.model if hasattr(self.config, 'model') else self.__class__.__name__)

        # Determine if simulation is requested
        simulate_env = os.getenv("PYTESTLAB_SIMULATE") == "1"
        should_simulate = simulate_env or simulate

        if should_simulate:
            self._logger.info(f"Simulation mode enabled for {config.model if hasattr(config, 'model') else 'instrument'}.")
            device_model_name = config.model if hasattr(config, 'model') else self.__class__.__name__
            self.instrument = SimBackend(profile=config, device_model=device_model_name)
            # SimBackend might not need/have clear_status, or it's a no-op.
            # If it does, it can be called here or handled within SimBackend's __init__.
            if hasattr(self.instrument, 'clear_status') and callable(self.instrument.clear_status):
                try:
                    self.instrument.clear_status() # type: ignore
                    self._logger.debug("Called clear_status on SimBackend.")
                except Exception as e_sim_clear:
                    self._logger.warning(f"Error calling clear_status on SimBackend: {e_sim_clear}")
            else:
                self._logger.debug("SimBackend does not have clear_status, or it's not callable.")

        else:
            self._logger.info(f"Real instrument mode for {config.model if hasattr(config, 'model') else 'instrument'}.")
            # Existing backend selection logic (e.g., using a global 'backend' variable or config-driven)
            # For this example, we'll assume the 'lamb' backend as per the original file structure.
            # This section would need to be more robust if multiple real backends are supported.
            current_backend_type = "lamb" # This could be determined from config or a global setting
            
            if current_backend_type == "lamb":
                if not hasattr(config, 'model') or not hasattr(config, 'serial_number'):
                    raise InstrumentConfigurationError("Lamb backend requires model and serial_number in config for real instrument mode.")
                self.instrument = LambInstrument(config.model, config.serial_number)
            # Example for other backends:
            # elif current_backend_type == "usbtmc":
            #     if not hasattr(config, 'vendor_id') or not hasattr(config, 'product_id'):
            #         raise InstrumentConfigurationError("USBTMC backend requires vendor_id and product_id in config.")
            #     self.instrument = usbtmc.Instrument(config.vendor_id, config.product_id)
            else:
                raise InstrumentConfigurationError(f"Invalid backend specified for real instrument: {current_backend_type}")
            
            # Initial clear_status for real instruments
            try:
                self.clear_status()
            except InstrumentCommunicationError as e:
                if hasattr(self.instrument, 'close') and callable(self.instrument.close):
                    try:
                        self.instrument.close()
                    except Exception as close_e:
                        self._logger.debug(f"Error closing instrument during failed init (after clear_status failure): {close_e}")
                raise InstrumentConnectionError("Failed to connect to the real instrument during initial status clear.") from e

    @classmethod
    def from_config(cls: Type[Instrument], config: InstrumentConfig, debug_mode: bool = False) -> Instrument:
        if not isinstance(config, InstrumentConfig):
             raise InstrumentConfigurationError("from_config expects an InstrumentConfig object.")
        return cls(config=config, debug_mode=debug_mode)

    def _read_to_np(self, data: bytes) -> np.ndarray:
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

    def _send_command(self, command: str, skip_check: bool = False) -> None:
        """
        Send an SCPI command to the instrument.
        """
        try:
            self.instrument.write(command)
            if not skip_check:
                self._error_check()
            self._command_log.append({"command": command, "success": True, "type": "write", "timestamp": time.time()})
        except Exception as e:
            self._command_log.append({"command": command, "success": False, "type": "write", "timestamp": time.time()})
            raise InstrumentCommunicationError(f"Failed to send command `{str(command)}`\n{str(e)}") from e

    def _query(self, query: str) -> str:
        """
        Query the instrument and return the response.
        """
        try:
            response: str = self.instrument.query(query)
            self._error_check()
            self._command_log.append({"command": query, "success": True, "type": "query", "timestamp": time.time(), "response": response})
            # self.instrument.query("*OPC?") # OPC? after every query might be too slow/redundant
            return response.strip()
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query", "timestamp": time.time()})
            raise InstrumentCommunicationError(f"Failed to query instrument with '{query}': {str(e)}") from e
        
    def _query_raw(self, query: str) -> bytes:
        """
        Query the instrument and return the raw response.
        """
        try:
            response: bytes
            if backend == "lamb":
                response = self.instrument.query_raw(query)
            # elif backend == "usbtmc":
            #     response = self.instrument.ask_raw(query.encode("utf-8")) # Ensure query is bytes
            else:
                raise InstrumentConfigurationError(f"Unsupported backend for _query_raw: {backend}")
            return response
        except Exception as e:
            raise InstrumentCommunicationError(f"Failed to raw query instrument with '{query}': {str(e)}") from e

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
            self.instrument.query("*OPC?")
            self._logger.debug("Waiting for instrument to finish processing commands (*OPC? successful).")
            self._command_log.append({"command": "*OPC?", "success": True, "type": "wait", "timestamp": time.time()})
        except Exception as e:
            self._logger.debug(f"Error during *OPC? wait: {e}")
            raise InstrumentCommunicationError("Failed to wait for operation complete (*OPC?).") from e

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
                esr_response = self.instrument.query("*ESR?")
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

    def _error_check(self) -> None:
        """
        Checks for errors on the instrument by querying SYSTem:ERRor?.
        Raises InstrumentCommunicationError if an error is found.
        """
        try:
            error_response = self.instrument.query(":SYSTem:ERRor?")
            # More robust check for "No error"
            if not (error_response.strip().startswith("+0,\"No error\"") or error_response.strip().startswith("0,\"No error\"")):
                raise InstrumentCommunicationError(f"Instrument returned error: {error_response.strip()}")
        except Exception as e:
            raise InstrumentCommunicationError(f"Failed to query instrument for errors: {str(e)}") from e

    def id(self) -> str:
        """
        Query the instrument for its identification string (*IDN?).
        """
        name = self._query("*IDN?")
        self._logger.debug(f"Connected to {name}")
        return name
    
    def close(self) -> None:
        """Close the connection to the instrument."""
        if hasattr(self.instrument, 'close') and callable(self.instrument.close):
            self.instrument.close()
            self._logger.debug("Instrument connection closed.")
        else:
            self._logger.debug("Instrument object does not have a close method or it's not callable.")

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
            raise InstrumentCommunicationError(f"Unexpected non-integer response from *TST?: '{result_str}'")
        except InstrumentCommunicationError as e:
             raise InstrumentCommunicationError("Failed to execute *TST? query.", cause=e) from e

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
                    raise InstrumentConfigurationError("Config object missing 'requires' method for decorator.")
                
                if self.config.requires(requirement):
                    return func(self, *args, **kwargs)
                else:
                    raise InstrumentConfigurationError(f"Method '{func.__name__}' requires '{requirement}'. This functionality is not available for this instrument model/configuration.")
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
        response = self._query("SYSTem:ERRor?").strip() 
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

    def wait_for_operation_complete(self, query_instrument: bool = True, timeout: float = 10.0) -> Optional[str]:
        """
        Waits for the instrument to finish all pending overlapping commands.
        """
        if query_instrument:
            original_timeout: Optional[Union[int, float]] = None 
            instrument_obj: Any = self.instrument
            
            if hasattr(instrument_obj, 'timeout'):
                 try:
                      original_timeout = instrument_obj.timeout 
                      instrument_obj.timeout = timeout 
                      self._logger.debug(f"Set instrument timeout to {timeout}s for *OPC? query.")
                 except Exception as te:
                      self._logger.debug(f"Warning: Could not set instrument timeout for OPC?: {te}")
            
            try:
                response = self._query("*OPC?") 
                self._logger.debug("Operation complete query (*OPC?) returned.")
                if response.strip() != "1":
                    self._logger.debug(f"Warning: *OPC? returned '{response}' instead of expected '1'.")
                return response.strip()
            except InstrumentCommunicationError as e: 
                err_msg = f"*OPC? query failed or timed out (current timeout: {timeout}s)."
                self._logger.debug(err_msg)
                raise InstrumentCommunicationError(err_msg, cause=e) from e
            finally:
                 if original_timeout is not None and hasattr(instrument_obj, 'timeout'):
                     try:
                          instrument_obj.timeout = original_timeout
                          self._logger.debug(f"Restored instrument timeout to {original_timeout}.")
                     except Exception as te:
                          self._logger.debug(f"Warning: Could not restore instrument timeout after OPC?: {te}")
        else:
            self._send_command("*OPC") 
            self._logger.debug("Operation complete command (*OPC) sent (non-blocking). Status polling required.")
            return None
        

    def get_scpi_version(self) -> str:
        """
        Queries the version of the SCPI standard the instrument complies with.
        """
        response = self._query("SYSTem:VERSion?").strip()
        self._logger.debug(f"SCPI Version reported: {response}")
        return response
