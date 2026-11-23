import re
import time
from contextlib import suppress
from typing import TYPE_CHECKING
from typing import Any

import pyvisa
from pyvisa.constants import StatusCode
from pyvisa.rname import InvalidResourceName
from pyvisa.rname import TCPIPSocket
from pyvisa.rname import parse_resource_name

from ...errors import InstrumentCommunicationError
from ...errors import InstrumentConfigurationError
from ...errors import InstrumentConnectionError

if TYPE_CHECKING:
    from ..instrument import InstrumentIO  # For type hinting


class VisaBackend:  # Intentionally not inheriting from InstrumentIO at runtime due to Protocol nature
    """
    A backend for communicating with instruments using pyvisa (sync).
    This class implements the InstrumentIO protocol.
    """

    def __init__(self, address: str, timeout_ms: int | None = 5000):
        self.address = address
        self.rm = pyvisa.ResourceManager()
        self.instrument: pyvisa.resources.MessageBasedResource | None = None
        self._timeout_ms = timeout_ms if timeout_ms is not None else 5000  # Default to 5 seconds
        self._read_termination: str | None = None
        self._write_termination: str | None = None

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
            resource = self.rm.open_resource(self.address)
            if not isinstance(resource, pyvisa.resources.MessageBasedResource):
                raise InstrumentConnectionError(
                    f"Resource at {self.address} is not a MessageBasedResource. Type: {type(resource).__name__}"
                )
            self.instrument = resource
            self.instrument.timeout = self._timeout_ms  # pyvisa timeout is in milliseconds
            self._apply_read_termination()
            self._apply_write_termination()
        except pyvisa.Error as e:  # Catch specific pyvisa errors
            raise InstrumentConnectionError(
                f"Failed to connect to VISA resource {self.address}: {e}"
            ) from e
        except Exception as e:  # Catch other potential errors during connection
            raise InstrumentConnectionError(
                f"An unexpected error occurred while connecting to VISA resource {self.address}: {e}"
            ) from e

    def disconnect(self) -> None:
        """Disconnects from the VISA resource."""
        if self.instrument is not None:
            try:
                self.instrument.close()
            except pyvisa.Error as e:
                # Log or handle error during close if necessary
                raise InstrumentConnectionError(
                    f"Error disconnecting from VISA resource {self.address}: {e}"
                ) from e
            except Exception as e:
                raise InstrumentConnectionError(
                    f"An unexpected error occurred while disconnecting VISA resource {self.address}: {e}"
                ) from e
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
            raise InstrumentCommunicationError(
                f"Failed to write command '{cmd}' to {self.address}: {e}"
            ) from e
        except Exception as e:
            raise InstrumentCommunicationError(
                f"An unexpected error occurred writing command '{cmd}' to {self.address}: {e}"
            ) from e

    def query(self, cmd: str, delay: float | None = None) -> str:
        """Sends a query to the instrument and returns the string response."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        try:
            response = self.instrument.query(cmd, delay=delay)
            return response.strip()
        except pyvisa.Error as e:  # pyvisa.VisaIOError is a common one here
            raise InstrumentCommunicationError(
                f"Failed to query '{cmd}' from {self.address}: {e}"
            ) from e
        except Exception as e:
            raise InstrumentCommunicationError(
                f"An unexpected error occurred querying '{cmd}' from {self.address}: {e}"
            ) from e

    def query_ascii_socket_line(self, cmd: str, *, limit: int, timeout_ms: int) -> str:
        """Perform one byte-capped LF/ASCII exchange on a plain VISA TCPIP SOCKET."""
        try:
            address = parse_resource_name(self.address)
        except InvalidResourceName as exc:
            raise InstrumentConfigurationError(
                self.address, "Expected an explicit VISA TCPIP SOCKET address."
            ) from exc
        if (
            re.fullmatch(r"[A-Za-z0-9:*]+\?", cmd) is None
            or not 2 <= limit <= 2_000_000
            or timeout_ms <= 0
            or not isinstance(address, TCPIPSocket)
            or self._read_termination != "\n"
            or self._write_termination != "\n"
        ):
            raise InstrumentConfigurationError(
                self.address, "Bounded SCPI queries require a TCPIP SOCKET with LF framing."
            )
        resource = self.instrument
        if resource is None:
            raise InstrumentConnectionError(self.address, "SCPI SOCKET is disconnected.")
        try:
            previous = resource.timeout
            deadline = time.monotonic() + timeout_ms / 1000
            resource.timeout = timeout_ms
            if resource.read_termination != "\n" or resource.write_termination != "\n":
                raise ValueError("VISA resource did not retain LF framing")
            if resource.write(cmd, encoding="ascii") != len(cmd) + 1:
                raise ValueError("incomplete SCPI query write")
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                raise TimeoutError("read deadline expired")
            resource.timeout = remaining
            # read_raw() loops until VISA stops returning MAX_CNT; ordinary
            # query() strips LF. Read at most the caller's bound and verify it.
            data, status = resource.visalib.read(resource.session, limit)
            if (
                status != StatusCode.success_termination_character_read
                or re.fullmatch(rb"[\t\x20-\x7e]+\r?\n", data) is None
                or data.lstrip().startswith(b"#")
                or not data.strip()
            ):
                raise ValueError("expected one complete bounded ASCII line ending in LF")
            result = data.decode("ascii").strip()
            resource.timeout = previous
            return result
        except BaseException as exc:
            # Never let a timed-out, interrupted or malformed exchange poison
            # the next request on this stream. No SCPI recovery command.
            with suppress(Exception):
                self.disconnect()
            if not isinstance(exc, Exception):
                raise
            raise InstrumentCommunicationError(
                self.address, command=cmd, message=f"{exc}; socket discarded"
            ) from exc

    def prepare_read(self, *, raw: bool = False) -> None:
        method = "read_raw" if raw else "read"
        if self.instrument is None or not callable(getattr(self.instrument, method, None)):
            raise InstrumentConnectionError(f"VISA resource does not support {method}().")

    def read(self) -> str:
        """Read pending text without writing a command first."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        try:
            return self.instrument.read().strip()
        except Exception as error:
            raise InstrumentCommunicationError(
                instrument=self.address, message=f"Native read failed: {error}"
            ) from error

    def read_raw(self) -> bytes:
        """Read an EOI-framed binary message independently of text EOS."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        resource: Any = self.instrument
        previous = resource.read_termination
        try:
            resource.read_termination = None
            return self.instrument.read_raw()
        except Exception as error:
            raise InstrumentCommunicationError(
                instrument=self.address, message=f"Native raw read failed: {error}"
            ) from error
        finally:
            resource.read_termination = previous

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        """Write once and read a binary message without text termination."""
        self.write(cmd)
        if delay is not None:
            time.sleep(delay)
        return self.read_raw()

    @staticmethod
    def _validate_read_termination(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("Read termination must be a string or None.")
        try:
            value[-1].encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(
                "Read termination's final character must be a single-byte ASCII character."
            ) from exc
        return value

    def _apply_read_termination(self) -> None:
        if self.instrument is None:
            return
        try:
            self.instrument.read_termination = self._read_termination or ""
        except pyvisa.Error as exc:
            raise InstrumentCommunicationError(
                f"Failed to set read termination on {self.address}: {exc}"
            ) from exc
        except Exception as exc:
            raise InstrumentCommunicationError(
                f"Unexpected error setting read termination on {self.address}: {exc}"
            ) from exc

    def set_read_termination(self, value: str | None) -> None:
        """Configure text EOS; raw reads remain binary-safe."""
        self._read_termination = self._validate_read_termination(value)
        self._apply_read_termination()

    @staticmethod
    def _validate_write_termination(value: str | None) -> str:
        if value is None or value == "":
            return ""
        if not isinstance(value, str):
            raise TypeError("Write termination must be a string or None.")
        if value not in {"\n", "\r", "\r\n"}:
            raise ValueError("Write termination must be None, empty, LF, CR, or CRLF.")
        return value

    def _apply_write_termination(self) -> None:
        if self.instrument is None or self._write_termination is None:
            return
        try:
            self.instrument.write_termination = self._write_termination
        except pyvisa.Error as exc:
            raise InstrumentCommunicationError(
                f"Failed to set write termination on {self.address}: {exc}"
            ) from exc
        except Exception as exc:
            raise InstrumentCommunicationError(
                f"Unexpected error setting write termination on {self.address}: {exc}"
            ) from exc

    def set_write_termination(self, value: str | None) -> None:
        """Configure command EOS; None and empty select EOI-only writes."""
        self._write_termination = self._validate_write_termination(value)
        self._apply_write_termination()

    def read_status_byte(self) -> int:
        """Read the native VISA status byte without sending a SCPI query."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        try:
            return self.instrument.read_stb()
        except pyvisa.Error as exc:
            raise InstrumentCommunicationError(
                f"Failed to read status byte from {self.address}: {exc}"
            ) from exc
        except Exception as exc:
            raise InstrumentCommunicationError(
                f"Unexpected error reading status byte from {self.address}: {exc}"
            ) from exc

    def device_clear(self) -> None:
        """Abort pending I/O using VISA Device Clear, not a queued SCPI command."""
        if self.instrument is None:
            raise InstrumentConnectionError("Not connected to VISA resource. Call connect() first.")
        try:
            self.instrument.clear()
        except pyvisa.Error as exc:
            raise InstrumentCommunicationError(
                instrument=self.address, message=f"VISA Device Clear failed: {exc}"
            ) from exc

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
                print(
                    f"Warning: Could not set timeout on VISA resource {self.address} (instrument may be disconnected or unresponsive): {e}"
                )
            except Exception as e:
                print(
                    f"Warning: An unexpected error occurred setting timeout on VISA resource {self.address}: {e}"
                )

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
