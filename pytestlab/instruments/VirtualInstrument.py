from __future__ import annotations

import numpy as np

from ..config.virtual_instrument_config import VirtualInstrumentConfig
from .instrument import Instrument
from .operation_contract import OperationDescriptor


class VirtualInstrument(Instrument[VirtualInstrumentConfig]):
    """A virtual instrument designed for testing simulation features."""

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "voltage_control",
            required_aliases=("set_voltage", "measure_voltage"),
            parameters={
                "voltage": {"bindings": [{"alias": "set_voltage", "parameter": "voltage"}]}
            },
        ),
        OperationDescriptor(
            "current_control",
            required_aliases=("set_current", "measure_current"),
            parameters={
                "current": {"bindings": [{"alias": "set_current", "parameter": "current"}]}
            },
        ),
        OperationDescriptor(
            "trigger_state",
            required_aliases=("set_trigger_state", "get_trigger_state"),
            parameters={
                "state": {"bindings": [{"alias": "set_trigger_state", "parameter": "state"}]}
            },
        ),
        OperationDescriptor(
            "counter",
            required_aliases=("increment_counter", "decrement_counter", "get_counter"),
        ),
        OperationDescriptor(
            "status_message",
            required_aliases=("set_status_message", "get_status_message"),
            parameters={
                "message": {"bindings": [{"alias": "set_status_message", "parameter": "message"}]}
            },
        ),
        OperationDescriptor(
            "waveform_fetch", required_aliases=("fetch_waveform",), safety_class="read"
        ),
    )

    def set_voltage(self, voltage: float) -> None:
        """Sets the virtual voltage."""
        self._send_command(self.scpi_engine.build("set_voltage", voltage=voltage)[0])

    def set_current(self, current: float) -> None:
        """Sets the virtual current."""
        self._send_command(self.scpi_engine.build("set_current", current=current)[0])

    def measure_voltage(self) -> float:
        """Measures the virtual voltage."""
        response = self._query(self.scpi_engine.build("measure_voltage")[0])
        return float(response)

    def measure_current(self) -> float:
        """Measures the virtual current."""
        response = self._query(self.scpi_engine.build("measure_current")[0])
        return float(response)

    def set_trigger_state(self, state: str) -> None:
        """Sets the virtual trigger state."""
        self._send_command(self.scpi_engine.build("set_trigger_state", state=state)[0])

    def get_trigger_state(self) -> str:
        """Gets the virtual trigger state."""
        return self._query(self.scpi_engine.build("get_trigger_state")[0])

    def increment_counter(self) -> None:
        """Increments the internal counter."""
        self._send_command(self.scpi_engine.build("increment_counter")[0])

    def decrement_counter(self) -> None:
        """Decrements the internal counter."""
        self._send_command(self.scpi_engine.build("decrement_counter")[0])

    def get_counter(self) -> int:
        """Gets the current counter value."""
        response = self._query(self.scpi_engine.build("get_counter")[0])
        return int(float(response))

    def set_status_message(self, message: str) -> None:
        """Sets the status message."""
        self._send_command(self.scpi_engine.build("set_status_message", message=message)[0])

    def get_status_message(self) -> str:
        """Gets the status message."""
        return self._query(self.scpi_engine.build("get_status_message")[0])

    def dynamic_add(self, value: float) -> float:
        """Tests dynamic addition using py: expression."""
        response = self._query(self.scpi_engine.build("dynamic_add", value=value)[0])
        return float(response)

    def dynamic_random(self) -> int:
        """Tests dynamic random number generation using lambda: expression."""
        response = self._query(self.scpi_engine.build("dynamic_random")[0])
        return int(response)

    def push_error(self) -> None:
        """Pushes a custom error to the queue."""
        self._send_command(self.scpi_engine.build("push_error")[0])

    def check_error(self) -> tuple[int, str]:
        """Checks for a custom error."""
        response = self._query(self.scpi_engine.build("check_error")[0])
        code_str, msg_str = response.split(",", 1)
        return int(code_str), msg_str.strip().strip('"')

    def fetch_waveform(self) -> np.ndarray:
        """Fetches a binary waveform."""
        response = self._query_raw(self.scpi_engine.build("fetch_waveform")[0])
        return np.frombuffer(response, dtype=np.uint8)
