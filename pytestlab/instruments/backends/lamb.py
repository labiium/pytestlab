from __future__ import annotations

import httpx # For asynchronous HTTP requests
from typing import Optional, Dict, Any, TYPE_CHECKING
import logging # For logging

from ...errors import InstrumentConnectionError, InstrumentCommunicationError

if TYPE_CHECKING:
    from ..instrument import AsyncInstrumentIO # For type hinting

# Setup logger for this backend
try:
    from ..._log import get_logger
    lamb_logger = get_logger("lamb.backend")
except ImportError:
    lamb_logger = logging.getLogger("lamb.backend_fallback")
    lamb_logger.warning("Could not import pytestlab's get_logger; LambBackend using fallback logger.")


class AsyncLambBackend: # Implements AsyncInstrumentIO
    """
    An asynchronous backend for communicating with instruments via a Lamb server.
    This class implements the AsyncInstrumentIO protocol using httpx.
    """
    def __init__(self, address: str, url: str = "http://lamb-server:8000", timeout_ms: Optional[int] = 5000):
        """
        Initializes the AsyncLambBackend.

        Args:
            address (str): The identifier for the instrument on the Lamb server (e.g., its VISA string or unique ID).
            url (str): The base URL of the Lamb server.
            timeout_ms (Optional[int]): Default communication timeout in milliseconds.
        """
        self.base_url: str = url.rstrip('/')
        self.instrument_address: str = address # This is the equivalent of visa_string for an existing instrument
        self._timeout_sec: float = (timeout_ms / 1000.0) if timeout_ms is not None and timeout_ms > 0 else 5.0
        self._client: Optional[httpx.AsyncClient] = None # Client can be managed or created per request
        lamb_logger.info(f"AsyncLambBackend initialized for address '{address}' at URL '{url}' with timeout {self._timeout_sec}s.")

    async def _get_client(self) -> httpx.AsyncClient:
        """Returns a shared httpx.AsyncClient instance, creating it if necessary."""
        # For simplicity, this example creates a new client per call or uses a context manager.
        # If a shared client is desired for performance (e.g. connection pooling),
        # it should be managed (created in connect, closed in disconnect).
        # For now, we'll create it within each method using a context manager.
        # This method is a placeholder if a shared client strategy is adopted later.
        # For now, it's not used.
        raise NotImplementedError("Shared client strategy not implemented yet. Use client per request.")

    async def connect(self) -> None:
        """
        Establishes and verifies the connection to the Lamb server for the instrument.
        This could involve a ping or a status check to the Lamb server.
        """
        lamb_logger.info(f"Attempting to connect/verify instrument '{self.instrument_address}' on Lamb server '{self.base_url}'.")
        try:
            async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                # Example: Ping a general health endpoint or a specific instrument status endpoint
                # This depends on the Lamb server's API.
                # For now, we'll assume a simple check like trying to get instrument details.
                # Replace with actual Lamb server health/status check endpoint if available.
                response = await client.post(
                    f"{self.base_url}/instrument/status", # Fictional status endpoint
                    json={"visa_string": self.instrument_address},
                    headers={"Accept": "application/json"}
                )
                response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx
                lamb_logger.info(f"Successfully connected to and verified instrument '{self.instrument_address}' on Lamb server.")
        except httpx.HTTPStatusError as e:
            lamb_logger.error(f"Failed to connect/verify instrument '{self.instrument_address}': HTTP {e.response.status_code} - {e.response.text}")
            raise InstrumentConnectionError(
                f"Lamb server returned an error for '{self.instrument_address}': {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            lamb_logger.error(f"Network error while trying to connect to Lamb server at '{self.base_url}': {e}")
            raise InstrumentConnectionError(f"Could not connect to Lamb server at '{self.base_url}': {e}") from e
        except Exception as e:
            lamb_logger.error(f"Unexpected error during connect for '{self.instrument_address}': {e}")
            raise InstrumentConnectionError(f"Unexpected error connecting to Lamb server: {e}") from e

    async def disconnect(self) -> None:
        """
        Closes the connection to the Lamb server (if a persistent client was used).
        For clients created per-request, this might be a no-op or log action.
        """
        lamb_logger.info(f"AsyncLambBackend for '{self.instrument_address}' disconnected (simulated, as client is per-request or context-managed).")
        # If self._client was a persistent shared client:
        # if self._client:
        #     await self._client.aclose()
        #     self._client = None
        pass # No specific action if client is per-request

    async def write(self, cmd: str) -> None:
        """Sends a write command to the instrument via the Lamb server."""
        lamb_logger.debug(f"WRITE to '{self.instrument_address}': {cmd}")
        try:
            async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                response = await client.post(
                    f"{self.base_url}/instrument/write",
                    json={"visa_string": self.instrument_address, "command": cmd},
                    headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            lamb_logger.error(f"Lamb server write error for '{self.instrument_address}', cmd '{cmd}': {e.response.status_code} - {e.response.text}")
            raise InstrumentCommunicationError(f"Lamb server write failed: {e.response.status_code} - {e.response.text}") from e
        except httpx.RequestError as e:
            lamb_logger.error(f"Network error during write to Lamb server for '{self.instrument_address}', cmd '{cmd}': {e}")
            raise InstrumentCommunicationError(f"Network error during Lamb write: {e}") from e

    async def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """Sends a query to the instrument via Lamb server and returns string response."""
        lamb_logger.debug(f"QUERY to '{self.instrument_address}': {cmd}" + (f" (delay {delay}s - ignored by Lamb)" if delay else ""))
        try:
            async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                response = await client.post(
                    f"{self.base_url}/instrument/query",
                    json={"visa_string": self.instrument_address, "command": cmd},
                    headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
                )
                response.raise_for_status()
                content: str = response.content.decode('utf-8')
                # Lamb server might or might not strip newline, client should handle
                return content.strip() # Ensure consistent stripping
        except httpx.HTTPStatusError as e:
            lamb_logger.error(f"Lamb server query error for '{self.instrument_address}', cmd '{cmd}': {e.response.status_code} - {e.response.text}")
            raise InstrumentCommunicationError(f"Lamb server query failed: {e.response.status_code} - {e.response.text}") from e
        except httpx.RequestError as e:
            lamb_logger.error(f"Network error during query to Lamb server for '{self.instrument_address}', cmd '{cmd}': {e}")
            raise InstrumentCommunicationError(f"Network error during Lamb query: {e}") from e

    async def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        """Sends a query via Lamb server and returns raw bytes response."""
        lamb_logger.debug(f"QUERY_RAW to '{self.instrument_address}': {cmd}" + (f" (delay {delay}s - ignored by Lamb)" if delay else ""))
        try:
            async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                response = await client.post(
                    f"{self.base_url}/instrument/query_raw",
                    json={"visa_string": self.instrument_address, "command": cmd},
                    headers={"Accept": "application/octet-stream"} # Or appropriate for raw bytes
                )
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            lamb_logger.error(f"Lamb server query_raw error for '{self.instrument_address}', cmd '{cmd}': {e.response.status_code} - {e.response.text}")
            raise InstrumentCommunicationError(f"Lamb server query_raw failed: {e.response.status_code} - {e.response.text}") from e
        except httpx.RequestError as e:
            lamb_logger.error(f"Network error during query_raw to Lamb server for '{self.instrument_address}', cmd '{cmd}': {e}")
            raise InstrumentCommunicationError(f"Network error during Lamb query_raw: {e}") from e

    async def close(self) -> None:
        """Closes the connection (alias for disconnect)."""
        await self.disconnect()

    async def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout in milliseconds for subsequent requests."""
        if timeout_ms <= 0:
            lamb_logger.warning(f"Attempted to set non-positive timeout: {timeout_ms}ms. Using 1ms instead.")
            self._timeout_sec = 0.001 # Prevent zero or negative timeout for httpx
        else:
            self._timeout_sec = timeout_ms / 1000.0
        lamb_logger.debug(f"AsyncLambBackend timeout set to {self._timeout_sec} seconds.")

    async def get_timeout(self) -> int:
        """Gets the communication timeout in milliseconds."""
        return int(self._timeout_sec * 1000)

# Static type checking helper
if TYPE_CHECKING:
    def _check_lamb_backend_protocol(backend: AsyncInstrumentIO) -> None: ...
    def _test_lamb_async() -> None:
        _check_lamb_backend_protocol(AsyncLambBackend(address="GPIB0::1::INSTR", url="http://localhost:8000"))