from __future__ import annotations

import time
from typing import Any

from ..config.bench_config import RouteEntry
from ..config.switch_matrix_config import SwitchMatrixConfig
from ..switch_profile import ObservedRouteVerification
from ..switch_profile import ProfileSwitchBackend
from .base import Device
from .base import DeviceIO


class SwitchMatrixDevice(Device[SwitchMatrixConfig]):
    """Active switching device with validated dry-run route support."""

    def __init__(self, config: SwitchMatrixConfig, backend: DeviceIO):
        self._profile_backend = (
            ProfileSwitchBackend(backend, {**config.switch, **config.transport})
            if config.switch is not None
            else None
        )
        super().__init__(config, self._profile_backend or backend)
        self._active_route: str | None = None

    def _check_safety_context(self, safety_context: dict[str, Any] | None) -> None:
        if self._profile_backend is None:
            return
        missing = [
            key
            for key in self._profile_backend.requires_context
            if not safety_context or safety_context.get(key) is not True
        ]
        if missing:
            raise ValueError("switch operation requires safety context: " + ", ".join(missing))

    def describe_route(self, name: str, route: RouteEntry) -> str:
        connections = "; ".join(
            f"{connection.from_endpoint}->{connection.to}" for connection in route.connects
        )
        return f"{name}: {connections}"

    def validate_route(self, route: RouteEntry, *, name: str | None = None) -> list[list[str]]:
        route_terminals = {
            endpoint
            for connection in route.connects
            for endpoint in (connection.from_endpoint, connection.to)
        }
        self.config.validate_route_terminals(name, route_terminals)
        resolved = [self.config.validate_path(connection.path) for connection in route.connects]
        if self._profile_backend is not None:
            self._profile_backend.preflight(
                "connect", [channel for path in resolved for channel in path]
            )
        return resolved

    def preflight_route(
        self,
        route: RouteEntry,
        *,
        name: str | None = None,
        safety_context: dict[str, Any] | None = None,
        expected_connected: bool = True,
    ) -> list[list[str]]:
        """Validate route commands and verification capability without I/O."""
        resolved = self.validate_route(route, name=name)
        self._check_safety_context(safety_context)
        if self._profile_backend is not None:
            channels = [channel for path in resolved for channel in path]
            self._profile_backend.preflight("connect" if expected_connected else "open", channels)
            if route.exclusive_group is not None or any(
                name in route_names for route_names in self.config.exclusive_groups.values()
            ):
                self._profile_backend.command_for("clear")
            response = self._profile_backend.query_response_spec("connection_state")
            if not self._profile_backend.has_query("connection_state") or (
                response.get("type") != "state_map"
                or not isinstance(response.get("values", response.get("map")), dict)
                or not all(
                    type(value) is bool
                    for value in response.get("values", response.get("map", {})).values()
                )
            ):
                raise NotImplementedError(
                    "switch profile does not declare a boolean connection_state readback"
                )
        return resolved

    def verify_route(
        self,
        route: RouteEntry,
        *,
        name: str | None = None,
        expected_connected: bool = True,
    ) -> ObservedRouteVerification:
        """Return verification evidence only from an explicit state readback."""
        self.validate_route(route, name=name)
        if self._profile_backend is None:
            raise NotImplementedError("switch profile does not declare connection readback")
        with self._profile_backend.lock:
            return self._profile_backend.verify_route(
                name or "", expected_connected=expected_connected
            )

    def verify_open(
        self, route: RouteEntry, *, name: str | None = None
    ) -> ObservedRouteVerification:
        return self.verify_route(route, name=name, expected_connected=False)

    def preflight_recipe(
        self,
        route: RouteEntry,
        *,
        name: str | None = None,
        safety_context: dict[str, Any] | None = None,
    ) -> list[list[str]]:
        return self.preflight_route(
            route,
            name=name,
            safety_context=safety_context,
            expected_connected=True,
        )

    def identify_extended(self) -> str:
        if self._profile_backend is None or not self._profile_backend.has_query(
            "identify_extended"
        ):
            raise NotImplementedError("switch profile does not declare extended identity")
        self._ensure_backend_connected()
        with self._profile_backend.lock:
            return self._profile_backend.query_action("identify_extended")

    def get_pin_status(self, pin: int) -> str:
        if self._profile_backend is None or not self._profile_backend.has_query("pin_status"):
            raise NotImplementedError("switch profile does not declare pin status")
        self._ensure_backend_connected()
        with self._profile_backend.lock:
            return self._profile_backend.query_action("pin_status", pin=pin)

    def get_port_status(self, port: int) -> str:
        if self._profile_backend is None or not self._profile_backend.has_query("port_status"):
            raise NotImplementedError("switch profile does not declare port status")
        self._ensure_backend_connected()
        with self._profile_backend.lock:
            return self._profile_backend.query_action("port_status", port=port)

    def guard_pin(self, pin: int, safety_context: dict[str, Any] | None = None) -> None:
        if self._profile_backend is None:
            raise NotImplementedError("switch profile does not declare pin guard")
        self._check_safety_context(safety_context)
        command = self._profile_backend.command_for_fields("guard_pin", pin=pin)
        with self._profile_backend.lock:
            self._ensure_backend_connected()
            self._profile_backend.send_command(command)

    def apply_route(
        self,
        name: str,
        route: RouteEntry,
        *,
        safety_context: dict[str, Any] | None = None,
    ) -> None:
        """Apply a previously validated route through the backend.

        The backend command format is intentionally simple and deterministic so
        fake backends can assert behavior without vendor-specific SCPI.
        """

        resolved_paths = self.validate_route(route, name=name)
        self._check_safety_context(safety_context)
        profile_channels = [channel for path in resolved_paths for channel in path]
        if self._profile_backend is not None:
            with self._profile_backend.lock:
                self._profile_backend.preflight("connect", profile_channels)
                self._active_route = None
                if route.exclusive_group is not None or any(
                    name in route_names for route_names in self.config.exclusive_groups.values()
                ):
                    self.open_all(safety_context=safety_context)
                self._ensure_backend_connected()
                self._profile_backend.apply_route(profile_channels)
                settling = (
                    route.settling_time_s
                    if route.settling_time_s is not None
                    else self.config.settling_time_s
                )
                if settling:
                    time.sleep(settling)
                self._active_route = name
            return
        # Any state-changing write can leave the physical route partially
        # applied. Invalidate the local claim before the first write.
        self._active_route = None
        if route.exclusive_group is not None or any(
            name in route_names for route_names in self.config.exclusive_groups.values()
        ):
            self.open_all(safety_context=safety_context)
        for resolved in resolved_paths:
            self.write(f"ROUTE:CLOSE {'/'.join(resolved)}")
        if route.settling_time_s is not None:
            self.write(f"ROUTE:SETTLE {route.settling_time_s:g}")
        self.write(f"ROUTE:NAME {name}")
        self._active_route = name

    def open_route(
        self,
        route: RouteEntry,
        *,
        name: str | None = None,
        safety_context: dict[str, Any] | None = None,
    ) -> None:
        resolved_paths = self.validate_route(route, name=name)
        self._check_safety_context(safety_context)
        if self._profile_backend is not None:
            with self._profile_backend.lock:
                self._profile_backend.preflight(
                    "open", [channel for path in resolved_paths for channel in path]
                )
                self._active_route = None
                self._ensure_backend_connected()
                self._profile_backend.open_route(
                    [channel for path in resolved_paths for channel in path]
                )
            return
        self._active_route = None
        for resolved in resolved_paths:
            self.write(f"ROUTE:OPEN {'/'.join(resolved)}")

    def open_all(self, *, safety_context: dict[str, Any] | None = None) -> None:
        """Disconnect all routes without closing the device connection."""
        self._check_safety_context(safety_context)
        if self._profile_backend is not None:
            with self._profile_backend.lock:
                self._profile_backend.command_for("clear")
                self._active_route = None
                self._ensure_backend_connected()
                self._profile_backend.clear()
            return
        self._active_route = None
        self.write("ROUTE:OPEN:ALL")

    def identity(self) -> str:
        if self._profile_backend is None:
            raise NotImplementedError("switch profile does not declare identity")
        with self._profile_backend.lock:
            self._profile_backend.command_for("identity")
            self._ensure_backend_connected()
            return self._profile_backend.identity()

    id = identity

    def route_state(self) -> dict[str, Any]:
        return {
            "terminals": list(self.config.terminals),
            "channels": list(self.config.channels),
            "aliases": dict(self.config.aliases),
            "active_route": self._active_route,
        }
