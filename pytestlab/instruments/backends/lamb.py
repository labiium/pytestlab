from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import httpx

from ...errors import InstrumentCommunicationError
from ...errors import InstrumentConnectionError

# if TYPE_CHECKING:
from ..instrument import InstrumentIO

try:
    from ..._log import get_logger

    lamb_logger = get_logger("lamb.backend")
except ImportError:
    lamb_logger = logging.getLogger("lamb.backend_fallback")
    lamb_logger.warning(
        "Could not import pytestlab's get_logger; LambBackend using fallback logger."
    )


class LambBackend(InstrumentIO):  # Implements InstrumentIO
    """
    An backend for communicating with instruments via a Lamb server.
    Supports direct resource strings and auto-connect via model/serial_number.
    """

    def __init__(
        self,
        address: str | None = None,
        url: str = "http://lamb-server:8000",
        timeout_ms: int | None = 10000,
        model_name: str | None = None,
        serial_number: str | None = None,
    ):
        """
        Args:
            address: The resource string or unique instrument address. If not provided, model_name and serial_number must be provided.
            url: Lamb server base URL.
            timeout_ms: Communication timeout in ms.
            model_name: Model name for auto-connect.
            serial_number: Serial number for auto-connect.
        """
        self.base_url: str = url.rstrip("/")
        self.instrument_address: str | None = address  # resource_string
        self._register_explicit_gpib = bool(
            address and re.fullmatch(r"GPIB\d+::\d+(?:::\d+)?::INSTR", address, re.IGNORECASE)
        )
        self.model_name: str | None = model_name
        self.serial_number: str | None = serial_number
        self._timeout_sec: float = (timeout_ms / 1000.0) if timeout_ms and timeout_ms > 0 else 5.0
        self._client: httpx.Client | None = None
        self._auto_connect_performed: bool = False

        lamb_logger.info(
            f"LambBackend initialized for address='{address}', model='{model_name}', serial='{serial_number}' at URL '{url}'"
        )

    def _ensure_connected(self) -> None:
        """
        Ensures that self.instrument_address is set.
        If not, and model_name/serial_number are provided, performs auto-connect.
        """
        if self.instrument_address and not self._register_explicit_gpib:
            return  # Already have resource_string/address

        model_name = (
            self.instrument_address if self._register_explicit_gpib else self.model_name
        )
        if not model_name:
            raise InstrumentConnectionError(
                "LambBackend requires either a resource_string/address or at least model_name for auto-connect."
            )

        # Perform auto-connect via /add endpoint
        try:
            payload = {"model_name": model_name}
            if self.serial_number and not self._register_explicit_gpib:
                payload["serial_number"] = self.serial_number
            with httpx.Client(timeout=self._timeout_sec) as client:
                response = client.post(
                    f"{self.base_url}/add",
                    json=payload,
                    headers={"Accept": "application/json", "Accept-Charset": "utf-8"},
                )
                if response.status_code != 200:
                    raise InstrumentConnectionError(
                        f"Lamb server /add failed: {response.status_code} - {response.text}"
                    )
                # The response should be the resource_string
                resource_string = response.text.strip()
                if not resource_string:
                    raise InstrumentConnectionError(
                        f"Lamb server /add returned empty resource_string for model={self.model_name}, serial={self.serial_number}"
                    )
                self.instrument_address = resource_string
                self._register_explicit_gpib = False
                self._auto_connect_performed = True
                lamb_logger.info(
                    f"LambBackend auto-connected: model={self.model_name}, serial={self.serial_number} -> resource_string={resource_string}"
                )
        except httpx.RequestError as e:
            raise InstrumentConnectionError(f"Network error during Lamb auto-connect: {e}") from e

    def connect(self) -> None:
        """
        Ensures the instrument is registered with Lamb and ready.
        """
        self._ensure_connected()
        # Optionally, ping instrument status endpoint here
        lamb_logger.info(f"Connected to Lamb instrument '{self.instrument_address}'.")

    def disconnect(self) -> None:
        lamb_logger.info(
            f"LambBackend for '{self.instrument_address}' disconnected (simulated, as client is per-request or context-managed)."
        )
        pass

    def write(self, cmd: str) -> None:
        self._ensure_connected()
        lamb_logger.debug(f"WRITE to '{self.instrument_address}': {cmd}")
        try:
            with httpx.Client(timeout=self._timeout_sec) as client:
                response = client.post(
                    f"{self.base_url}/instrument/write",
                    json={"resource_string": self.instrument_address, "command": cmd},
                    headers={"Accept": "application/json", "Accept-Charset": "utf-8"},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise InstrumentCommunicationError(
                f"Lamb server write failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise InstrumentCommunicationError(f"Network error during Lamb write: {e}") from e

    def query(self, cmd: str, delay: float | None = None) -> str:
        self._ensure_connected()
        lamb_logger.debug(f"QUERY to '{self.instrument_address}': {cmd}")
        try:
            with httpx.Client(timeout=self._timeout_sec) as client:
                response = client.post(
                    f"{self.base_url}/instrument/query",
                    json={"resource_string": self.instrument_address, "command": cmd},
                    headers={"Accept": "application/json", "Accept-Charset": "utf-8"},
                )
                response.raise_for_status()
                content: str = response.content.decode("utf-8")
                return content.strip()
        except httpx.HTTPStatusError as e:
            raise InstrumentCommunicationError(
                f"Lamb server query failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise InstrumentCommunicationError(f"Network error during Lamb query: {e}") from e

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        self._ensure_connected()
        lamb_logger.debug(f"QUERY_RAW to '{self.instrument_address}': {cmd}")
        try:
            with httpx.Client(timeout=self._timeout_sec) as client:
                response = client.post(
                    f"{self.base_url}/instrument/query_raw",
                    json={"resource_string": self.instrument_address, "command": cmd},
                    headers={"Accept": "application/octet-stream"},
                )
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            raise InstrumentCommunicationError(
                f"Lamb server query_raw failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise InstrumentCommunicationError(f"Network error during Lamb query_raw: {e}") from e

    def close(self) -> None:
        self.disconnect()

    def set_timeout(self, timeout_ms: int) -> None:
        if timeout_ms <= 0:
            self._timeout_sec = 0.001
        else:
            self._timeout_sec = timeout_ms / 1000.0
        lamb_logger.debug(f"LambBackend timeout set to {self._timeout_sec} seconds.")

    def get_timeout(self) -> int:
        return int(self._timeout_sec * 1000)


# Static type checking helper
if TYPE_CHECKING:

    def _check_lamb_backend_protocol(backend: InstrumentIO) -> None: ...
    def _test_lamb() -> None:
        _check_lamb_backend_protocol(
            LambBackend(address="GPIB0::1::INSTR", url="http://localhost:8000")
        )
