# pytestlab/instruments/backends/replay_backend.py
import logging
from typing import Any, Dict, List, Optional

from ...errors import InstrumentCommunicationError
from ..instrument import AsyncInstrumentIO

LOGGER = logging.getLogger(__name__)


class ReplayMismatchError(InstrumentCommunicationError):
    """Raised when a command during replay does not match the recorded log."""


class ReplayBackend(AsyncInstrumentIO):
    """
    A backend that replays a previously recorded session from a log file.

    This backend ensures that a script interacts with the simulated instrument
    in the exact sequence it was recorded. Any deviation will result in a
    ReplayMismatchError.
    """

    def __init__(self, session_log: List[Dict[str, Any]], model_name: str):
        self._log = session_log
        self._model_name = model_name
        self._step = 0

    def connect(self) -> None:
        LOGGER.debug(f"ReplayBackend for '{self._model_name}': Connected.")

    def disconnect(self) -> None:
        LOGGER.debug(f"ReplayBackend for '{self._model_name}': Disconnected.")

    def _get_next_log_entry(self, expected_type: str, command: str) -> Dict[str, Any]:
        with self._lock:
            if self._step >= len(self._log):
                raise ReplayMismatchError(
                    f"Replay for '{self._model_name}' ended, but received unexpected command: '{command}'"
                )

            entry = self._log[self._step]
            cmd_in_log = entry.get("command", "").strip()
            cmd_received = command.strip()

            if entry.get("type") != expected_type or cmd_in_log != cmd_received:
                raise ReplayMismatchError(
                    f"Replay mismatch for '{self._model_name}' at step {self._step}.\n"
                    f"  Expected: type='{entry.get('type')}', cmd='{cmd_in_log}'\n"
                    f"  Received: type='{expected_type}', cmd='{cmd_received}'"
                )

            self._step += 1
            return entry

    def write(self, command: str) -> None:
        self._get_next_log_entry("write", command)

    def query(self, command: str, delay: Optional[float] = None) -> str:
        entry = self._get_next_log_entry("query", command)
        return entry.get("response", "")

    def query_raw(self, command: str, delay: Optional[float] = None) -> bytes:
        entry = self._get_next_log_entry("query_raw", command)
        # Assuming the response is stored as a base64 string or similar if not directly in YAML
        # For this implementation, we'll assume it's a simple string that needs encoding.
        # A more robust solution might use base64 encoding in the YAML.
        return str(entry.get("response", "")).encode('utf-8')

    def close(self) -> None:
        self.disconnect()

    # The following methods are part of the protocol but are no-ops for replay
    def set_timeout(self, timeout_ms: int) -> None:
        pass

    def get_timeout(self) -> int:
        return 5000  # Default value
