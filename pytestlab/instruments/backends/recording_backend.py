import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)


class RecordingBackend:
    """A backend that records interactions to a simulation profile."""

    def __init__(
        self,
        backend: Any,
        output_path: str | Path | None = None,
        base_profile: dict[str, Any] | None = None,
    ):
        self.backend = backend
        self.output_path = output_path
        self.base_profile: dict[str, Any] = base_profile if base_profile is not None else {}
        self.log: list[dict[str, Any]] = []
        self.start_time = time.monotonic()

    def write(self, command: str, *args, **kwargs):
        """Write a command to the instrument and log it."""
        self.log.append({"type": "write", "command": command.strip()})
        if hasattr(self.backend, "write") and callable(self.backend.write):
            result = self.backend.write(command, *args, **kwargs)
            return result
        raise NotImplementedError("Backend does not support write method.")

    def query(self, command: str, *args, **kwargs):
        """Query to the instrument, log it, and return the response."""
        if hasattr(self.backend, "query") and callable(self.backend.query):
            response = self.backend.query(command, *args, **kwargs)
            self.log.append(
                {
                    "type": "query",
                    "command": command.strip(),
                    "response": getattr(response, "strip", lambda: response)(),
                }
            )
            return response
        raise NotImplementedError("Backend does not support query method.")

    def query_raw(self, command: str, *args, **kwargs):
        """Query to the instrument, log it, and return the response."""
        if hasattr(self.backend, "query_raw") and callable(self.backend.query_raw):
            response = self.backend.query_raw(command, *args, **kwargs)
            self.log.append({"type": "query_raw", "command": command.strip(), "response": response})
            return response
        raise NotImplementedError("Backend does not support query_raw method.")

    def read(self) -> str:
        """Read from the instrument and log it."""
        response_obj = self.backend.read()
        response_str = response_obj.strip() if hasattr(response_obj, "strip") else str(response_obj)
        self.log.append({"type": "read", "response": response_str})
        return response_str

    def close(self):
        """Close the backend and write the simulation profile."""
        if hasattr(self.backend, "close") and callable(self.backend.close):
            self.backend.close()
        print("DEBUG: Calling generate_profile from RecordingBackend.close()")
        self.generate_profile()

    def generate_profile(self):
        """Generate the YAML simulation profile from the log."""
        print(f"DEBUG: generate_profile called. Output path: {self.output_path}")
        output_path = Path(self.output_path) if self.output_path else None
        binary_root = output_path.parent if output_path else Path.cwd()
        scpi_map = {}
        for entry in self.log:
            entry_type = entry.get("type")
            if entry_type == "query":
                scpi_map[str(entry["command"])] = entry["response"]
            elif entry_type == "query_raw":
                command = str(entry["command"])
                command_slug = re.sub(r"[^a-zA-Z0-9]", "_", command)
                binary_filename = f"{command_slug}.bin"
                binary_filepath = binary_root / binary_filename
                with open(binary_filepath, "wb") as f:
                    response_obj = entry["response"]
                    if not isinstance(response_obj, bytes | bytearray):
                        raise TypeError("query_raw responses must be bytes-like to be recorded.")
                    f.write(response_obj)
                scpi_map[command] = {"binary": binary_filename}
            elif entry_type == "write":
                # For writes, we record the command with an empty response,
                # which is suitable for commands that don't return a value.
                scpi_map[str(entry["command"])] = ""

        profile = self.base_profile
        if "simulation" not in profile:
            profile["simulation"] = {}
        profile["simulation"]["scpi"] = scpi_map
        print(f"DEBUG: Profile data to be written: {profile}")
        if output_path:
            try:
                output_file = output_path
                print(f"DEBUG: Creating parent directory for {output_file}")
                output_file.parent.mkdir(parents=True, exist_ok=True)
                print(f"DEBUG: Writing to file {output_file}")
                with open(output_file, "w") as f:
                    yaml.dump(profile, f, sort_keys=False)
                print("DEBUG: File write complete.")
                LOGGER.info(f"Simulation profile saved to {self.output_path}")
            except Exception as e:
                print(f"DEBUG: ERROR in generate_profile: {e}")
        else:
            # In a real scenario, this would go to a user cache directory.
            # For now, let's just print it if no path is provided.
            print("DEBUG: No output path provided. Printing to stdout.")
            print(yaml.dump(profile, sort_keys=False))

    def __getattr__(self, name):
        """Delegate other attributes to the wrapped backend."""
        return getattr(self.backend, name)
