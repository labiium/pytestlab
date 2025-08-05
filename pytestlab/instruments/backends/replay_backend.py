# pytestlab/instruments/backends/replay_backend.py
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ...errors import InstrumentCommunicationError, ReplayMismatchError
from ..instrument import InstrumentIO

LOGGER = logging.getLogger(__name__)


class ReplayBackend(InstrumentIO):
    """
    A backend that replays a previously recorded session from a log file.

    This backend ensures that a script interacts with the simulated instrument
    in the exact sequence it was recorded. Any deviation will result in a
    ReplayMismatchError.
    """

    def __init__(self, session_data: Union[List[Dict[str, Any]], str, Path], model_name: str):
        if isinstance(session_data, (str, Path)):
            # Load from file
            with open(session_data, 'r') as f:
                session_file_data = yaml.safe_load(f)
            self._log = session_file_data[model_name]['log']
        else:
            # Direct log data
            self._log = session_data
        self._model_name = model_name
        self._step = 0

    @classmethod
    def from_session_file(cls, session_file: Union[str, Path], model_name: str) -> 'ReplayBackend':
        """Create a ReplayBackend from a session file."""
        return cls(session_file, model_name)

    def connect(self) -> None:
        LOGGER.debug(f"ReplayBackend for '{self._model_name}': Connected.")

    def disconnect(self) -> None:
        LOGGER.debug(f"ReplayBackend for '{self._model_name}': Disconnected.")

    def _get_next_log_entry(self, expected_type: str, command: str) -> Dict[str, Any]:
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
