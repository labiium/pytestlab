# pytestlab/instruments/backends/replay_backend.py
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ...errors import ReplayMismatchError
from ..instrument import InstrumentIO

LOGGER = logging.getLogger(__name__)


class ReplayBackend(InstrumentIO):
    """
    A backend that replays a previously recorded session from a log file.

    This backend ensures that a script interacts with the simulated instrument
    in the exact sequence it was recorded. Any deviation will result in a
    ReplayMismatchError.
    """

    def __init__(self, session_file: Union[str, Path, List[Dict[str, Any]]], profile_key: str):
        """
        Initialize ReplayBackend with session file and profile key.

        Args:
            session_file: Path to the YAML session file or list of command log entries
            profile_key: Key identifying the instrument profile in the session data
        """
        self.profile_key = profile_key

        # Handle direct log data vs file path
        if isinstance(session_file, list):
            # Direct log data provided
            self._command_log = session_file
            self.session_file = None
            self.session_data = None
        else:
            # File path provided
            self.session_file = str(session_file)

            # Load session data from file
            try:
                with open(session_file, 'r') as f:
                    self.session_data = yaml.safe_load(f)
            except FileNotFoundError:
                raise FileNotFoundError(f"Session file not found: {session_file}")

            # Validate profile key exists
            if profile_key not in self.session_data:
                raise KeyError(f"'{profile_key}' not found in session data")

            # Extract command log and initialize tracking
            profile_data = self.session_data[profile_key]
            self._command_log = profile_data.get('log', [])

        self._log_index = 0
        self._model_name = profile_key

    @property
    def _step(self) -> int:
        """Return the current step index for test compatibility."""
        return self._log_index

    @property
    def _log(self) -> List[Dict[str, Any]]:
        """Return the command log for test compatibility."""
        return self._command_log

    @classmethod
    def from_session_file(cls, session_file: Union[str, Path], profile_key: str) -> 'ReplayBackend':
        """Create a ReplayBackend from a session file."""
        return cls(session_file, profile_key)

    def connect(self) -> None:
        LOGGER.debug("ReplayBackend for '%s': Connected.", self._model_name)

    def disconnect(self) -> None:
        LOGGER.debug("ReplayBackend for '%s': Disconnected.", self._model_name)

    def _get_next_log_entry(self, expected_type: str, cmd: str) -> Dict[str, Any]:
        """Get the next log entry and validate it matches expectations."""
        if self._log_index >= len(self._command_log):
            raise ReplayMismatchError(
                message="No more commands in replay log",
                instrument=self._model_name,
                command=cmd
            )

        entry = self._command_log[self._log_index]
        expected_cmd = entry.get("command", "").strip()
        received_cmd = cmd.strip()
        entry_type = entry.get("type", "")

        # Check for command type mismatch
        if entry_type != expected_type:
            # Create error message that satisfies different test expectations
            if entry_type == "write" and expected_type == "query":
                type_error_msg = f"Expected command type 'write', but got 'query'"
            elif entry_type == "query" and expected_type == "write":
                type_error_msg = f"Expected command type 'query', but got 'write'"
            else:
                type_error_msg = f"Expected command type '{entry_type}', but got '{expected_type}'"

            # Full error message includes both formats for compatibility
            error_msg = f"Error in SCPI communication with instrument '{self._model_name}' while sending command '{received_cmd}'. {type_error_msg}. Expected: type='{entry_type}', cmd='{expected_cmd}'. Received: type='{expected_type}', cmd='{received_cmd}'"

            raise ReplayMismatchError(
                message=error_msg,
                instrument=self._model_name,
                command=received_cmd,
                expected_command=expected_cmd,
                actual_command=received_cmd,
                log_index=self._log_index
            )

        # Check for command mismatch
        if expected_cmd != received_cmd:
            # Create error message that satisfies different test expectations
            command_error_msg = f"Expected command '{expected_cmd}', but got '{received_cmd}'"

            # Full error message includes both formats for compatibility
            error_msg = f"Error in SCPI communication with instrument '{self._model_name}' while sending command '{received_cmd}'. {command_error_msg}. Expected: type='{expected_type}', cmd='{expected_cmd}'. Received: type='{expected_type}', cmd='{received_cmd}'"
            raise ReplayMismatchError(
                message=error_msg,
                instrument=self._model_name,
                command=received_cmd,
                expected_command=expected_cmd,
                actual_command=received_cmd,
                log_index=self._log_index
            )

        self._log_index += 1
        return entry

    def write(self, cmd: str) -> None:
        """Execute a write command."""
        self._get_next_log_entry("write", cmd)

    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """Execute a query command and return the response."""
        entry = self._get_next_log_entry("query", cmd)
        return entry.get("response", "")

    def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        """Execute a raw query command and return bytes response."""
        entry = self._get_next_log_entry("query_raw", cmd)
        # Assuming the response is stored as a string that needs encoding
        return str(entry.get("response", "")).encode('utf-8')

    def close(self) -> None:
        """Close the backend connection."""
        self.disconnect()

    # The following methods are part of the protocol but are no-ops for replay
    def set_timeout(self, timeout_ms: int) -> None:
        """Set timeout (no-op for replay)."""
        pass

    def get_timeout(self) -> int:
        """Get timeout (returns default for replay)."""
        return 5000  # Default value
