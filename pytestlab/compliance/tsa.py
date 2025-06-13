from __future__ import annotations
import hashlib, json, pathlib, time
from datetime import datetime, timezone
from typing import TypedDict, List


class LinkedToken(TypedDict):
    idx: int
    ts:  str
    sha_prev: str
    sha_data: str
    sha_cum:  str


class LinkedTSA:
    """
    Minimal ISO 18014-3 Linked Time-Stamp Authority.
    Stores the chain in *tsa.json* under ~/.pytestlab
    """

    def __init__(self, path: pathlib.Path):
        self._path = pathlib.Path(path)
        if self._path.exists():
            self._chain: List[LinkedToken] = json.loads(self._path.read_text())
        else:
            self._chain = []

    # ------------------------------------------------------------------ #
    def seal(self, data_sha: str) -> LinkedToken:
        prev = self._chain[-1]["sha_cum"] if self._chain else "0"*64
        idx  = len(self._chain)
        now  = datetime.now(timezone.utc).isoformat()
        cum  = hashlib.sha256(f"{idx}|{data_sha}|{prev}|{now}".encode()).hexdigest()
        tok: LinkedToken = dict(
            idx=idx, ts=now, sha_prev=prev, sha_data=data_sha, sha_cum=cum
        )
        self._chain.append(tok)
        self._path.write_text(json.dumps(self._chain, indent=2))
        return tok

    # ------------------------------------------------------------------ #
    def verify_chain(self) -> bool:
        prev = "0"*64
        for t in self._chain:
            exp = hashlib.sha256(
                f"{t['idx']}|{t['sha_data']}|{prev}|{t['ts']}".encode()
            ).hexdigest()
            if exp != t["sha_cum"]:
                return False
            prev = exp
        return True
