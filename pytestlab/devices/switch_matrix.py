from __future__ import annotations

from typing import Any

from ..config.bench_config import RouteEntry
from ..config.switch_matrix_config import SwitchMatrixConfig
from .base import Device
from .base import DeviceIO


class SwitchMatrixDevice(Device[SwitchMatrixConfig]):
    """Active switching device with validated dry-run route support."""

    def __init__(self, config: SwitchMatrixConfig, backend: DeviceIO):
        super().__init__(config, backend)
        self._active_route: str | None = None

    def describe_route(self, name: str, route: RouteEntry) -> str:
        connections = "; ".join(
            f"{connection.from_endpoint}->{connection.to}"
            for connection in route.connects
        )
        return f"{name}: {connections}"

    def validate_route(self, route: RouteEntry, *, name: str | None = None) -> list[list[str]]:
        route_terminals = {
            endpoint
            for connection in route.connects
            for endpoint in (connection.from_endpoint, connection.to)
        }
        self.config.validate_route_terminals(name, route_terminals)
        return [self.config.validate_path(connection.path) for connection in route.connects]

    def apply_route(self, name: str, route: RouteEntry) -> None:
        """Apply a previously validated route through the backend.

        The backend command format is intentionally simple and deterministic so
        fake backends can assert behavior without vendor-specific SCPI.
        """

        resolved_paths = self.validate_route(route, name=name)
        if route.exclusive_group is not None or any(
            name in route_names for route_names in self.config.exclusive_groups.values()
        ):
            self.close_all()
        for resolved in resolved_paths:
            self.write(f"ROUTE:CLOSE {'/'.join(resolved)}")
        if route.settling_time_s is not None:
            self.write(f"ROUTE:SETTLE {route.settling_time_s:g}")
        self.write(f"ROUTE:NAME {name}")
        self._active_route = name

    def open_route(self, route: RouteEntry, *, name: str | None = None) -> None:
        for resolved in self.validate_route(route, name=name):
            self.write(f"ROUTE:OPEN {'/'.join(resolved)}")

    def close_all(self) -> None:
        self.write("ROUTE:OPEN:ALL")

    def route_state(self) -> dict[str, Any]:
        return {
            "terminals": list(self.config.terminals),
            "channels": list(self.config.channels),
            "aliases": dict(self.config.aliases),
            "active_route": self._active_route,
        }
