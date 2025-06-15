from __future__ import annotations
import base64, hashlib, json, pathlib
from datetime import datetime, timezone
from typing import TypedDict, Any

from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend


class Envelope(TypedDict):
    """A dictionary representing a signed data envelope.

    This structure contains the digital signature and all the necessary
    metadata to verify the integrity and authenticity of a payload.

    Attributes:
        sha: The SHA-256 hash of the original payload.
        sig: The Base64-encoded ECDSA signature of the payload's hash.
        pub: The PEM-encoded public key corresponding to the signing key.
        alg: The signing algorithm used (e.g., "ECDSA-P256-SHA256").
        ts: The ISO 8601 timestamp of when the signature was created.
    """
    sha: str
    sig: str
    pub: str
    alg: str
    ts:  str


class Signer:
    """Handles cryptographic signing and verification using ECDSA.

    This class manages a persistent ECDSA private key (P-256). If a key does
    not exist in the specified directory, it will be generated automatically.
    The `Signer` can then be used to create signed `Envelope` objects for given
    payloads and to verify the integrity of payloads against their envelopes.

    Attributes:
        _priv_path: The file path to the private key.
        _priv: The loaded private key object from the `cryptography` library.
        _pub_b: The PEM-encoded public key as a string.
    """

    def __init__(self, hsm_dir: pathlib.Path):
        """Initializes the Signer and loads or generates the private key.

        Args:
            hsm_dir: The directory where the private key file (`private.pem`)
                     is stored. This path can be user-relative (e.g., `~/.myapp`).
        """
        self._priv_path = pathlib.Path(hsm_dir).expanduser() / "private.pem"
        self._priv_path.parent.mkdir(exist_ok=True, parents=True)
        # If the private key file doesn't exist, create it.
        if not self._priv_path.exists():
            self._generate()

        # Load the private key from the PEM file.
        with open(self._priv_path, "rb") as fh:
            self._priv = serialization.load_pem_private_key(
                fh.read(), password=None, backend=default_backend()
            )
        # Derive and store the corresponding public key in PEM format.
        self._pub_b = self._priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    # ------------------------------------------------------------------ #
    def _generate(self) -> None:
        """Generates a new ECDSA P-256 private key and saves it to disk."""
        priv = ec.generate_private_key(ec.SECP256R1(), default_backend())
        # Serialize the key to PEM format without encryption.
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(self._priv_path, "wb") as fh:
            fh.write(pem)

    # ------------------------------------------------------------------ #
    def sign(self, payload: dict[str, Any]) -> Envelope:
        """Signs a JSON payload and returns a compliance envelope.

        The payload is first canonicalized by sorting its keys and then hashed
        using SHA-256. The hash is then signed using the private key.

        Args:
            payload: A dictionary to be signed.

        Returns:
            An `Envelope` dictionary containing the signature and metadata.
        """
        # Canonicalize the payload to ensure a consistent hash.
        raw = json.dumps(payload, sort_keys=True).encode()
        digest = hashlib.sha256(raw).digest()
        # Sign the pre-computed hash.
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
        """Verifies a payload against its signed envelope.

        This static method performs two checks:
        1. It verifies that the SHA-256 hash of the payload matches the hash
           stored in the envelope.
        2. It uses the public key from the envelope to verify the signature
           against the payload's hash.

        Args:
            payload: The original payload dictionary.
            env: The `Envelope` associated with the payload.

        Returns:
            True if both the hash and the signature are valid, False otherwise.
        """
        from cryptography.hazmat.primitives import serialization

        # Canonicalize the payload to regenerate the hash for comparison.
        raw = json.dumps(payload, sort_keys=True).encode()
        # 1. Verify the payload hash matches the one in the envelope.
        if hashlib.sha256(raw).hexdigest() != env["sha"]:
            return False
        # Load the public key from the envelope.
        pub = serialization.load_pem_public_key(
            env["pub"].encode(), backend=default_backend()
        )
        try:
            # 2. Verify the cryptographic signature.
            pub.verify(
                base64.b64decode(env["sig"]),
                hashlib.sha256(raw).digest(),
                ec.ECDSA(utils.Prehashed(hashes.SHA256())),
            )
            return True
        except Exception:  # Broad exception to catch any verification error.
            return False
