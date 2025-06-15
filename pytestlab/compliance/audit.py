from __future__ import annotations
import sqlite3, pathlib, json, datetime, hashlib
from typing import TypedDict, Any

from .tsa import LinkedTSA


class AuditRecord(TypedDict):
    """Represents a single record in the audit trail database."""
    id:      int
    ts:      str
    actor:   str
    action:  str
    envelope_sha: str
    tsa_idx: int


class AuditTrail:
    """Manages an append-only audit trail with cryptographic integrity.

    This class uses a simple SQLite database to store audit records. Each record
    is linked to a Time-Stamping Authority (TSA) token, which provides a
    verifiable, chronological, and tamper-evident chain of events. The integrity
    of the entire audit trail can be verified by checking the hash chain in the
    associated `LinkedTSA`.

    Attributes:
        _db: The connection to the SQLite database.
        _tsa: The `LinkedTSA` instance used for creating and verifying timestamps.
    """

    def __init__(self, db_path: pathlib.Path | str, tsa: LinkedTSA):
        """Initializes the AuditTrail and creates the log table if it doesn't exist.

        Args:
            db_path: The file path for the SQLite database.
            tsa: An initialized `LinkedTSA` object that will be used to seal
                 audit records.
        """
        self._db = sqlite3.connect(db_path)
        self._tsa = tsa
        # Ensure the 'log' table exists upon initialization.
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts TEXT, actor TEXT, action TEXT, envelope_sha TEXT, tsa_idx INT)"
            )

    # ------------------------------------------------------------------ #
    def append(self, actor: str, action: str, envelope: dict[str, Any]) -> int:
        """Appends a new record to the audit trail.

        This method creates a new audit record by first sealing the hash of the
        provided envelope with the TSA. It then inserts the record into the
        database, linking it to the generated timestamp token.

        Args:
            actor: The identifier of the entity performing the action.
            action: A description of the action being audited.
            envelope: A dictionary containing the data to be audited, which must
                      include a 'sha' key with the SHA-256 hash of the content.

        Returns:
            The ID of the newly created audit record.
        """
        # Seal the hash of the envelope content to get a timestamp token.
        tok = self._tsa.seal(envelope["sha"])
        with self._db:
            cur = self._db.execute(
                "INSERT INTO log (ts, actor, action, envelope_sha, tsa_idx) "
                "VALUES (?, ?, ?, ?, ?)",
                (tok["ts"], actor, action, envelope["sha"], tok["idx"]),
            )
            # Return the auto-incremented ID of the new record.
            return int(cur.lastrowid)

    # ------------------------------------------------------------------ #
    def verify(self) -> bool:
        """Verifies the integrity of the entire audit trail.

        This method delegates the verification to the `LinkedTSA` instance,
        which checks the cryptographic hash chain of all timestamp tokens.

        Returns:
            True if the chain is valid, False otherwise.
        """
        return self._tsa.verify_chain()
