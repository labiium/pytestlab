import asyncio
import logging
import re
import time
from pathlib import Path

import yaml

LOGGER = logging.getLogger(__name__)


class RecordingBackend:
    """A backend that records interactions to a simulation profile."""

    def __init__(self, backend, output_path=None, base_profile=None):
        self.backend = backend
        self.output_path = output_path
        self.base_profile = base_profile if base_profile is not None else {}
        self.log = []
        self.start_time = time.monotonic()

    async def write(self, command: str, *args, **kwargs):
        """Async write a command to the instrument and log it."""
        self.log.append({"type": "write", "command": command.strip()})
        if hasattr(self.backend, 'write') and callable(getattr(self.backend, 'write')):
            result = self.backend.write(command, *args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result
        raise NotImplementedError("Backend does not support write method.")

    async def query(self, command: str, *args, **kwargs):
        """Async query to the instrument, log it, and return the response."""
        if hasattr(self.backend, 'query') and callable(getattr(self.backend, 'query')):
            result = self.backend.query(command, *args, **kwargs)
            if asyncio.iscoroutine(result):
                response = await result
            else:
                response = result
            self.log.append({
                "type": "query",
                "command": command.strip(),
                "response": getattr(response, 'strip', lambda: response)()
            })
            return response
        raise NotImplementedError("Backend does not support query method.")

    async def query_raw(self, command: str, *args, **kwargs):
        """Async query to the instrument, log it, and return the response."""
        if hasattr(self.backend, 'query_raw') and callable(getattr(self.backend, 'query_raw')):
            result = self.backend.query_raw(command, *args, **kwargs)
            if asyncio.iscoroutine(result):
                response = await result
            else:
                response = result
            self.log.append({
                "type": "query_raw",
                "command": command.strip(),
                "response": response
            })
            return response
        raise NotImplementedError("Backend does not support query_raw method.")

    def read(self) -> str:
        """Read from the instrument and log it."""
        response = self.backend.read()
        self.log.append({"type": "read", "response": response.strip()})
        return response

    async def close(self):
        """Close the backend and write the simulation profile."""
        if hasattr(self.backend, 'close') and callable(getattr(self.backend, 'close')):
            result = self.backend.close()
            if asyncio.iscoroutine(result):
                await result
        print("DEBUG: Calling generate_profile from RecordingBackend.close()")
        self.generate_profile()

    def generate_profile(self):
        """Generate the YAML simulation profile from the log."""
        print(f"DEBUG: generate_profile called. Output path: {self.output_path}")
        scpi_map = {}
        for entry in self.log:
            if entry["type"] == "query":
                scpi_map[entry["command"]] = entry["response"]
            elif entry["type"] == "query_raw":
                command_slug = re.sub(r"[^a-zA-Z0-9]", "_", entry["command"])
                binary_filename = f"{command_slug}.bin"
                binary_filepath = Path(self.output_path).parent / binary_filename
                with open(binary_filepath, "wb") as f:
                    f.write(entry["response"])
                scpi_map[entry["command"]] = {"binary": binary_filename}
            elif entry["type"] == "write":
                # For writes, we record the command with an empty response,
                # which is suitable for commands that don't return a value.
                scpi_map[entry["command"]] = ""

        profile = self.base_profile
        if "simulation" not in profile:
            profile["simulation"] = {}
        profile["simulation"]["scpi"] = scpi_map
        print(f"DEBUG: Profile data to be written: {profile}")
        if self.output_path:
            try:
                output_file = Path(self.output_path)
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