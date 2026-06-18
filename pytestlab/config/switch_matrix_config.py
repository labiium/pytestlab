from __future__ import annotations

from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from .device_config import DeviceConfig
from .device_config import DeviceRole


class SwitchMatrixConfig(DeviceConfig):
    """Configuration for an active switch/routing device."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    device_type: str = Field("switch_matrix", frozen=True)
    role: DeviceRole = DeviceRole.SWITCHING
    terminals: list[str] = Field(default_factory=list, min_length=1)
    channels: list[str] = Field(default_factory=list, min_length=1)
    aliases: dict[str, str] = Field(default_factory=dict)
    allowed_routes: dict[str, list[str]] = Field(default_factory=dict)
    exclusive_groups: dict[str, list[str]] = Field(default_factory=dict)
    settling_time_s: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_switch_matrix_paths(self) -> SwitchMatrixConfig:
        if not self.terminals:
            raise ValueError("switch_matrix profiles must declare at least one terminal.")
        known_channels = set(self.channels)
        known_terminals = set(self.terminals)
        for alias, target in self.aliases.items():
            if target not in known_channels:
                raise ValueError(
                    f"switch_matrix alias '{alias}' targets unknown channel '{target}'."
                )
        for route_name, terminals in self.allowed_routes.items():
            unknown = [terminal for terminal in terminals if terminal not in known_terminals]
            if unknown:
                raise ValueError(
                    f"switch_matrix allowed_route '{route_name}' references unknown "
                    f"terminal(s): {', '.join(unknown)}."
                )
        return self

    def resolve_path_element(self, element: str) -> str:
        return self.aliases.get(element, element)

    def validate_path(self, path: list[str]) -> list[str]:
        known_channels = set(self.channels)
        resolved = [self.resolve_path_element(element) for element in path]
        unknown = [element for element in resolved if element not in known_channels]
        if unknown:
            allowed = ", ".join(sorted(known_channels | set(self.aliases)))
            raise ValueError(
                f"Unknown switch path element(s): {', '.join(unknown)}. "
                f"Known channels/aliases: {allowed}"
            )
        return resolved

    def validate_route_terminals(self, name: str | None, terminals: set[str]) -> None:
        unknown_terminals = sorted(terminals - set(self.terminals))
        if unknown_terminals:
            raise ValueError(
                "Route references terminal(s) not declared by switch_matrix profile: "
                f"{', '.join(unknown_terminals)}."
            )
        if not self.allowed_routes:
            return
        if name is None:
            raise ValueError(
                "Route name is required when switch_matrix allowed_routes is configured."
            )
        if name not in self.allowed_routes:
            allowed_names = ", ".join(sorted(self.allowed_routes))
            raise ValueError(
                f"Route '{name}' is not declared in allowed_routes. "
                f"Known route(s): {allowed_names}."
            )
        allowed_terminals = set(self.allowed_routes[name])
        disallowed = sorted(terminals - allowed_terminals)
        if disallowed:
            raise ValueError(
                f"Route '{name}' uses terminal(s) outside allowed_routes: {', '.join(disallowed)}."
            )
