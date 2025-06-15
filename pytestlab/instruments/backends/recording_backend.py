import logging
import time
from pathlib import Path

import yaml

LOGGER = logging.getLogger(__name__)


class RecordingBackend:
    """A backend that records interactions to a simulation profile."""

    def __init__(self, backend, output_path=None):
        self.backend = backend
        self.output_path = output_path
        self.log = []
        self.start_time = time.monotonic()

    def write(self, command: str):
        """Write a command to the instrument and log it."""
        self.log.append({"type": "write", "command": command.strip()})
        self.backend.write(command)

    def query(self, command: str) -> str:
        """Send a query to the instrument, log it, and return the response."""
        response = self.backend.query(command)
        self.log.append(
            {"type": "query", "command": command.strip(), "response": response.strip()}
        )
        return response

    def read(self) -> str:
        """Read from the instrument and log it."""
        response = self.backend.read()
        self.log.append({"type": "read", "response": response.strip()})
        return response

    def close(self):
        """Close the backend and write the simulation profile."""
        self.backend.close()
        self.generate_profile()

    def generate_profile(self):
        """Generate the YAML simulation profile from the log."""
        profile = {"simulation": self.log}
        if self.output_path:
            output_file = Path(self.output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w") as f:
                yaml.dump(profile, f, sort_keys=False)
            LOGGER.info(f"Simulation profile saved to {self.output_path}")
        else:
            # In a real scenario, this would go to a user cache directory.
            # For now, let's just print it if no path is provided.
            print(yaml.dump(profile, sort_keys=False))

    def __getattr__(self, name):
        """Delegate other attributes to the wrapped backend."""
        return getattr(self.backend, name)