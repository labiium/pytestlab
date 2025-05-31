from typing import List, Dict, Any, Optional
from pytestlab.sim.backend import SimBackend

class SpyingSimBackend(SimBackend):
    """
    A SimBackend that records all SCPI commands sent to it.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_trace: List[Dict[str, Any]] = []

    def write(self, cmd: str) -> None:
        """
        Records the write command and then calls the parent's write method.
        """
        self.command_trace.append({"type": "write", "cmd": cmd.strip()})
        super().write(cmd)

    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """
        Records the query command and then calls the parent's query method.
        """
        self.command_trace.append({"type": "query", "cmd": cmd.strip()})
        # Ensure query also updates internal state if the command is state-changing
        # The base SimBackend's query should handle this if it calls _process_command
        response = super().query(cmd, delay)
        # If the query itself could be a state changing command that SimBackend handles
        # via _process_command, ensure it's called.
        # SimBackend.query calls _process_command if cmd is in self.command_map
        # and the command has no specific query_response.
        # If it has a query_response, _process_command is not called by query.
        # This might be a nuance to consider for state changes via queries.
        return response

    def clear_trace(self) -> None:
        """Clears the recorded command trace."""
        self.command_trace = []

    def get_trace(self) -> List[Dict[str, Any]]:
        """Returns the recorded command trace."""
        return self.command_trace