from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any
from typing import Generic
from typing import Protocol
from typing import TypeVar
from typing import runtime_checkable

from .._log import get_logger
from ..config.device_config import DeviceConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentConnectionError

ConfigType = TypeVar("ConfigType", bound=DeviceConfig)


class DeviceBackend(Protocol):
    """Lifecycle contract shared by every PyTestLab device backend."""

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def close(self) -> None: ...


class DeviceIO(DeviceBackend, Protocol):
    """Synchronous raw-command backend for SCPI-like devices."""

    def write(self, cmd: str) -> None: ...

    def query(self, cmd: str, delay: float | None = None) -> str: ...

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes: ...

    def set_timeout(self, timeout_ms: int) -> None: ...

    def get_timeout(self) -> int: ...


@runtime_checkable
class StatusByteReader(Protocol):
    """Optional transport capability for native VISA status-byte reads."""

    def read_status_byte(self) -> int: ...


@runtime_checkable
class MessageTerminationIO(Protocol):
    """Optional transport capability for configuring text read termination."""

    def set_read_termination(self, value: str | None) -> None: ...


@dataclass(frozen=True)
class _BackendFactory:
    """Pending allocation, distinct from an actual (possibly callable) backend."""

    build: Callable[[], DeviceBackend]


class Device(Generic[ConfigType]):
    """Base class for arbitrary automatable lab devices."""

    config: ConfigType
    _command_log: list[dict[str, Any]]
    _logger: Any

    def __init__(
        self, config: ConfigType, backend: DeviceBackend | _BackendFactory, **_: Any
    ) -> None:
        if not isinstance(config, DeviceConfig):
            raise TypeError(
                f"{self.__class__.__name__} expects a DeviceConfig-compatible object, "
                f"got {type(config).__name__}."
            )
        self.config = config
        self._backend_lock = RLock()
        self._backend_source = backend
        self._backend_connected = False
        self._command_log = []
        logger_name = getattr(config, "model", self.__class__.__name__)
        self._logger = get_logger(logger_name)
        self._logger.info("Device '%s': Initialized.", logger_name)

    @property
    def _backend(self) -> DeviceBackend:
        """Return the real backend, allocating it only when first accessed."""
        with self._backend_lock:
            if isinstance(self._backend_source, _BackendFactory):
                self._backend_source = self._backend_source.build()
            return self._backend_source

    @_backend.setter
    def _backend(self, backend: DeviceBackend) -> None:
        # Recording/replay callers own the previous backend; replacement must
        # not close an object that the replacement may itself wrap.
        with self._backend_lock:
            self._backend_source = backend

    def connect_backend(self) -> None:
        """Open the device backend if it is not already connected.

        This method remains public for backwards compatibility and explicit
        lifecycle control, but normal user code should not need to call it:
        PyTestLab connects lazily before the first backend operation and
        Bench.open() connects configured devices during bench initialization.
        """
        with self._backend_lock:
            if self._backend_connected:
                return
            logger_name = getattr(self.config, "model", self.__class__.__name__)
            backend = None
            try:
                backend = self._backend
                backend.connect()
                self._backend_connected = True
                self._logger.info("Device '%s': Backend connected.", logger_name)
            except Exception as exc:
                self._logger.error("Device '%s': Failed to connect backend: %s", logger_name, exc)
                # Never access the property after a failed allocation: doing so
                # would retry the factory while handling its original failure.
                if backend is not None:
                    try:
                        backend.disconnect()
                    except Exception as disconnect_exc:
                        self._logger.error(
                            "Device '%s': Error disconnecting backend after failed connect: %s",
                            logger_name,
                            disconnect_exc,
                        )
                raise InstrumentConnectionError(
                    instrument=logger_name, message=f"Failed to connect backend: {exc}"
                ) from exc

    def _ensure_backend_connected(self) -> None:
        """Connect lazily so user code never has to call connect_backend()."""
        if not self._backend_connected:
            self.connect_backend()

    def close(self) -> None:
        with self._backend_lock:
            if not isinstance(self._backend_source, _BackendFactory):
                self._backend_source.close()
            self._backend_connected = False

    def write(self, cmd: str) -> None:
        self._ensure_backend_connected()
        writer = getattr(self._backend, "write", None)
        if not callable(writer):
            raise NotImplementedError(
                f"Backend {type(self._backend).__name__} does not support raw write()."
            )
        writer(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        self._ensure_backend_connected()
        query = getattr(self._backend, "query", None)
        if not callable(query):
            raise NotImplementedError(
                f"Backend {type(self._backend).__name__} does not support raw query()."
            )
        return query(cmd, delay=delay)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        self._ensure_backend_connected()
        query_raw = getattr(self._backend, "query_raw", None)
        if not callable(query_raw):
            raise NotImplementedError(
                f"Backend {type(self._backend).__name__} does not support raw query_raw()."
            )
        return query_raw(cmd, delay=delay)

    @property
    def is_simulated(self) -> bool:
        """Report the actual backend's simulation contract, not a YAML intent flag."""
        return getattr(self._backend, "is_simulated", False) is True

    def supports_read(self) -> bool:
        checker = getattr(self._backend, "supports_read", None)
        return (
            checker() is True
            if callable(checker)
            else callable(getattr(self._backend, "read", None))
        )

    def supports_read_raw(self) -> bool:
        checker = getattr(self._backend, "supports_read_raw", None)
        return (
            checker() is True
            if callable(checker)
            else callable(getattr(self._backend, "read_raw", None))
        )

    def read(self) -> str:
        """Read pending text data without sending an instrument command."""
        if not self.supports_read():
            raise InstrumentConfigurationError(
                self.config.model, "Backend does not support reads without a command."
            )
        self._ensure_backend_connected()
        reader = getattr(self._backend, "read", None)
        assert callable(reader)
        return reader()

    def read_raw(self) -> bytes:
        """Read pending binary data without sending an instrument command."""
        if not self.supports_read_raw():
            raise InstrumentConfigurationError(
                self.config.model, "Backend does not support raw reads without a command."
            )
        self._ensure_backend_connected()
        reader = getattr(self._backend, "read_raw", None)
        assert callable(reader)
        return reader()

    def supports_native_status_byte(self) -> bool:
        """Report native status-byte support without connecting or sending I/O."""
        capability = getattr(self._backend, "supports_native_status_byte", None)
        if callable(capability):
            return bool(capability())
        return callable(getattr(self._backend, "read_status_byte", None))

    def read_status_byte(self) -> int:
        """Read a backend-native status byte without issuing a protocol query."""
        if not self.supports_native_status_byte():
            raise InstrumentConfigurationError(
                getattr(self.config, "model", type(self).__name__),
                "The selected backend does not provide native status-byte reading.",
            )
        self._ensure_backend_connected()
        reader = getattr(self._backend, "read_status_byte", None)
        assert callable(reader)
        value = reader()
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFF:
            raise InstrumentCommunicationError(
                instrument=getattr(self.config, "model", type(self).__name__),
                message="Backend returned an invalid status byte; expected an integer from 0 to 255.",
            )
        return value
