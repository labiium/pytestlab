"""Profile-defined message framing and transactions shared by capabilities.

This layer has no instrument model or command vocabulary. Profiles describe
termination, acknowledgement grammar and timing; capability adapters supply
the already-rendered command.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from threading import RLock
from typing import Any

from .errors import InstrumentConfigurationError


def _seconds(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite, non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite, non-negative number")
    return result


class ProfileResponseError(RuntimeError):
    """A required response failed the profile's acknowledgement grammar."""


@dataclass
class _ResourceTiming:
    lock: Any = field(default_factory=RLock)
    minimum: float = 0.0
    completed: float | None = None


_RESOURCE_TIMING: dict[tuple[str, str, str], _ResourceTiming] = {}
_RESOURCE_TIMING_LOCK = RLock()


class ProfileTransport:
    """Serialize one profile's message transactions with declared wire rules."""

    def __init__(self, io: Any, spec: Mapping[str, Any]) -> None:
        self.io = io
        if "command_pacing_s" in spec:
            raise ValueError("command_pacing_s was removed; use min_command_interval_s")
        self.min_command_interval_s = _seconds(
            spec.get("min_command_interval_s", 0), "min_command_interval_s"
        )
        address = getattr(io, "instrument_address", None) or getattr(io, "address", None)
        if isinstance(address, str) and address:
            key = (
                type(io).__module__ + "." + type(io).__qualname__,
                str(getattr(io, "base_url", "local")),
                address.strip().upper(),
            )
            with _RESOURCE_TIMING_LOCK:
                self._timing = _RESOURCE_TIMING.setdefault(key, _ResourceTiming())
        else:
            self._timing = _ResourceTiming()
        with self._timing.lock:
            self._timing.minimum = max(self._timing.minimum, self.min_command_interval_s)
        self._policy_registered = False
        delay = spec.get("query_delay_s")
        self.query_delay_s = None if delay is None else _seconds(delay, "query_delay_s")
        self.success_prefix = spec.get("success_prefix")
        self.success_token = spec.get("success_token")
        pattern = spec.get("success_pattern")
        self.success_pattern = re.compile(pattern) if pattern is not None else None
        message_io = spec.get("message_io", {})
        if not isinstance(message_io, Mapping):
            raise ValueError("profile message_io must be a mapping")
        unknown = set(message_io) - {"read_termination", "write_termination"}
        if unknown:
            raise ValueError(f"Unknown profile message_io settings: {sorted(unknown)}")
        self.message_io = dict(message_io)
        for key in ("read_termination", "write_termination"):
            if key in spec:
                self.message_io[key] = spec[key]
        termination = self.message_io.get("read_termination")
        if termination is not None and not isinstance(termination, str):
            raise ValueError("profile message_io.read_termination must be a string or null")
        write_termination = self.message_io.get("write_termination")
        if write_termination is not None and (
            not isinstance(write_termination, str)
            or write_termination not in ("", "\n", "\r", "\r\n")
        ):
            raise ValueError(
                "profile message_io.write_termination must be null, empty, LF, CR, or CRLF"
            )

    @property
    def lock(self) -> Any:
        return self._timing.lock

    def __getattr__(self, name: str) -> Any:
        return getattr(self.io, name)

    def _register_policy(self) -> None:
        if self._policy_registered:
            return
        setter = getattr(self.io, "set_min_command_interval", None)
        minimum = self._timing.minimum
        if minimum and callable(setter):
            setter(minimum)
        self._policy_registered = True

    def connect(self) -> None:
        with self.lock:
            self._configure_message_io()
            self._register_policy()
            self.io.connect()

    def _configure_message_io(self, *, write_only: bool = False) -> None:
        keys = ("write_termination",) if write_only else ("write_termination", "read_termination")
        for key in keys:
            if key in self.message_io:
                setter = getattr(self.io, f"set_{key}", None)
                if not callable(setter):
                    raise InstrumentConfigurationError(
                        "profile", f"backend cannot configure {key.replace('_', ' ')}"
                    )
                setter(self.message_io[key])

    def disconnect(self) -> None:
        self.io.disconnect()

    def close(self) -> None:
        self.io.close()

    def set_timeout(self, timeout_ms: int) -> None:
        self.io.set_timeout(timeout_ms)

    def get_timeout(self) -> int:
        return self.io.get_timeout()

    def set_read_termination(self, value: str | None) -> None:
        self.message_io["read_termination"] = value
        self.io.set_read_termination(value)

    def _perform(self, operation: Callable[[], Any]) -> Any:
        with self.lock:
            getter, setter = (
                getattr(self.io, "get_timeout", None),
                getattr(self.io, "set_timeout", None),
            )
            original = getter() if callable(getter) else None
            budget = (
                original / 1000
                if isinstance(original, (int, float))
                and not isinstance(original, bool)
                and original > 0
                else None
            )
            deadline = time.monotonic() + budget if budget is not None else None

            def pause(seconds: float) -> None:
                if not seconds:
                    return
                if deadline is not None and seconds >= deadline - time.monotonic():
                    raise TimeoutError("Profile timing exceeds the remaining command budget.")
                time.sleep(seconds)

            self._configure_message_io(write_only=True)
            self._register_policy()
            if self._timing.completed is not None:
                pause(max(0.0, self._timing.minimum - (time.monotonic() - self._timing.completed)))
            changed_timeout = False
            try:
                if deadline is not None and callable(setter):
                    remaining = int((deadline - time.monotonic()) * 1000)
                    if remaining <= 0:
                        raise TimeoutError("Profile timing exhausted the command budget.")
                    if original is not None and remaining < original:
                        setter(remaining)
                        changed_timeout = True
                try:
                    return operation()
                finally:
                    self._timing.completed = time.monotonic()
            finally:
                if changed_timeout and callable(setter):
                    setter(original)

    def _delay(self, requested: float | None) -> float | None:
        if requested is None:
            return self.query_delay_s
        return max(self.query_delay_s or 0.0, _seconds(requested, "query delay"))

    def write(self, cmd: str) -> None:
        self.exchange(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        return self.exchange(cmd, expect_response=True, validate_success=False, delay=delay)

    def supports_read(self) -> bool:
        checker = getattr(self.io, "supports_read", None)
        return checker() is True if callable(checker) else callable(getattr(self.io, "read", None))

    def supports_read_raw(self) -> bool:
        checker = getattr(self.io, "supports_read_raw", None)
        return (
            checker() is True if callable(checker) else callable(getattr(self.io, "read_raw", None))
        )

    def read(self) -> str:
        if not self.supports_read():
            raise NotImplementedError("Backend does not support reads without a command.")
        return self._perform(lambda: self.io.read()).strip()

    def read_raw(self) -> bytes:
        if not self.supports_read_raw():
            raise NotImplementedError("Backend does not support raw reads without a command.")
        return self._perform(self.io.read_raw)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        value = self._delay(delay)
        return self._perform(lambda: self.io.query_raw(cmd, delay=value))

    def expects_response(self, spec: Mapping[str, Any] | None = None) -> bool:
        setting = (spec or {}).get("expect_response")
        if setting is not None:
            if not isinstance(setting, bool):
                raise ValueError("expect_response must be a boolean")
            return setting
        return any(
            value is not None
            for value in (
                self.success_prefix,
                self.success_token,
                self.success_pattern,
            )
        )

    def exchange(
        self,
        command: str,
        *,
        expect_response: bool = False,
        validate_success: bool = True,
        delay: float | None = None,
    ) -> str:
        value = self._delay(delay)

        def perform() -> str:
            if not expect_response:
                self.io.write(command)
                return ""
            response = str(
                self.io.query(command) if value is None else self.io.query(command, delay=value)
            ).strip()
            valid = bool(response)
            if validate_success:
                if self.success_prefix is not None:
                    valid = valid and response.startswith(str(self.success_prefix))
                if self.success_token is not None:
                    valid = valid and response.split()[0] == str(self.success_token)
                if self.success_pattern is not None:
                    valid = valid and self.success_pattern.fullmatch(response) is not None
            if not valid:
                raise ProfileResponseError(f"profile_error_response: {response!r}")
            return response

        return self._perform(perform)

    def supports_native_status_byte(self) -> bool:
        checker = getattr(self.io, "supports_native_status_byte", None)
        if callable(checker):
            return checker() is True
        return callable(getattr(self.io, "read_status_byte", None))

    def read_status_byte(self) -> int:
        if not self.supports_native_status_byte():
            raise NotImplementedError("backend does not provide native status-byte reads")
        return self._perform(self.io.read_status_byte)
