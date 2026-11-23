"""Generic profile-driven wafer-prober capability."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from typing import Any

from .motion import MotionResult
from .motion_profile import ProfileMotionBackend
from .motion_profile import ProfileMotionDevice

_PROBER_ACTIONS = ("move_absolute", "contact", "separate")


class GenericProberDevice(ProfileMotionDevice):
    """Profile-driven prober with native, typed auxiliary actions."""

    def _profile_backend(self) -> ProfileMotionBackend:
        backend = self._backend
        if not isinstance(backend, ProfileMotionBackend):
            raise TypeError("generic prober requires a ProfileMotionBackend")
        return backend

    @staticmethod
    def _require_bool(name: str, value: Any) -> bool:
        if type(value) is not bool:
            raise TypeError(f"{name} must be a bool")
        return value

    def _action(self, operation: str, *, wait: bool = False, **fields: Any) -> MotionResult:
        requested = dict(fields) if fields else None
        return self._issue(operation, fields=fields, requested=requested, wait=wait)

    def contact(self, *, wait: bool = False) -> MotionResult:
        """Move the probe into contact using the profile's native command."""

        return self._action("contact", wait=wait)

    def separate(self, *, wait: bool = False) -> MotionResult:
        """Separate the probe using the profile's native command."""

        return self._action("separate", wait=wait)

    def align(self, *, wait: bool = False) -> MotionResult:
        """Run a genuine profile-declared alignment action."""

        return self._action("align", wait=wait)

    def move_to_align(self, *, wait: bool = False) -> MotionResult:
        """Move to the profile's alignment-height/preset position."""

        return self._action("move_to_align", wait=wait)

    def move_to_load(self, *, wait: bool = False) -> MotionResult:
        """Move the prober to its load position."""

        return self._action("move_to_load", wait=wait)

    def set_vacuum(self, enabled: bool, *, wait: bool = False) -> MotionResult:
        """Set chuck vacuum; ``enabled`` must be an actual bool."""

        value = self._require_bool("enabled", enabled)
        return self._action("set_vacuum", enabled=value, wait=wait)

    def configure_chuck(
        self,
        overtravel: bool,
        auto_z: bool,
        interlock: bool,
        edge_sensor: bool,
        *,
        wait: bool = False,
    ) -> MotionResult:
        """Configure chuck interlocks with explicit safety booleans.

        ``interlock=True`` engages the interlock.  Passing ``False`` explicitly
        bypasses it; no implicit truthiness or integer coercion is accepted.
        All four values are checked before the backend can connect or actuate.
        """

        values = {
            "overtravel": self._require_bool("overtravel", overtravel),
            "auto_z": self._require_bool("auto_z", auto_z),
            "interlock": self._require_bool("interlock", interlock),
            "edge_sensor": self._require_bool("edge_sensor", edge_sensor),
        }
        return self._action("configure_chuck", wait=wait, **values)

    def _validate_readback_spec(self, query: str, label: str) -> None:
        backend = self._profile_backend()
        if not backend.has_query(query):
            raise NotImplementedError(f"{label} readback is not declared by the profile")
        response = backend.query_response_spec(query)
        response_type = str((response or {}).get("type", ""))
        if response_type not in {"state_map", "status_field"}:
            raise NotImplementedError(
                f"{label} readback requires an explicit state/status map in the profile"
            )
        if response_type == "state_map":
            mapping = (response or {}).get("values", (response or {}).get("map"))
        else:
            mapping = (response or {}).get("value_map", (response or {}).get("map"))
        if not isinstance(mapping, Mapping) or not mapping:
            raise NotImplementedError(
                f"{label} readback requires an explicit state/status map in the profile"
            )
        if query in {"settled", "vacuum_state"} and any(
            type(value) is not bool for value in mapping.values()
        ):
            raise NotImplementedError(f"{label} readback map values must be bool")
        if query == "contact_state":
            known = {"contact", "contacted", "separate", "separated", "open"}
            for value in mapping.values():
                if type(value) is bool:
                    continue
                if not isinstance(value, str) or value.strip().lower() not in known:
                    raise NotImplementedError(
                        f"{label} readback map contains an unknown canonical state"
                    )

    def _explicit_readback(self, query: str, label: str) -> Any:
        self._validate_readback_spec(query, label)
        backend = self._profile_backend()
        self._ensure_backend_connected()
        return backend.motion_query(query)

    def get_contact_state(self) -> Any:
        """Read contact only when the profile declares a mapped query."""

        value = self._explicit_readback("contact_state", "contact state")
        if type(value) is bool:
            return value
        if isinstance(value, str) and value.strip().lower() in {
            "contact",
            "contacted",
            "separate",
            "separated",
            "open",
        }:
            return value
        raise ValueError(f"contact state readback is not canonical: {value!r}")

    def get_vacuum_state(self) -> bool:
        """Read vacuum only from an explicit map to boolean states."""

        value = self._explicit_readback("vacuum_state", "vacuum state")
        if type(value) is not bool:
            raise ValueError("vacuum readback must map to a bool")
        return value

    def get_settled_state(self) -> bool:
        """Read settled state only from an explicit mapped profile query."""

        value = self._explicit_readback("settled", "settled state")
        if not isinstance(value, bool):
            raise ValueError("settled readback must map to a bool")
        return value

    def settled(self) -> bool:
        """Compatibility alias for get_settled_state."""

        return self.get_settled_state()

    def preflight_recipe(self, required: Iterable[str] | None = None) -> tuple[str, ...]:
        """Validate a complete action/readback recipe before actuation.

        Omitting ``required`` checks the core move, contact, and separate
        recipe plus explicit mapped contact and settled readbacks. Passing an
        iterable checks those named capabilities; if it includes
        ``set_vacuum``, a mapped vacuum readback is also required. This
        checks declarations only, not the prober's physical state.
        """

        complete = required is None
        required_names = tuple(_PROBER_ACTIONS if complete else (str(name) for name in required))
        supports = self.get_capabilities().supports
        missing = tuple(name for name in required_names if name not in supports)
        if missing:
            raise NotImplementedError(
                f"prober recipe requires unsupported capabilities: {', '.join(missing)}"
            )
        if complete:
            # Validate every required query declaration before any readback
            # or connection. PA200 is acknowledgement-only and fails closed.
            self._validate_readback_spec("contact_state", "contact state")
            self._validate_readback_spec("settled", "settled state")
        elif "set_vacuum" in required_names:
            self._validate_readback_spec("vacuum_state", "vacuum state")
        return required_names


ProberDevice = GenericProberDevice

__all__ = ["GenericProberDevice", "ProberDevice"]
