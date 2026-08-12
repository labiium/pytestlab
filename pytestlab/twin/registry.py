"""Small local registry for characterized digital twins."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .base import TwinIdentity
from .scope import CharacterizedScopeTwin


@dataclass
class TwinRegistry:
    """In-memory registry keyed by model/profile/serial identity.

    The registry is intentionally small and file-format-free for now. It gives
    user code a stable place to collect characterized twins without introducing
    a persistence dependency or implying an issuing-lab trust store.
    """

    _twins: dict[str, CharacterizedScopeTwin]

    def __init__(self, twins: Iterable[CharacterizedScopeTwin] = ()) -> None:
        self._twins = {}
        for twin in twins:
            self.register(twin)

    def register(self, twin: CharacterizedScopeTwin) -> str:
        key = identity_key(twin.identity)
        self._twins[key] = twin
        return key

    def get(self, identity: TwinIdentity) -> CharacterizedScopeTwin | None:
        return self._twins.get(identity_key(identity))

    def by_model(self, model: str) -> list[CharacterizedScopeTwin]:
        return [twin for twin in self._twins.values() if twin.identity.model == model]

    def all(self) -> list[CharacterizedScopeTwin]:
        return list(self._twins.values())


def identity_key(identity: TwinIdentity) -> str:
    return "|".join(
        (
            identity.model,
            identity.serial_number or "",
            identity.profile_sha256 or "",
            identity.twin_id or "",
        )
    )
