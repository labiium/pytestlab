from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
from typing import TYPE_CHECKING
from typing import Any

import httpx

from ..._lamb_url import DEFAULT_LAMB_URL as DEFAULT_LAMB_URL
from ..._lamb_url import resolve_lamb_url
from ...errors import InstrumentCommunicationError
from ...errors import InstrumentConfigurationError
from ...errors import InstrumentConnectionError

# if TYPE_CHECKING:
from ..command_attribution import describe_emitter
from ..instrument import InstrumentIO

DEFAULT_TIMEOUT_MS = 30_000
HTTP_TIMEOUT_GRACE_SEC = 5.0
_EXPLICIT_GPIB = re.compile(r"GPIB\d+::\d+(?:::\d+)?::INSTR", re.IGNORECASE)

try:
    from ..._log import get_logger

    lamb_logger = get_logger("lamb.backend")
except ImportError:
    lamb_logger = logging.getLogger("lamb.backend_fallback")
    lamb_logger.warning(
        "Could not import pytestlab's get_logger; LambBackend using fallback logger."
    )


class LambBackend(InstrumentIO):  # Implements InstrumentIO
    """Synchronous instrument transport through a LAMB HTTP server.

    Connect directly with a server-side resource string, or discover a
    resource by model and optional serial number. Query, raw-query, timeout, and
    lifecycle methods implement the shared ``InstrumentIO`` contract.
    """

    def __init__(
        self,
        address: str | None = None,
        url: str | None = None,
        timeout_ms: int | None = DEFAULT_TIMEOUT_MS,
        model_name: str | None = None,
        serial_number: str | None = None,
    ):
        """
        Args:
            address: The resource_string or unique instrument address. If not provided, model_name and serial_number must be provided.
            url: Lamb server base URL.
            timeout_ms: Communication timeout in ms. Defaults to 30 seconds; use per-operation overrides for exceptional long operations.
            model_name: Model name for auto-connect.
            serial_number: Serial number for auto-connect.
        """
        self.base_url: str = resolve_lamb_url(url)
        self.instrument_address: str | None = address  # resource_string
        # Explicit resource URIs remain authoritative across LAMB handle
        # reactivation. A server-side /add response must never replace it.
        self._explicit_address: str | None = address or None
        self._register_explicit_gpib = bool(address and _EXPLICIT_GPIB.fullmatch(address))
        self._explicit_address_registered = False
        self.model_name: str | None = model_name
        self.serial_number: str | None = serial_number
        effective_timeout_ms = DEFAULT_TIMEOUT_MS if timeout_ms is None else max(1, timeout_ms)
        self._timeout_sec: float = effective_timeout_ms / 1000.0
        self._client: httpx.Client | None = None
        self._auto_connect_performed: bool = False
        self._resource_acquired = False
        self._read_termination: str | None = None
        self._write_termination: str | None = None
        self._write_termination_configured = False
        self._query_delay_supported: bool | None = None
        self._verified_capabilities: set[str] = set()
        self._minimum_interval_s = 0.0

        lamb_logger.info(
            f"LambBackend initialized for address='{address}', model='{model_name}', serial='{serial_number}' at URL '{url}'"
        )

    @staticmethod
    def _tim_attribution_enabled() -> bool:
        # The TIM launcher sets these together for the PyTestLab lane. Run
        # and block IDs are optional there. Origin/token alone do not opt in.
        explicit = os.getenv("PYTESTLAB_TIM_ATTRIBUTION")
        if explicit is not None:
            return explicit.strip().lower() in {"1", "true", "yes", "on"}
        return os.getenv("TIM_HARNESS_ARM", "").strip() == "pytestlab" and all(
            os.getenv(name, "").strip()
            for name in (
                "TIM_LAMB_RUNTIME_MANIFEST",
                "TIM_HARNESS_TASK_ID",
                "TIM_HARNESS_VARIANT_ID",
            )
        )

    @staticmethod
    def _request_headers(accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept, "Accept-Charset": "utf-8"}
        if not LambBackend._tim_attribution_enabled():
            return headers
        headers["X-TIM-Origin"] = os.getenv("TIM_LAMB_ORIGIN", "controller").strip() or "controller"
        try:
            headers["X-TIM-Emitter"] = json.dumps(describe_emitter(), separators=(",", ":"))
        except Exception as exc:
            frame = sys._getframe(1)
            emitter = {
                "schema_version": 1,
                "kind": "transport",
                "method": "LambBackend",
                "callsite": {"file": frame.f_code.co_filename, "line": frame.f_lineno},
                "basis": "python_call_stack",
                "transport": "pytestlab_lamb",
                "classification_complete": False,
                "instrumentation_error": type(exc).__name__,
            }
            headers["X-TIM-Emitter"] = json.dumps(emitter, separators=(",", ":"))
        for header, variable in (
            ("X-TIM-Harness-Run-Id", "TIM_HARNESS_RUN_ID"),
            ("X-TIM-Block-Id", "TIM_HARNESS_BLOCK_ID"),
            ("X-TIM-Arm", "TIM_HARNESS_ARM"),
            ("X-TIM-Task-Id", "TIM_HARNESS_TASK_ID"),
            ("X-TIM-Variant-Id", "TIM_HARNESS_VARIANT_ID"),
        ):
            if value := os.getenv(variable, "").strip():
                headers[header] = value
        operation_token = os.getenv("TIM_LAMB_OPERATION_TOKEN", "").strip()
        if operation_token:
            headers["X-TIM-Operation-Token"] = operation_token
        return headers

    def _ensure_connected(self) -> None:
        """
        Ensures that self.instrument_address is set.
        If not, and model_name/serial_number are provided, performs auto-connect.
        """
        if self._write_termination_configured:
            self._ensure_server_capability("write_termination")
        if self._minimum_interval_s:
            self._ensure_server_capability("resource_timing_policy")
        if self._explicit_address:
            self.instrument_address = self._explicit_address
            if self._register_explicit_gpib and not self._explicit_address_registered:
                self._activate_explicit_address()
            return
        if self.instrument_address:
            return  # Already auto-connected by model/serial.

        if not self.model_name:
            raise InstrumentConnectionError(
                "LambBackend requires either a resource_string/address or at least model_name for auto-connect."
            )

        # Perform auto-connect via /add endpoint
        try:
            payload = {"model_name": self.model_name}
            if self.serial_number:
                payload["serial_number"] = self.serial_number
            response = self._post_request(
                f"{self.base_url}/add",
                json=payload,
                headers=self._request_headers(),
                timeout=self._http_timeout_sec(),
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
            self._auto_connect_performed = True
            self._resource_acquired = True
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
        client, self._client = self._client, None
        self._verified_capabilities.clear()
        self._query_delay_supported = None
        if client is not None:
            client.close()
        lamb_logger.info(f"LambBackend for '{self.instrument_address}' disconnected.")

    def reconnect(
        self,
        *,
        model_name: str | None = None,
        serial_number: str | None = None,
    ) -> None:
        """Replace the managed LAMB session and resolve its current address."""

        if model_name:
            self.model_name = model_name
        if serial_number:
            self.serial_number = serial_number
        self.close()
        self.connect()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def _http_timeout_sec(self) -> float:
        """HTTP timeout for LAMB requests.

        The payload timeout is the instrument operation budget enforced by
        LAMB/VISA. The HTTP client gets an additional grace window so server
        504/structured errors can return instead of PyTestLab timing out first.
        """
        return self._timeout_sec + HTTP_TIMEOUT_GRACE_SEC

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

    def set_read_termination(self, value: str | None) -> None:
        """Configure text EOS; raw transfers never include this field."""
        self._read_termination = self._validate_read_termination(value)

    @staticmethod
    def _validate_write_termination(value: str | None) -> str:
        if value is None or value == "":
            return ""
        if not isinstance(value, str):
            raise TypeError("Write termination must be a string or None.")
        if value not in {"\n", "\r", "\r\n"}:
            raise ValueError("Write termination must be None, empty, LF, CR, or CRLF.")
        return value

    def set_write_termination(self, value: str | None) -> None:
        """Configure command framing; require server support before instrument I/O."""
        termination = self._validate_write_termination(value)
        self._ensure_server_capability("write_termination")
        self._write_termination = termination
        self._write_termination_configured = True

    def _instrument_payload(
        self,
        cmd: str | None,
        *,
        include_read_termination: bool = False,
        query_delay_ms: int | None = None,
    ) -> dict[str, str | int | None]:
        """Build a LAMB instrument operation payload.

        LAMB servers before per-request operation budgets ignore the timeout
        field, while newer servers use it to keep server-side VISA/USBTMC
        budgets aligned with the existing PyTestLab backend timeout setting.
        """
        timeout_ms = max(1, int(self._timeout_sec * 1000))
        payload: dict[str, str | int | None] = {
            "resource_string": self._explicit_address or self.instrument_address or "",
            "timeout_ms": timeout_ms,
        }
        if cmd is not None:
            payload["command"] = cmd
            if self._write_termination_configured:
                payload["write_termination"] = self._write_termination
        if self._minimum_interval_s:
            payload["min_command_interval_ms"] = math.ceil(self._minimum_interval_s * 1000)
        if include_read_termination:
            payload["read_termination"] = (
                ord(self._read_termination[-1]) if self._read_termination else None
            )
        if query_delay_ms is not None:
            payload["query_delay_ms"] = query_delay_ms
        return payload

    @staticmethod
    def _query_delay_ms(delay: float | None) -> int | None:
        if delay is None:
            return None
        if isinstance(delay, bool) or not isinstance(delay, (int, float)):
            raise ValueError("Query delay must be a finite, non-negative number of seconds.")
        if not math.isfinite(float(delay)) or delay < 0:
            raise ValueError("Query delay must be a finite, non-negative number of seconds.")
        if delay == 0:
            return None
        return math.ceil(float(delay) * 1000)

    def _ensure_server_capability(self, name: str) -> None:
        if name in self._verified_capabilities:
            return
        try:
            response = self._get_client().get(
                f"{self.base_url}/capabilities",
                headers=self._request_headers(),
                timeout=self._http_timeout_sec(),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get(name) is not True:
                raise InstrumentCommunicationError(
                    message=f"LAMB server does not advertise {name} capability."
                )
            self._verified_capabilities.update(
                key for key, value in payload.items() if value is True
            )
        except InstrumentCommunicationError:
            raise
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise InstrumentCommunicationError(
                message=f"Unable to verify LAMB {name} capability: {error}"
            ) from error

    def _ensure_query_delay_capability(self) -> None:
        self._ensure_server_capability("query_delay_ms")
        self._query_delay_supported = True

    def set_min_command_interval(self, seconds: float) -> None:
        """Register a minimum spacing policy before instrument I/O."""
        milliseconds = self._query_delay_ms(seconds)
        if milliseconds is None or seconds <= self._minimum_interval_s:
            return
        address = self._explicit_address or self.instrument_address
        if not address:
            raise InstrumentConfigurationError(
                "LAMB timing", "Mandatory timing requires an explicit physical resource URI."
            )
        self._ensure_server_capability("resource_timing_policy")
        try:
            response = self._post_request(
                f"{self.base_url}/instrument/timing",
                json={"resource_string": address, "min_command_interval_ms": milliseconds},
                headers=self._request_headers(),
                timeout=self._http_timeout_sec(),
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise InstrumentCommunicationError(
                instrument=address, message=f"Unable to register mandatory timing: {error}"
            ) from error
        self._minimum_interval_s = milliseconds / 1000

    def _status_byte_payload(self) -> dict[str, str | int]:
        """Build the native status-byte payload without a synthetic SCPI command."""
        return {
            "resource_string": self._explicit_address or self.instrument_address or "",
            "timeout_ms": max(1, int(self._timeout_sec * 1000)),
        }

    def _activate_explicit_address(self) -> bool:
        """Register an explicit resource URI without model discovery."""
        address = self._explicit_address
        if not address:
            return False
        try:
            response = self._post_request(
                f"{self.base_url}/add",
                json={"model_name": address},
                headers=self._request_headers(),
                timeout=self._http_timeout_sec(),
            )
            if response.status_code != 200:
                raise InstrumentConnectionError(
                    f"LAMB /add failed for explicit address {address}: "
                    f"{response.status_code} - {response.text}"
                )
            if response.text.strip() != address:
                raise InstrumentConnectionError(
                    f"LAMB /add did not confirm the exact configured resource {address!r}; "
                    "refusing to send commands."
                )
            self.instrument_address = address
            self._explicit_address_registered = True
            self._resource_acquired = True
            return True
        except httpx.RequestError as exc:
            raise InstrumentConnectionError(
                f"Network error during LAMB explicit-address activation: {exc}"
            ) from exc

    def _reactivate_after_missing_handle(self) -> bool:
        """Re-register a descriptor-backed resource after LAMB releases it.

        LAMB's close endpoint releases the shared server-side handle.  A bench
        opened from an explicit address still carries model/serial identity,
        so a subsequent operation can safely restore that handle through the
        same idempotent ``/add`` contract used by auto-connect.
        """

        if self._explicit_address:
            self.instrument_address = self._explicit_address
            self._explicit_address_registered = False
            self._resource_acquired = False
            return self._activate_explicit_address()

        if not self.model_name or not self.serial_number:
            lamb_logger.warning(
                "Refusing LAMB handle reactivation without model and serial identity: "
                "model=%r serial=%r",
                self.model_name,
                self.serial_number,
            )
            self.instrument_address = None
            self._auto_connect_performed = False
            return False
        self.instrument_address = None
        self._auto_connect_performed = False
        self._ensure_connected()
        return bool(self.instrument_address)

    @staticmethod
    def _is_missing_handle_response(response: httpx.Response) -> bool:
        """Return whether a 404 explicitly identifies a released instrument handle."""

        if response.status_code != 404:
            return False
        body = response.text.casefold()
        return any(
            marker in body
            for marker in (
                "instrument not found",
                "missing handle",
                "handle not found",
                "resource handle not found",
            )
        )

    def _post_request(self, url: str, *, json: dict[str, Any], **kwargs: Any) -> httpx.Response:
        """Send the canonical LAMB resource envelope without compatibility retries."""
        return self._get_client().post(url, json=json, **kwargs)

    def _post_operation(
        self,
        endpoint: str,
        cmd: str | None,
        *,
        accept: str = "application/json",
        include_read_termination: bool = False,
        query_delay_ms: int | None = None,
    ):
        """Post one operation, retrying once after a released-handle 404."""

        headers = self._request_headers(accept)

        # A command may cause the server to open or reactivate this resource.
        # Mark it before sending so close() can clean up even after a reply error.
        self._resource_acquired = True
        response = self._post_request(
            f"{self.base_url}{endpoint}",
            json=(
                self._instrument_payload(
                    cmd,
                    include_read_termination=include_read_termination,
                    query_delay_ms=query_delay_ms,
                )
            ),
            headers=headers,
            timeout=self._http_timeout_sec(),
        )
        if self._is_missing_handle_response(response) and self._reactivate_after_missing_handle():
            response = self._post_request(
                f"{self.base_url}{endpoint}",
                json=(
                    self._instrument_payload(
                        cmd,
                        include_read_termination=include_read_termination,
                        query_delay_ms=query_delay_ms,
                    )
                ),
                headers=headers,
                timeout=self._http_timeout_sec(),
            )
        return response

    def write(self, cmd: str) -> None:
        self._ensure_connected()
        lamb_logger.debug(f"WRITE to '{self.instrument_address}': {cmd}")
        try:
            response = self._post_operation("/instrument/write", cmd)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise InstrumentCommunicationError(
                f"Lamb server write failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise InstrumentCommunicationError(f"Network error during Lamb write: {e}") from e

    def query(self, cmd: str, delay: float | None = None) -> str:
        query_delay_ms = self._query_delay_ms(delay)
        if query_delay_ms is not None:
            self._ensure_query_delay_capability()
        self._ensure_connected()
        lamb_logger.debug(f"QUERY to '{self.instrument_address}': {cmd}")
        try:
            response = self._post_operation(
                "/instrument/query",
                cmd,
                include_read_termination=True,
                query_delay_ms=query_delay_ms,
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
        query_delay_ms = self._query_delay_ms(delay)
        if query_delay_ms is not None:
            self._ensure_query_delay_capability()
        self._ensure_connected()
        lamb_logger.debug(f"QUERY_RAW to '{self.instrument_address}': {cmd}")
        try:
            response = self._post_operation(
                "/instrument/query_raw",
                cmd,
                accept="application/octet-stream",
                query_delay_ms=query_delay_ms,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as e:
            raise InstrumentCommunicationError(
                f"Lamb server query_raw failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise InstrumentCommunicationError(f"Network error during Lamb query_raw: {e}") from e

    def prepare_read(self, *, raw: bool = False) -> None:
        """Negotiate no-write read support before acquisition setup commands."""
        self._ensure_server_capability("native_read")

    def read(self) -> str:
        """Read pending text without sending an instrument command."""
        self._ensure_server_capability("native_read")
        self._ensure_connected()
        try:
            response = self._post_operation("/instrument/read", None, include_read_termination=True)
            response.raise_for_status()
            return response.content.decode("utf-8").strip()
        except (httpx.HTTPError, UnicodeError) as error:
            raise InstrumentCommunicationError(
                instrument=self.instrument_address, message=f"Native read failed: {error}"
            ) from error

    def read_raw(self) -> bytes:
        """Read pending bytes without a command or text EOS."""
        self._ensure_server_capability("native_read")
        self._ensure_connected()
        response = self._post_operation(
            "/instrument/read_raw", None, accept="application/octet-stream"
        )
        try:
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as error:
            raise InstrumentCommunicationError(
                instrument=self.instrument_address, message=f"Native raw read failed: {error}"
            ) from error

    def read_status_byte(self) -> int:
        """Read the VISA service-request status register through LAMB."""
        self._ensure_connected()
        try:
            response = self._post_operation("/instrument/read_status_byte", None)
            response.raise_for_status()
            try:
                payload = response.json()
            except (TypeError, ValueError) as e:
                raise InstrumentCommunicationError(
                    "Lamb server read_status_byte returned invalid JSON; expected "
                    "an object containing integer 'status_byte'."
                ) from e
            status_byte = payload.get("status_byte") if isinstance(payload, dict) else None
            if (
                isinstance(status_byte, bool)
                or not isinstance(status_byte, int)
                or not 0 <= status_byte <= 0xFF
            ):
                raise InstrumentCommunicationError(
                    "Lamb server read_status_byte returned an invalid response; expected "
                    "an integer 'status_byte' in the range 0..255."
                )
            return status_byte
        except httpx.HTTPStatusError as e:
            raise InstrumentCommunicationError(
                f"Lamb server read_status_byte failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise InstrumentCommunicationError(
                f"Network error during Lamb read_status_byte: {e}"
            ) from e

    def close(self) -> None:
        address = self._explicit_address or self.instrument_address
        try:
            if address and self._resource_acquired:
                response = self._post_request(
                    f"{self.base_url}/instrument/close",
                    # Deployed LAMB servers deserialize close requests using
                    # the same instrument-operation envelope as query/write;
                    # the command is ignored by the close handler but remains
                    # required by that wire schema.
                    json={"resource_string": address, "command": ""},
                    headers=self._request_headers(),
                    timeout=self._http_timeout_sec(),
                )
                # Closing an already-removed handle is idempotent from the
                # client's perspective; every other server failure remains
                # visible.
                if response.status_code != 404:
                    response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise InstrumentCommunicationError(
                f"Lamb server close failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise InstrumentCommunicationError(f"Network error during Lamb close: {e}") from e
        finally:
            self.disconnect()
            self.instrument_address = None
            self._auto_connect_performed = False
            self._explicit_address_registered = False
            self._resource_acquired = False

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
