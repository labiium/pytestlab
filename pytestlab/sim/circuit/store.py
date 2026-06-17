from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredArtifact:
    content_hash: str
    path: Path
    created_at: float


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, namespace: str, payload: bytes, *, suffix: str = "bin") -> StoredArtifact:
        digest = hashlib.sha256(payload).hexdigest()
        content_hash = f"sha256:{digest}"
        target_dir = self.root / namespace
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{digest}.{suffix}"
        if not path.exists():
            path.write_bytes(payload)
        return StoredArtifact(content_hash=content_hash, path=path, created_at=time.time())

    def put_text(self, namespace: str, text: str, *, suffix: str = "txt") -> StoredArtifact:
        return self.put_bytes(namespace, text.encode("utf-8"), suffix=suffix)

    def put_json(self, namespace: str, payload: Any, *, suffix: str = "json") -> StoredArtifact:
        data = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
        return self.put_bytes(namespace, data, suffix=suffix)

    def get_bytes(self, namespace: str, content_hash: str) -> bytes:
        algo, _, digest = content_hash.partition(":")
        if algo != "sha256" or not digest:
            raise ValueError("content_hash must be sha256:<hex>")
        path = self.root / namespace / f"{digest}.bin"
        if not path.exists():
            raise FileNotFoundError(path)
        return path.read_bytes()

    def get_text(self, namespace: str, content_hash: str) -> str:
        return self.get_bytes(namespace, content_hash).decode("utf-8")

    def get_json(self, namespace: str, content_hash: str) -> Any:
        return json.loads(self.get_text(namespace, content_hash))
