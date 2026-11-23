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
            public_method="set_voltage",
        ),
        OperationDescriptor(
            "measure_voltage", public_method="measure_voltage", safety_class="read"
        ),
        OperationDescriptor(
            "current_control",
            public_method="set_current",
        ),
        OperationDescriptor(
            "measure_current", public_method="measure_current", safety_class="read"
        ),
        OperationDescriptor(
            "trigger_state",
            public_method="set_trigger_state",
        ),
        OperationDescriptor(
            "get_trigger_state", public_method="get_trigger_state", safety_class="read"
        ),
        OperationDescriptor(
            "counter",
            public_method="increment_counter",
        ),
        OperationDescriptor("decrement_counter", public_method="decrement_counter"),
        OperationDescriptor("get_counter", public_method="get_counter", safety_class="read"),
        OperationDescriptor(
            "status_message",
            public_method="set_status_message",
        ),
        OperationDescriptor(
            "get_status_message", public_method="get_status_message", safety_class="read"
        ),
        OperationDescriptor(
            "waveform_fetch",
            public_method="fetch_waveform",
            safety_class="read",
        ),
        OperationDescriptor("dynamic_add", public_method="dynamic_add"),
        OperationDescriptor("dynamic_random", public_method="dynamic_random", safety_class="read"),
        OperationDescriptor("push_error", public_method="push_error"),
        OperationDescriptor("check_error", public_method="check_error", safety_class="read"),
    )

    def set_voltage(self, voltage: float) -> None:
        """Sets the virtual voltage."""
        resolved = self._resolve_operation_parameter("voltage_control", "voltage", voltage)
        self._send_profile_alias("set_voltage", voltage=resolved.transport_value)

    def set_current(self, current: float) -> None:
        """Sets the virtual current."""
        resolved = self._resolve_operation_parameter("current_control", "current", current)
        self._send_profile_alias("set_current", current=resolved.transport_value)

    def measure_voltage(self) -> float:
        """Measures the virtual voltage."""
        response = self._query_profile_alias("measure_voltage")
        return float(response)

    def measure_current(self) -> float:
        """Measures the virtual current."""
        response = self._query_profile_alias("measure_current")
        return float(response)

    def set_trigger_state(self, state: str) -> None:
        """Sets the virtual trigger state."""
        resolved = self._resolve_operation_parameter("trigger_state", "state", state)
        self._send_profile_alias("set_trigger_state", state=resolved.transport_value)

    def get_trigger_state(self) -> str:
        """Gets the virtual trigger state."""
        return self._query_profile_alias("get_trigger_state")

    def increment_counter(self) -> None:
        """Increments the internal counter."""
        self._send_profile_alias("increment_counter")

    def decrement_counter(self) -> None:
        """Decrements the internal counter."""
        self._send_profile_alias("decrement_counter")

    def get_counter(self) -> int:
        """Gets the current counter value."""
        response = self._query_profile_alias("get_counter")
        return int(float(response))

    def set_status_message(self, message: str) -> None:
        """Sets the status message."""
        resolved = self._resolve_operation_parameter("status_message", "message", message)
        self._send_profile_alias("set_status_message", message=resolved.transport_value)

    def get_status_message(self) -> str:
        """Gets the status message."""
        return self._query_profile_alias("get_status_message")

    def dynamic_add(self, value: float) -> float:
        """Tests dynamic addition using py: expression."""
        response = self._query_profile_alias("dynamic_add", value=value)
        return float(response)

    def dynamic_random(self) -> int:
        """Tests dynamic random number generation using lambda: expression."""
        response = self._query_profile_alias("dynamic_random")
        return int(response)

    def push_error(self) -> None:
        """Pushes a custom error to the queue."""
        self._send_profile_alias("push_error")

    def check_error(self) -> tuple[int, str]:
        """Checks for a custom error."""
        response = self._query_profile_alias("check_error")
        code_str, msg_str = response.split(",", 1)
        return int(code_str), msg_str.strip().strip('"')

    def fetch_waveform(self) -> np.ndarray:
        """Fetches a binary waveform."""
        response = self._query_raw(self._build_profile_alias("fetch_waveform")[0])
        return np.frombuffer(response, dtype=np.uint8)
