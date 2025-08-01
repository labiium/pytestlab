# pytestlab/instruments/backends/session_recording_backend.py
import logging
import time
from typing import List, Dict, Any

from ..instrument import AsyncInstrumentIO

LOGGER = logging.getLogger(__name__)


class SessionRecordingBackend(AsyncInstrumentIO):
    """
    A backend wrapper that records all interactions into a list of events.
    This is used by the `pytestlab replay record` command.
    """

    def __init__(self, original_backend: AsyncInstrumentIO, session_log: List[Dict[str, Any]]):
        self.original_backend = original_backend
        self.session_log = session_log
        self.start_time = time.monotonic()

    def connect(self) -> None:
        self.original_backend.connect()

    def disconnect(self) -> None:
        self.original_backend.disconnect()

    def _log_event(self, event_data: Dict[str, Any]):
        """Appends a timestamped event to the session log."""
        event_data["timestamp"] = time.monotonic() - self.start_time
        self.session_log.append(event_data)

    def write(self, command: str) -> None:
        self._log_event({"type": "write", "command": command.strip()})
        self.original_backend.write(command)

    def query(self, command: str, delay: float | None = None) -> str:
        response = self.original_backend.query(command, delay=delay)
        self._log_event({
            "type": "query",
            "command": command.strip(),
            "response": response.strip()
        })
        return response

    def query_raw(self, command: str, delay: float | None = None) -> bytes:
        response = self.original_backend.query_raw(command, delay=delay)
        # Note: Storing raw bytes in YAML is tricky. Consider base64 encoding for robustness.
        # For simplicity here, we'll decode assuming it's representable as a string.
        try:
            response_str = response.decode('utf-8', errors='ignore')
        except Exception:
            response_str = f"<binary data of length {len(response)}>"

        self._log_event({
            "type": "query_raw",
            "command": command.strip(),
            "response": response_str
        })
        return response

    def close(self):
        # The file writing is now handled by the CLI command. This just closes the wrapped backend.
        self.original_backend.close()

    def set_timeout(self, timeout_ms: int) -> None:
        self.original_backend.set_timeout(timeout_ms)

    def get_timeout(self) -> int:
        return self.original_backend.get_timeout()
