import pyvisa
import anyio
from typing import Optional, TYPE_CHECKING, cast
import time # For query_raw with delay, though ideally handled by VISA layer if possible

from ...errors import InstrumentConnectionError, InstrumentCommunicationError
if TYPE_CHECKING:
    from ..instrument import AsyncInstrumentIO # For type hinting
    from pyvisa.resources import MessageBasedResource # Specific type for instrument

class AsyncVisaBackend: # Intentionally not inheriting from AsyncInstrumentIO at runtime
    """
    An asynchronous backend for communicating with instruments using pyvisa,
    by running blocking calls in a separate thread via anyio.
    This class implements the AsyncInstrumentIO protocol.
    """
    def __init__(self, address: str, timeout_ms: Optional[int] = 5000):
        self.address = address
        self.rm = pyvisa.ResourceManager()
        self.instrument: Optional[MessageBasedResource] = None
        self._timeout_ms = timeout_ms if timeout_ms is not None else 5000 # Default to 5 seconds
        self._lock = anyio.Lock() # For thread-safety around instrument access

    def connect(self) -> None:
        """Connects to the VISA resource asynchronously."""
        with self._lock:
            if self.instrument is not None:
                try:
                    # Ensure existing instrument is closed before reconnecting
                    self.instrument.close()
                except Exception:
                    # Ignore errors if already closed or in a bad state
                    pass
                self.instrument = None

            try:
                # Open the resource directly (synchronous)
                resource = self.rm.open_resource(self.address)
                if not isinstance(resource, pyvisa.resources.MessageBasedResource):
                    raise InstrumentConnectionError(
                        f"Resource at {self.address} is not a MessageBasedResource. Type: {type(resource).__name__}"
                    )
                self.instrument = cast('MessageBasedResource', resource) # Cast for type checker

                # Set timeout on the instrument object
                self.instrument.timeout = self._timeout_ms

            except pyvisa.Error as e:
                raise InstrumentConnectionError(f"Failed to connect to VISA resource {self.address}: {e}") from e
            except Exception as e:
                raise InstrumentConnectionError(f"An unexpected error occurred while connecting to VISA resource {self.address}: {e}") from e

    def disconnect(self) -> None:
        """Disconnects from the VISA resource asynchronously."""
        with self._lock:
            if self.instrument is not None:
                try:
                    self.instrument.close()
                except pyvisa.Error as e:
                    raise InstrumentConnectionError(f"Error disconnecting from VISA resource {self.address}: {e}") from e
                except Exception as e:
                    raise InstrumentConnectionError(f"An unexpected error occurred while disconnecting VISA resource {self.address}: {e}") from e
                finally:
                    self.instrument = None

    def write(self, cmd: str) -> None:
        """Writes a command to the instrument asynchronously."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")

        instr = self.instrument # Local reference for thread safety
        def _blocking_write(command: str) -> None:
            instr.write(command)

        with self._lock: # Ensure exclusive access for the write operation
            if self.instrument is None: # Re-check after acquiring lock
                 raise InstrumentConnectionError("Instrument became disconnected before write.")
            try:
                _blocking_write(cmd)
            except pyvisa.Error as e:
                raise InstrumentCommunicationError(f"Failed to write command '{cmd}' to {self.address}: {e}") from e
            except Exception as e:
                raise InstrumentCommunicationError(f"An unexpected error occurred writing command '{cmd}' to {self.address}: {e}") from e

    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """Sends a query and returns the string response asynchronously."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")

        instr = self.instrument # Local reference
        def _blocking_query(command: str, q_delay: Optional[float]) -> str:
            return instr.query(command, delay=q_delay).strip()

        with self._lock:
            if self.instrument is None:
                 raise InstrumentConnectionError("Instrument became disconnected before query.")
            try:
                response = _blocking_query(cmd, delay)
                return response
            except pyvisa.Error as e:
                raise InstrumentCommunicationError(f"Failed to query '{cmd}' from {self.address}: {e}") from e
            except Exception as e:
                raise InstrumentCommunicationError(f"An unexpected error occurred querying '{cmd}' from {self.address}: {e}") from e

    def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        """Sends a query and returns the raw bytes response asynchronously."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")

        instr = self.instrument # Local reference
        def _blocking_query_raw(command: str, q_delay: Optional[float]) -> bytes:
            instr.write(command) # Write the command
            if q_delay is not None:
                time.sleep(q_delay) # Blocking sleep in the thread
            # Assuming read_bytes is the appropriate method for raw data.
            # Adjust chunk_size or method (e.g. read_raw()) as needed.
            return instr.read_bytes(instr.chunk_size)

        with self._lock:
            if self.instrument is None:
                 raise InstrumentConnectionError("Instrument became disconnected before query_raw.")
            try:
                data = _blocking_query_raw(cmd, delay)
                return data
            except pyvisa.Error as e:
                raise InstrumentCommunicationError(f"Failed to query_raw '{cmd}' from {self.address}: {e}") from e
            except Exception as e:
                raise InstrumentCommunicationError(f"An unexpected error occurred during query_raw '{cmd}' from {self.address}: {e}") from e

    def close(self) -> None:
        """Closes the connection asynchronously (alias for disconnect)."""
        self.disconnect()

    def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout in milliseconds asynchronously."""
        if timeout_ms <= 0:
            raise ValueError("Timeout must be positive.")

        self._timeout_ms = timeout_ms # Update local store immediately

        if self.instrument:
            instr = self.instrument # Local reference
            def _blocking_set_timeout(timeout_val: int) -> None:
                instr.timeout = timeout_val

            with self._lock: # Ensure instrument object isn't changed during this
                if self.instrument: # Re-check after lock
                    try:
                        _blocking_set_timeout(timeout_ms)
                    except pyvisa.Error as e:
                        # Log this, but don't necessarily fail the operation.
                        print(f"Warning: Could not set timeout on VISA resource {self.address}: {e}")
                    except Exception as e:
                        print(f"Warning: An unexpected error occurred setting timeout on VISA resource {self.address}: {e}")


    def get_timeout(self) -> int:
        """Gets the communication timeout in milliseconds."""
        # Return the locally stored timeout. Reading from instrument is not always reliable
        # and the local value is the intended setting.
        return self._timeout_ms

# Static type checking helper
if TYPE_CHECKING:
    def _check_async_visa_backend_protocol(backend: AsyncInstrumentIO) -> None: ...
    def _test_async() -> None:
        _check_async_visa_backend_protocol(AsyncVisaBackend(address="TCPIP0::localhost::INSTR"))
