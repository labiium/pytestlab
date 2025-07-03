from __future__ import annotations
from .instrument import Instrument
from ..config.virtual_instrument_config import VirtualInstrumentConfig
import numpy as np

class VirtualInstrument(Instrument[VirtualInstrumentConfig]):
    """A virtual instrument designed for testing simulation features."""

    async def set_voltage(self, voltage: float) -> None:
        """Sets the virtual voltage."""
        await self._send_command(f"SET:VOLT {voltage}")

    async def set_current(self, current: float) -> None:
        """Sets the virtual current."""
        await self._send_command(f"SET:CURR {current}")

    async def measure_voltage(self) -> float:
        """Measures the virtual voltage."""
        response = await self._query("MEAS:VOLT?")
        return float(response)

    async def measure_current(self) -> float:
        """Measures the virtual current."""
        response = await self._query("MEAS:CURR?")
        return float(response)

    async def set_trigger_state(self, state: str) -> None:
        """Sets the virtual trigger state."""
        await self._send_command(f"TRIG:STATE {state}")

    async def get_trigger_state(self) -> str:
        """Gets the virtual trigger state."""
        return await self._query("TRIG:STATE?")

    async def increment_counter(self) -> None:
        """Increments the internal counter."""
        await self._send_command("COUNT:INC")

    async def decrement_counter(self) -> None:
        """Decrements the internal counter."""
        await self._send_command("COUNT:DEC")

    async def get_counter(self) -> int:
        """Gets the current counter value."""
        response = await self._query("COUNT?")
        return int(float(response))

    async def set_status_message(self, message: str) -> None:
        """Sets the status message."""
        await self._send_command(f"STATUS:MSG {message}")

    async def get_status_message(self) -> str:
        """Gets the status message."""
        return await self._query("STATUS:MSG?")

    async def dynamic_add(self, value: float) -> float:
        """Tests dynamic addition using py: expression."""
        response = await self._query(f"DYNAMIC:ADD {value}")
        return float(response)

    async def dynamic_random(self) -> int:
        """Tests dynamic random number generation using lambda: expression."""
        response = await self._query("DYNAMIC:RAND?")
        return int(response)

    async def push_error(self) -> None:
        """Pushes a custom error to the queue."""
        await self._send_command("ERROR:PUSH")

    async def check_error(self) -> tuple[int, str]:
        """Checks for a custom error."""
        response = await self._query("ERROR:CHECK?")
        code_str, msg_str = response.split(',', 1)
        return int(code_str), msg_str.strip().strip('"')

    async def fetch_waveform(self) -> np.ndarray:
        """Fetches a binary waveform."""
        response = await self._query_raw("FETCH:WAV?")
        return np.frombuffer(response, dtype=np.uint8)