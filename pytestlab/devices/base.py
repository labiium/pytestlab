from __future__ import annotations

from typing import Any
from typing import Generic
from typing import Protocol
from typing import TypeVar

from .._log import get_logger
from ..config.device_config import DeviceConfig
from ..errors import InstrumentConnectionError

ConfigType = TypeVar("ConfigType", bound=DeviceConfig)


class DeviceIO(Protocol):
    """Synchronous communication backend protocol for automatable lab devices."""

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def write(self, cmd: str) -> None: ...

    def query(self, cmd: str, delay: float | None = None) -> str: ...

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes: ...

    def close(self) -> None: ...

    def set_timeout(self, timeout_ms: int) -> None: ...

    def get_timeout(self) -> int: ...


class Device(Generic[ConfigType]):
    """Base class for arbitrary automatable lab devices."""

    config: ConfigType
    _backend: DeviceIO
    _command_log: list[dict[str, Any]]
    _logger: Any

    def __init__(self, config: ConfigType, backend: DeviceIO, **_: Any) -> None:
        if not isinstance(config, DeviceConfig):
            raise TypeError(
                f"{self.__class__.__name__} expects a DeviceConfig-compatible object, "
                f"got {type(config).__name__}."
            )
        self.config = config
        self._backend = backend
        self._backend_connected = False
        self._command_log = []
        logger_name = getattr(config, "model", self.__class__.__name__)
        self._logger = get_logger(logger_name)
        self._logger.info(
            "Device '%s': Initializing with backend '%s'.",
            logger_name,
            type(backend).__name__,
        )

    def connect_backend(self) -> None:
        """Open the device backend if it is not already connected.

        This method remains public for backwards compatibility and explicit
        lifecycle control, but normal user code should not need to call it:
        PyTestLab connects lazily before the first backend operation and
        Bench.open() connects configured devices during bench initialization.
        """
        if self._backend_connected:
            return

        logger_name = getattr(self.config, "model", self.__class__.__name__)
        try:
            self._backend.connect()
            self._backend_connected = True
            self._logger.info("Device '%s': Backend connected.", logger_name)
        except Exception as exc:
            self._logger.error("Device '%s': Failed to connect backend: %s", logger_name, exc)
            if hasattr(self._backend, "disconnect"):
                try:
                    self._backend.disconnect()
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
        self._backend.close()
        self._backend_connected = False

    def write(self, cmd: str) -> None:
        self._ensure_backend_connected()
        self._backend.write(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        self._ensure_backend_connected()
        return self._backend.query(cmd, delay=delay)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        self._ensure_backend_connected()
        return self._backend.query_raw(cmd, delay=delay)
