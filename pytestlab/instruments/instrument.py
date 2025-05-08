from typing import Optional, Tuple
import numpy as np
from polars import List
from ..errors import InstrumentConnectionBusy, InstrumentConfigurationError, InstrumentNotFoundError, InstrumentCommunicationError, InstrumentConnectionError, InstrumentParameterError
from ..config import InstrumentConfig
from pyscpi import usbtmc
from .backends.lamb import LambInstrument
import time

backend = "lamb"

class Instrument:
    """
    A class representing an SCPI-compliant instrument.

    Attributes:
        visa_resource (str): The VISA resource string that identifies the instrument.
    """

    def __init__(self, config=None, debug_mode=False):
        """
        Initialize the SCPIInstrument class.

        Args:
            visa_resource (str): The VISA resource string to use for the connection.
        """
        if isinstance(config, InstrumentConfig):
            match backend:
                # Can implement more non lamb backends here
                # case "usbtmc":
                #     self.instrument = usbtmc.Instrument(config.vendor_id, config.product_id)
                case "lamb":
                    self.instrument = LambInstrument(config.model, config.serial_number)
                case _:
                    raise InstrumentConfigurationError("Invalid backend")
        else:
            raise InstrumentConfigurationError("Either a VISA resource string or a vendor and product ID must be provided.")
        self.config = config
        self._command_log = []
        self.debug_mode = debug_mode
        try:
            self.clear_status()
        except InstrumentCommunicationError:
            raise InstrumentConnectionError("Failed to connect to the instrument.")

    @classmethod
    def from_config(cls, config: InstrumentConfig, debug_mode=False):
        return cls(config=InstrumentConfig(**config), debug_mode=debug_mode)

    def _read_to_np(self, data) -> bytes:
        chunk_size = 1024
        np.frombuffer(data[10:], dtype=np.uint8)
        header = data[2:10].decode('utf-8')
        data = np.frombuffer(data[10:], dtype=np.uint8)
        # self._log(header)

        # hpoints = int(header)

        # while len(data) < hpoints:
        #     data = np.append(data, np.frombuffer(
        #         self.instrument.read_raw(chunk_size), dtype=np.uint8))

        return data[:-1]

    def _send_command(self, command, skip_check=False):
        """
        Send an SCPI command to the instrument.

        Args:
            command (str): The SCPI command to send.

        Raises:
            SCPICommunicationError: If sending the command fails.
        """
        try:
            self.instrument.write(command)
            if not skip_check:
                self._error_check()
            self._command_log.append({"command": command, "success": True, "type": "write", "timestamp":time.time})
        except Exception as e:
            raise InstrumentCommunicationError(f"Failed to send command `{str(command)}`\n{str(e)}")

    def _query(self, query):
        """
        Query the instrument and return the response.

        Args:
            query (str): The SCPI query to send.

        Returns:
            str: The instrument's response to the query.

        Raises:
            SCPICommunicationError: If the query fails.
        """
        try:
            response =  self.instrument.query(query)
            self._error_check()
            # self.lo
            # print(response)
            self._command_log.append({"command": query, "success": True, "type": "query", "timestamp":time.time, "response": response})
            self.instrument.query("*OPC?")
            return response
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query", "timestamp":time.time})
            raise InstrumentCommunicationError(f"Failed to query instrument: {str(e)}")
        
    def _query_raw(self, query):
        """
        Query the instrument and return the raw response.

        Args:
            query (str): The SCPI query to send.

        Returns:
            bytes: The raw instrument response to the query.

        Raises:
            SCPICommunicationError: If the query fails.
        """
        try:
            match backend:
                # case "usbtmc":
                #     response = self.instrument.ask_raw(query.encode("utf-8"))
                case "lamb":
                    response = self.instrument.query_raw(query)
                case _:
                    pass
            # self._error_check()
            return response
        except Exception as e:
            raise InstrumentCommunicationError(f"Failed to query instrument: {str(e)}")

    def lock_panel(self, lock=True):
        """
        Locks the panel of the instrument

        Args:
            lock (bool): True to lock the panel, False to unlock it
        """
        if lock:
            self._send_command(":SYSTem:LOCK")
        else:
            self._send_command(":SYSTem:LOCal")

    def _wait(self):
        """
        Blocks until all previous commands have been processed by the instrument.
        """
        self.instrument.query("*OPC?")
        self._log("Waiting for instrument to finish processing commands.")
        self._command_log.append({"command": "BLOCK", "success": True, "type": "wait", "timestamp":time.time})

    def _wait_event(self):
        """
        Blocks until all previous commands have been processed by the instrument.
        """
        result = 0
        while (result == 0):
            result =  int(self.instrument.query("*ESR?"))
        self._log("Waiting for instrument to finish processing commands.")
        self._command_log.append({"command": "BLOCK", "success": True, "type": "wait", "timestamp":time.time})

    def _log(self, message):
        """
        Log a message.

        Args:
            message (str): The message to log.
        """
        if self.debug_mode:
            print(message)

    def _history(self):
        """
        Prints history of executed commands
        """
        for command in self._command_log:
            print(command)

    def _error_check(self):
        """
        Checks for errors on the instrument
        """
        error = self.instrument.query(":SYSTem:ERRor?")
        if error.strip() != "+0,\"No error\"":
            raise InstrumentCommunicationError(f"Instrument returned error: {error}")


    def id(self):
        """
        Query the instrument for its identification.

        Returns:
            str: The identification string of the instrument.
        """

        name = self._query("*IDN?")
        self._log(f"Connected to {name}")
        self._command_log.append({"command": "*IDN?", "success": True, "type": "query", "timestamp":time.time, "response": name})
        return name
    
    def close(self):
        """Close the connection to the instrument."""
        self.instrument.close()

    def reset(self):
        """Reset the instrument to its default settings."""
        self._send_command("*RST")
        self._log("Resetting instrument to default settings.")
        self._command_log.append({"command": "RESET", "success": True, "type": "reset", "timestamp":time.time})

    def run_self_test(self, full_test: bool = True) -> str:
        """
        Executes the instrument's internal self-test routine (*TST?) and reports result.

        Args:
            full_test (bool): Parameter included for potential future expansion or
                              if different test levels exist. Currently ignored,
                              performs the standard *TST?. Defaults to True.

        Returns:
            - "Passed" if the self-test query (`*TST?`) returns 0.
            - "Failed: Code <code>. Errors: <details>" if the self-test query returns
              a non-zero code. `<details>` will include any specific error messages
              retrieved from the instrument's error queue after the failure.

        Raises:
            InstrumentCommunicationError: If the *TST? query itself fails or returns
                                          an unparseable response.
        """
        if not full_test:
             self._log("Note: `full_test=False` currently ignored, running standard *TST? self-test.", level="info")

        self._log("Running self-test (*TST?)...")
        # SCPI: *TST? (Manual p.69) - Returns 0 for pass, non-zero for fail
        try:
             result_str = self._query("*TST?")
             code = int(result_str.strip())
        except ValueError:
            raise InstrumentCommunicationError(f"Unexpected non-integer response from *TST?: '{result_str}'")
        except InstrumentCommunicationError as e:
             # Re-raise communication errors during the query itself
             raise InstrumentCommunicationError("Failed to execute *TST? query.", cause=e) from e

        if code == 0:
            self._log("Self-test query (*TST?) returned 0 (Passed).")
            # Check for any latent errors potentially generated *during* the test execution
            # even if the final result code is 0.
            errors_after_test = self.get_all_errors()
            if errors_after_test:
                 details = "; ".join([f"{c}: {m}" for c, m in errors_after_test])
                 warn_msg = f"Self-test query passed, but errors found in queue afterwards: {details}"
                 self._log(warn_msg, level="warning")
                 # Optionally, change return status based on post-test errors
                 # return f"Passed (with subsequent errors: {details})"
            return "Passed"
        else:
            # If TST? reports failure (non-zero code), read error queue for details
            self._log(f"Self-test query (*TST?) returned non-zero code: {code} (Failed). Reading error queue...", level="error")
            errors = self.get_all_errors()
            details = "; ".join([f"{c}: {m}" for c, m in errors]) if errors else 'No specific errors reported in queue'
            fail_msg = f"Failed: Code {code}. Errors: {details}"
            self._log(fail_msg, level="error")
            return fail_msg
    

    
    @classmethod
    def requires(cls, requirement: str):
        """
        Decorator that can be used to specify requirements for a method.
        
        Args:
            requirement (str): The requirement that must be met for the method to be executed.
        """
        def decorator(func):
            def wrapped_func(self, *args, **kwargs):
                if self.config.requires(requirement):
                    return func(self, *args, **kwargs)
                else:
                    raise InstrumentConfigurationError(f"Method '{func.__name__}' requires '{requirement}'. This functionality is not available for this instrument.")
            return wrapped_func
        return decorator

    def clear_status(self):
        """
        Clears the instrument's status registers and error queue (*CLS).

        This clears the Status Byte register, the Standard Event register, and any
        other SCPI-defined event registers. It also clears the instrument's error queue.
        It does *not* clear enable registers (like *ESE, *SRE masks).

        Raises:
            InstrumentCommunicationError: If the SCPI command fails.
        """
        # SCPI: *CLS (Manual p.64)
        self._send_command("*CLS")
        self._log("Status registers and error queue cleared (*CLS).")
        # No error check needed after *CLS itself, as its purpose is to clear errors.

    def get_all_errors(self) -> list[tuple[int, str]]:
        """
        Reads and clears all errors currently present in the instrument's error queue.

        Continuously queries `SYSTem:ERRor?` until the "No error" (code 0)
        response is received or a maximum number of reads is reached.

        Returns:
            A list of (error_code, error_message) tuples for all errors found.
            Returns an empty list if no errors were present in the queue.
        """
        errors: List[Tuple[int, str]] = []
        # Limit reads to prevent potential infinite loops in unexpected scenarios
        # SCPI error queue depth is often limited (e.g., 20-50 entries).
        max_errors_to_read = 50
        for i in range(max_errors_to_read):
            try:
                code, message = self.get_error()
            except InstrumentCommunicationError as e:
                self._log(f"Communication error while reading error queue (iteration {i+1}): {e}", level="error")
                # Include any errors read so far
                if errors:
                     self._log(f"Returning errors read before communication failure: {errors}", level="warning")
                return errors # Return what we have

            if code == 0:
                # Successfully read "No error", queue is clear.
                break
            errors.append((code, message))
            # Check for queue overflow error (-350) explicitly
            if code == -350:
                 self._log("Error queue overflow (-350) detected. Stopping read.", level="warning")
                 break
        else:
            # Loop finished without encountering "No error" code 0
            self._log(f"Warning: Read {max_errors_to_read} errors without reaching 'No error'. "
                      "Error queue might still contain errors or be in an unexpected state.", level="warning")

        if not errors:
            self._log("No errors found in instrument queue.", level="info")
        else:
             self._log(f"Retrieved {len(errors)} error(s) from queue.", level="warning" if errors else "info")
        return errors
    
    def get_error(self) -> Tuple[int, str]:
        """
        Reads and clears the oldest error from the instrument's error queue.

        Follows the SCPI standard `SYSTem:ERRor?` query format.

        Returns:
            A tuple containing:
            - error_code (int): The numeric error code. 0 indicates "No error".
                                Negative codes are standard SCPI errors. Positive
                                codes are often device-specific.
            - error_message (str): The descriptive error message string.
                                   "No error" if the queue was empty.

        Raises:
            InstrumentCommunicationError: If the SCPI query fails or the response
                                          format is unexpected.
        """
        # SCPI: SYST:ERR? (Manual p.230)
        response = self._query("SYSTem:ERRor?").strip()
        try:
            # SCPI format: <error code>,<error string> (string usually quoted)
            # Example: -113,"Undefined header" or +0,"No error"
            code_str, msg_part = response.split(',', 1)
            code = int(code_str)
            # Remove potential surrounding quotes from the message part
            message = msg_part.strip().strip('"')
        except (ValueError, IndexError) as e:
            # Handle cases where response is not in "code,message" format
            self._log(f"Warning: Unexpected error response format: '{response}'. Raising error.", level="warning")
            raise InstrumentCommunicationError(f"Could not parse error response: '{response}'", cause=e) from e

        if code != 0:
             self._log(f"Instrument Error Query: Code={code}, Message='{message}'", level="warning")
        else:
             self._log(f"Instrument Error Query: Code={code}, Message='{message}'", level="debug") # Debug level for "No error"
        return code, message

    def wait_for_operation_complete(self, query_instrument: bool = True, timeout: float = 10.0) -> Optional[str]:
        """
        Waits for the instrument to finish all pending overlapping commands.

        Uses either the blocking `*OPC?` query or the non-blocking `*OPC` command
        for synchronization. `*OPC?` is generally preferred for robust script control.

        Args:
            query_instrument: - If True (default): Sends `*OPC?`. This method will block
                                until the instrument finishes preceding commands and returns "1".
                              - If False: Sends `*OPC`. This method returns immediately. `*OPC`
                                sets a bit in the Standard Event Status Register upon completion,
                                requiring separate status polling by the calling script.
            timeout: Maximum time in seconds to wait for the `*OPC?` query to return.
                     Only applicable if `query_instrument` is True. Defaults to 10.0 seconds.
                     Note: Actual timeout behavior depends on the underlying VISA implementation.

        Returns:
            - If `query_instrument` is True: Returns "1" upon successful completion within timeout.
            - If `query_instrument` is False: Returns None immediately after sending `*OPC`.

        Raises:
            InstrumentCommunicationError: If `query_instrument` is True and the `*OPC?` query
                                          fails or times out.
        """
        if query_instrument:
            original_timeout = None
            if hasattr(self.instrument, 'timeout'):
                 try:
                      original_timeout = self.instrument.timeout # Store original timeout
                      # Set timeout for this specific query (convert s to ms for VISA)
                      visa_timeout_ms = max(1000, int(timeout * 1000)) # Ensure minimum 1 sec
                      self.instrument.timeout = visa_timeout_ms
                      self._log(f"Set VISA timeout to {visa_timeout_ms} ms for *OPC? query.")
                 except Exception as te:
                      self._log(f"Warning: Could not set VISA timeout for OPC?: {te}", level="warning")
                      # Proceed without timeout adjustment if setting fails

            try:
                # SCPI: *OPC? (Manual p.66) - Waits for completion, returns "1"
                response = self._query("*OPC?")
                self._log("Operation complete query (*OPC?) returned.")
                if response.strip() != "1":
                    # This indicates an unexpected response from the instrument
                    self._log(f"Warning: *OPC? returned '{response}' instead of expected '1'.", level="warning")
                return response.strip() # Return "1" or whatever was received
            except Exception as e:
                # Catch potential timeout errors or other communication issues
                # Specific timeout exception type depends on the backend (pyvisa, etc.)
                err_msg = f"*OPC? query failed or timed out after {timeout}s."
                self._log(err_msg, level="error")
                raise InstrumentCommunicationError(err_msg, cause=e) from e
            finally:
                 # Restore original timeout if it was changed
                 if original_timeout is not None and hasattr(self.instrument, 'timeout'):
                     try:
                          self.instrument.timeout = original_timeout
                          self._log(f"Restored VISA timeout to {original_timeout} ms.")
                     except Exception as te:
                          self._log(f"Warning: Could not restore VISA timeout after OPC?: {te}", level="warning")
        else:
            # SCPI: *OPC (Manual p.65) - Sets ESR bit 0 on completion, non-blocking command
            self._send_command("*OPC")
            self._log("Operation complete command (*OPC) sent (non-blocking). Status polling required.")
            # Check if the *OPC command itself was accepted without error
            self._error_check()
            return None
        

    def get_scpi_version(self) -> str:
        """
        Queries the version of the SCPI standard the instrument complies with.

        Returns:
            The SCPI version string (e.g., "1994.0").

        Raises:
            InstrumentCommunicationError: If the SCPI query fails.
        """
        # SCPI: SYSTem:VERSion? (Manual p.231)
        response = self._query("SYSTem:VERSion?").strip()
        self._log(f"SCPI Version reported: {response}")
        return response    
# def error_info(original_exception_type, custom_exception_type):
#     def decorator(func):
#         def wrapper(*args, **kwargs):
#             try:
#                 return func(*args, **kwargs)
#             except original_exception_type as e:
#                 raise custom_exception_type(e) from None
#         return wrapper
#     return decorator
