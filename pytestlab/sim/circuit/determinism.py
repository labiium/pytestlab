from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np


def seed_from_context(
    *,
    base_seed: int,
    instrument_id: str,
    kind: str,
    state: dict[str, Any] | None = None,
) -> int:
    payload = {
        "base_seed": int(base_seed),
        "instrument_id": instrument_id,
        "kind": kind,
        "state": state or {},
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return int(digest[:8], 16)


def make_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(int(seed) & 0xFFFFFFFF)
