from __future__ import annotations
from .instrument import Instrument
from ..config.virtual_instrument_config import VirtualInstrumentConfig
import numpy as np

class VirtualInstrument(Instrument[VirtualInstrumentConfig]):
    """A virtual instrument designed for testing simulation features."""

    def set_voltage(self, voltage: float) -> None:
        """Sets the virtual voltage."""
        self._send_command(f"SET:VOLT {voltage}")

    def set_current(self, current: float) -> None:
        """Sets the virtual current."""
        self._send_command(f"SET:CURR {current}")

    def measure_voltage(self) -> float:
        """Measures the virtual voltage."""
        response = self._query("MEAS:VOLT?")
        return float(response)

    def measure_current(self) -> float:
        """Measures the virtual current."""
        response = self._query("MEAS:CURR?")
        return float(response)

    def set_trigger_state(self, state: str) -> None:
        """Sets the virtual trigger state."""
        self._send_command(f"TRIG:STATE {state}")

    def get_trigger_state(self) -> str:
        """Gets the virtual trigger state."""
        return self._query("TRIG:STATE?")

    def increment_counter(self) -> None:
        """Increments the internal counter."""
        self._send_command("COUNT:INC")

    def decrement_counter(self) -> None:
        """Decrements the internal counter."""
        self._send_command("COUNT:DEC")

    def get_counter(self) -> int:
        """Gets the current counter value."""
        response = self._query("COUNT?")
        return int(float(response))

    def set_status_message(self, message: str) -> None:
        """Sets the status message."""
        self._send_command(f"STATUS:MSG {message}")

    def get_status_message(self) -> str:
        """Gets the status message."""
        return self._query("STATUS:MSG?")

    def dynamic_add(self, value: float) -> float:
        """Tests dynamic addition using py: expression."""
        response = self._query(f"DYNAMIC:ADD {value}")
        return float(response)

    def dynamic_random(self) -> int:
        """Tests dynamic random number generation using lambda: expression."""
        response = self._query("DYNAMIC:RAND?")
        return int(response)

    def push_error(self) -> None:
        """Pushes a custom error to the queue."""
        self._send_command("ERROR:PUSH")

    def check_error(self) -> tuple[int, str]:
        """Checks for a custom error."""
        response = self._query("ERROR:CHECK?")
        code_str, msg_str = response.split(',', 1)
        return int(code_str), msg_str.strip().strip('"')

    def fetch_waveform(self) -> np.ndarray:
        """Fetches a binary waveform."""
        response = self._query_raw("FETCH:WAV?")
        return np.frombuffer(response, dtype=np.uint8)