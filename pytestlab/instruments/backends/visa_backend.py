import pyvisa
from typing import Optional, TYPE_CHECKING
import time

from ...errors import InstrumentConnectionError, InstrumentCommunicationError
if TYPE_CHECKING:
    from ..instrument import InstrumentIO # For type hinting

class VisaBackend: # Intentionally not inheriting from InstrumentIO at runtime due to Protocol nature
    """
    A backend for communicating with instruments using pyvisa (sync).
    This class implements the InstrumentIO protocol.
    """
    def __init__(self, address: str, timeout_ms: Optional[int] = 5000):
        self.address = address
        self.rm = pyvisa.ResourceManager()
        self.instrument: Optional[pyvisa.resources.MessageBasedResource] = None
        self._timeout_ms = timeout_ms if timeout_ms is not None else 5000 # Default to 5 seconds

    def connect(self) -> None:
        """Connects to the VISA resource."""
        if self.instrument is not None:
            # Already connected or connection attempt made, ensure clean state if re-connecting
            try:
                self.instrument.close()
            except Exception:
                # Ignore errors on close if already disconnected or in bad state
                pass
            self.instrument = None

        try:
            # Type ignore for open_resource as pyvisa's stubs might not be perfectly aligned
            # with all resource types, but MessageBasedResource is common.
            resource = self.rm.open_resource(self.address) # type: ignore
            if not isinstance(resource, pyvisa.resources.MessageBasedResource):
                raise InstrumentConnectionError(
                    f"Resource at {self.address} is not a MessageBasedResource. Type: {type(resource).__name__}"
                )
            self.instrument = resource
            self.instrument.timeout = self._timeout_ms # pyvisa timeout is in milliseconds
        except pyvisa.Error as e: # Catch specific pyvisa errors
            raise InstrumentConnectionError(f"Failed to connect to VISA resource {self.address}: {e}") from e
        except Exception as e: # Catch other potential errors during connection
            raise InstrumentConnectionError(f"An unexpected error occurred while connecting to VISA resource {self.address}: {e}") from e

    def disconnect(self) -> None:
        """Disconnects from the VISA resource."""
        if self.instrument is not None:
            try:
                self.instrument.close()
            except pyvisa.Error as e:
                # Log or handle error during close if necessary
                raise InstrumentConnectionError(f"Error disconnecting from VISA resource {self.address}: {e}") from e
            except Exception as e:
                raise InstrumentConnectionError(f"An unexpected error occurred while disconnecting VISA resource {self.address}: {e}") from e
            finally:
                self.instrument = None
        # If already disconnected, do nothing.

    def write(self, cmd: str) -> None:
        """Writes a command to the instrument."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        try:
            self.instrument.write(cmd)
        except pyvisa.Error as e:
            raise InstrumentCommunicationError(f"Failed to write command '{cmd}' to {self.address}: {e}") from e
        except Exception as e:
            raise InstrumentCommunicationError(f"An unexpected error occurred writing command '{cmd}' to {self.address}: {e}") from e

    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """Sends a query to the instrument and returns the string response."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        try:
            response = self.instrument.query(cmd, delay=delay)
            return response.strip()
        except pyvisa.Error as e: # pyvisa.VisaIOError is a common one here
            raise InstrumentCommunicationError(f"Failed to query '{cmd}' from {self.address}: {e}") from e
        except Exception as e:
            raise InstrumentCommunicationError(f"An unexpected error occurred querying '{cmd}' from {self.address}: {e}") from e

    def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        """Sends a query and returns the raw bytes response."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        try:
            # pyvisa's query_binary_values might be more appropriate for some raw data,
            # but query_ascii_values(..., converter='s') or direct read after write can also work.
            # For simplicity and generality, using write then read_raw.
            # Ensure the instrument is configured for binary transfer if needed.
            self.instrument.write(cmd)
            if delay is not None:
                time.sleep(delay)
            data = self.instrument.read_bytes(self.instrument.chunk_size) # Or read_raw()
            return data
        except pyvisa.Error as e:
            raise InstrumentCommunicationError(f"Failed to query_raw '{cmd}' from {self.address}: {e}") from e
        except Exception as e:
            raise InstrumentCommunicationError(f"An unexpected error occurred during query_raw '{cmd}' from {self.address}: {e}") from e

    def close(self) -> None:
        """Closes the connection (alias for disconnect)."""
        self.disconnect()

    def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout in milliseconds."""
        if timeout_ms <= 0:
            raise ValueError("Timeout must be positive.")
        self._timeout_ms = timeout_ms
        if self.instrument:
            try:
                self.instrument.timeout = timeout_ms
            except pyvisa.Error as e:
                # Log this, but don't necessarily fail the operation if instrument is disconnected
                # or doesn't support dynamic timeout setting in its current state.
                # Consider raising InstrumentConfigurationError if strictness is required.
                print(f"Warning: Could not set timeout on VISA resource {self.address} (instrument may be disconnected or unresponsive): {e}")
            except Exception as e:
                print(f"Warning: An unexpected error occurred setting timeout on VISA resource {self.address}: {e}")


    def get_timeout(self) -> int:
        """Gets the communication timeout in milliseconds."""
        # Return the locally stored timeout, as reading from instrument might not always be reliable
        # or could cause unnecessary communication. The local value is the source of truth for new connections
        # and attempts to set it on the instrument.
        return self._timeout_ms

# To ensure VisaBackend correctly implements InstrumentIO, you can do a static check:
if TYPE_CHECKING:
    def _check_visa_backend_protocol(backend: InstrumentIO) -> None: ...
    def _test() -> None:
        _check_visa_backend_protocol(VisaBackend(address="TCPIP0::localhost::INSTR"))