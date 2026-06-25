# pytestlab/instruments/backends/session_recording_backend.py
import base64
import hashlib
import logging
import os
import time
from typing import Any

import yaml

from ..instrument import InstrumentIO

LOGGER = logging.getLogger(__name__)


class SessionRecordingBackend(InstrumentIO):
    """
    A backend wrapper that records all interactions into a session file.
    This is used by the `pytestlab replay record` command.
    """

    def __init__(
        self,
        original_backend: InstrumentIO,
        output_file_or_log: str | list[dict[str, Any]],
        profile_key: str | None = None,
    ):
        self.original_backend = original_backend
        # Predefine attributes for consistent typing
        self._command_log: list[dict[str, Any]] = []
        self.output_file: str | None = None

        # Handle both file output and direct log recording
        if isinstance(output_file_or_log, list):
            self._command_log = output_file_or_log
            self.output_file = None
        else:
            self.output_file = output_file_or_log
            self._command_log = []

        self.profile_key = profile_key
        self.start_time = time.monotonic()

    @property
    def backend(self) -> InstrumentIO:
        """Alias for original_backend for compatibility."""
        return self.original_backend

    def connect(self) -> None:
        self.original_backend.connect()

    def disconnect(self) -> None:
        self.original_backend.disconnect()

    def _log_event(self, event_data: dict[str, Any]):
        """Appends a timestamped event to the command log."""
        event_data["timestamp"] = time.monotonic() - self.start_time
        self._command_log.append(event_data)

    def write(self, cmd: str) -> None:
        self._log_event({"type": "write", "command": cmd.strip()})
        self.original_backend.write(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        # Handle the case where the underlying backend doesn't support delay parameter
        try:
            response = self.original_backend.query(cmd, delay=delay)
        except TypeError:
            # Fallback for backends that don't support delay parameter
            response = self.original_backend.query(cmd)

        self._log_event({"type": "query", "command": cmd.strip(), "response": response.strip()})
        return response

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        try:
            response = self.original_backend.query_raw(cmd, delay=delay)
        except TypeError:
            response = self.original_backend.query_raw(cmd)

        self._log_event(
            {
                "type": "query_raw",
                "command": cmd.strip(),
                "response_encoding": "base64",
                "response_base64": base64.b64encode(response).decode("ascii"),
                "response_sha256": hashlib.sha256(response).hexdigest(),
                "response_len": len(response),
            }
        )
        return response

    def save_session(self, profile_key: str):
        """Save the recorded session to the output file."""
        if self.output_file is None:
            # No file output configured, session is stored in the list
            return

        session_key = self.profile_key or profile_key
        session_data = {session_key: {"profile": profile_key, "log": self._command_log}}

        # Load existing session data if file exists
        existing_data: dict[str, Any] = {}
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file) as f:
                    existing_data = yaml.safe_load(f) or {}
            except Exception:
                # If file is corrupted or empty, start fresh
                existing_data = {}

        # Merge with existing data
        existing_data.update(session_data)

        # Create parent directory if it doesn't exist
        try:
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        except (OSError, PermissionError) as e:
            raise FileNotFoundError(f"Cannot create directory for {self.output_file}: {e}") from e

        # Write to file
        with open(self.output_file, "w") as f:
            yaml.dump(existing_data, f, default_flow_style=False)

    def close(self):
        # The file writing is now handled by save_session or CLI command
        self.original_backend.close()

    def set_timeout(self, timeout_ms: int) -> None:
        self.original_backend.set_timeout(timeout_ms)

    def get_timeout(self) -> int:
        return self.original_backend.get_timeout()
