from __future__ import annotations
import sqlite3, pathlib, json, datetime, hashlib
from typing import TypedDict, Any

from .tsa import LinkedTSA


class AuditRecord(TypedDict):
    id:      int
    ts:      str
    actor:   str
    action:  str
    envelope_sha: str
    tsa_idx: int


class AuditTrail:
    """
    Small append-only audit database (SQLite) with SHA-256 hash-link via TSA.
    """

    def __init__(self, db_path: pathlib.Path | str, tsa: LinkedTSA):
        self._db = sqlite3.connect(db_path)
        self._tsa = tsa
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts TEXT, actor TEXT, action TEXT, envelope_sha TEXT, tsa_idx INT)"
            )

    # ------------------------------------------------------------------ #
    def append(self, actor: str, action: str, envelope: dict[str, Any]) -> int:
        tok = self._tsa.seal(envelope["sha"])
        with self._db:
            cur = self._db.execute(
                "INSERT INTO log (ts, actor, action, envelope_sha, tsa_idx) "
                "VALUES (?, ?, ?, ?, ?)",
                (tok["ts"], actor, action, envelope["sha"], tok["idx"]),
            )
            return int(cur.lastrowid)

    # ------------------------------------------------------------------ #
    def verify(self) -> bool:
        return self._tsa.verify_chain()
