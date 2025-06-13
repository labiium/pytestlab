from __future__ import annotations
import base64, hashlib, json, pathlib
from datetime import datetime, timezone
from typing import TypedDict, Any

from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend


class Envelope(TypedDict):
    sha: str
    sig: str
    pub: str
    alg: str
    ts:  str


class Signer:
    """
    Tiny wrapper around ECDSA-P256 – keys are generated once under
    ~/.pytestlab/hsm/private.pem
    """

    def __init__(self, hsm_dir: pathlib.Path):
        self._priv_path = pathlib.Path(hsm_dir).expanduser() / "private.pem"
        self._priv_path.parent.mkdir(exist_ok=True, parents=True)
        if not self._priv_path.exists():
            self._generate()

        with open(self._priv_path, "rb") as fh:
            self._priv = serialization.load_pem_private_key(
                fh.read(), password=None, backend=default_backend()
            )
        self._pub_b = self._priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    # ------------------------------------------------------------------ #
    def _generate(self) -> None:
        priv = ec.generate_private_key(ec.SECP256R1(), default_backend())
        pem = priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        with open(self._priv_path, "wb") as fh:
            fh.write(pem)

    # ------------------------------------------------------------------ #
    def sign(self, payload: dict[str, Any]) -> Envelope:
        raw = json.dumps(payload, sort_keys=True).encode()
        digest = hashlib.sha256(raw).digest()
        sig = self._priv.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return {
            "sha": hashlib.sha256(raw).hexdigest(),
            "sig": base64.b64encode(sig).decode(),
            "pub": self._pub_b,
            "alg": "ECDSA-P256-SHA256",
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def verify(payload: dict[str, Any], env: Envelope) -> bool:
        from cryptography.hazmat.primitives import serialization

        raw = json.dumps(payload, sort_keys=True).encode()
        if hashlib.sha256(raw).hexdigest() != env["sha"]:
            return False
        pub = serialization.load_pem_public_key(
            env["pub"].encode(), backend=default_backend()
        )
        try:
            pub.verify(
                base64.b64decode(env["sig"]),
                hashlib.sha256(raw).digest(),
                ec.ECDSA(utils.Prehashed(hashes.SHA256())),
            )
            return True
        except Exception:  # noqa: BLE001
            return False
