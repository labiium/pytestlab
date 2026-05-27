from __future__ import annotations

from ...devices.base import DeviceIO
from ...devices.registry import BackendBuildContext


class CircuitSimBackend:
    """DeviceIO backend routing SCPI to pytestlab_sim.SimbenchScpiBackend."""

    def __init__(self, *, instrument_id: str, session, timeout_ms: int = 5_000):
        from pytestlab_sim.scpi import SimbenchScpiBackend

        self._inner = SimbenchScpiBackend(
            session=session,
            instrument_id=instrument_id,
            timeout_ms=timeout_ms,
        )

    def connect(self) -> None:
        self._inner.connect()

    def disconnect(self) -> None:
        self._inner.disconnect()

    def close(self) -> None:
        self._inner.close()

    def write(self, cmd: str) -> None:
        self._inner.write(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        return self._inner.query(cmd, delay)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return self._inner.query_raw(cmd, delay)

    def set_timeout(self, timeout_ms: int) -> None:
        self._inner.set_timeout(timeout_ms)

    def get_timeout(self) -> int:
        return self._inner.get_timeout()


def build_circuit_sim_backend(context: BackendBuildContext) -> DeviceIO:
    spec = context.backend_spec or {}
    session = context.sim_session
    if session is None:
        raise RuntimeError(
            "circuit_sim backend requires a shared Session; use Bench.open() with sim_circuit"
        )
    instrument_id = str(spec.get("instrument_id", context.config.model))
    return CircuitSimBackend(
        instrument_id=instrument_id,
        session=session,
        timeout_ms=context.timeout_ms,
    )
