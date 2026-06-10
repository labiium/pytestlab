from __future__ import annotations

import time
from typing import TYPE_CHECKING
from typing import Any

from ..errors import InstrumentCommunicationError

if TYPE_CHECKING:
    from .instrument import Instrument


class InstrumentCommandSession:
    """Transport and command-history helper for an Instrument instance."""

    def __init__(self, instrument: Instrument[Any]) -> None:
        self.instrument = instrument

    def send_command(self, command: str, skip_check: bool = False) -> None:
        instrument = self.instrument
        instrument._ensure_backend_connected()
        try:
            instrument._backend.write(command)
            if not skip_check:
                instrument._error_check()
            instrument._command_log.append(
                {"command": command, "success": True, "type": "write", "timestamp": time.time()}
            )
        except Exception as e:
            instrument._command_log.append(
                {"command": command, "success": False, "type": "write", "timestamp": time.time()}
            )
            raise InstrumentCommunicationError(
                instrument=instrument.config.model,
                command=command,
                message=f"Failed to send command: {e}",
            ) from e

    def query(self, query: str, delay: float | None = None, skip_check: bool = False) -> str:
        instrument = self.instrument
        instrument._ensure_backend_connected()
        try:
            response: str = instrument._backend.query(query, delay=delay)
            if not skip_check:
                instrument._error_check()
            instrument._command_log.append(
                {
                    "command": query,
                    "success": True,
                    "type": "query",
                    "timestamp": time.time(),
                    "response": response,
                    "delay": delay,
                }
            )
            return response.strip()
        except Exception as e:
            instrument._command_log.append(
                {
                    "command": query,
                    "success": False,
                    "type": "query",
                    "timestamp": time.time(),
                    "delay": delay,
                }
            )
            raise InstrumentCommunicationError(
                instrument=instrument.config.model,
                command=query,
                message=f"Failed to query instrument: {e}",
            ) from e

    def query_raw(self, query: str, delay: float | None = None) -> bytes:
        instrument = self.instrument
        instrument._ensure_backend_connected()
        try:
            response: bytes = instrument._backend.query_raw(query, delay=delay)
            instrument._command_log.append(
                {
                    "command": query,
                    "success": True,
                    "type": "query_raw",
                    "timestamp": time.time(),
                    "response_len": len(response),
                    "delay": delay,
                }
            )
            return response
        except Exception as e:
            instrument._command_log.append(
                {
                    "command": query,
                    "success": False,
                    "type": "query_raw",
                    "timestamp": time.time(),
                    "delay": delay,
                }
            )
            raise InstrumentCommunicationError(
                instrument=instrument.config.model,
                command=query,
                message=f"Failed to raw query instrument: {e}",
            ) from e

    def print_history(self) -> None:
        print("--- Command History ---")
        for i, entry in enumerate(self.instrument._command_log):
            ts_val = entry.get("timestamp", "N/A")
            ts_str = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_val))
                if isinstance(ts_val, float)
                else "Invalid Timestamp"
            )
            print(
                f"{i + 1}. [{ts_str}] Type: {entry.get('type', 'N/A')}, Success: {entry.get('success', 'N/A')}, Command: {entry.get('command', 'N/A')}"
            )
            if "response" in entry:
                print(f"   Response: {entry['response']}")
        print("--- End of History ---")
