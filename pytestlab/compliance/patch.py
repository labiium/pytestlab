from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone

from .._log import get_logger
from .signature import Signer
from .tsa import LinkedTSA
from .audit import AuditTrail

_LOG = get_logger("compliance.patch")

def apply_patches(homedir):
    """Applies monkey patches to core PyTestLab classes for compliance features.

    This function dynamically modifies key classes at runtime to add cryptographic
    signing and audit trail capabilities. It should be called once at the
    beginning of a session where compliance is required.

    The patches perform the following actions:
    1.  **`MeasurementResult`**:
        -   Wraps the original class to automatically create a signed envelope
            for every measurement result upon instantiation.
        -   The envelope contains the result's metadata and a hash of its values.
        -   The creation of this signed result is recorded in the audit trail.
        -   Extends the `save` method to also write the signed envelope to a
            separate JSON file.

    2.  **`MeasurementDatabase`**:
        -   Wraps the `store_measurement` method to also save the signed
            envelope of the measurement result into a separate
            `measurement_envelopes` table in the database.

    Args:
        homedir: The home directory path where compliance-related files
                 (HSM keys, TSA file, audit database) are stored.
    """
    _SIGNER = Signer(homedir / "hsm")
    _TSA = LinkedTSA(homedir / "tsa.json")
    _TRAIL = AuditTrail(homedir / "audit.sqlite", _TSA)

    # Patch MeasurementResult
    from ..experiments import results as _results_mod
    _OriginalMR = _results_mod.MeasurementResult

    class _SignedResult(_OriginalMR):
        def __init__(self, *a, **k):
            """Initializes the result and immediately creates the compliance envelope."""
            super().__init__(*a, **k)
            # Create a payload with essential metadata from the measurement result.
            payload = {
                "instrument": self.instrument,
                "measurement_type": self.measurement_type,
                "units": self.units,
                "values_sha256": hashlib.sha256(
                    str(self.values).encode()
                ).hexdigest(),
                "timestamp": self.timestamp,
            }
            # Sign the payload and create the full envelope.
            self.envelope = _SIGNER.sign(payload) | {"payload": payload}
            # Create a PROV-O compliant provenance record for the measurement.
            self.prov = {
                "entity": {
                    f"ex:{self.envelope['sha']}": {
                        "prov:type": "ex:MeasurementResult",
                        "prov:label": self.measurement_type,
                        "prov:value": payload["values_sha256"],
                        "prov:generatedAtTime": datetime.fromtimestamp(
                            self.timestamp, timezone.utc
                        ).isoformat().replace('+00:00', 'Z'),
                    }
                }
            }
            # Record the creation of this signed result in the audit trail.
            _TRAIL.append(
                actor="pytestlab",
                action="create_result",
                envelope=self.envelope,
            )

        def save(self, path: str) -> None:
            """Saves the measurement data and its corresponding compliance envelope."""
            super().save(path)
            # Save the envelope to a separate file with a '.env.json' extension.
            with open(f"{path}.env.json", "w", encoding="utf-8") as fh:
                json.dump(self.envelope, fh, indent=2)

    _results_mod.MeasurementResult = _SignedResult
    
    # Also patch the top-level pytestlab namespace to ensure the patched class is used.
    import pytestlab
    pytestlab.MeasurementResult = _SignedResult
    _LOG.info("MeasurementResult patched with compliance envelope.")

    # Patch MeasurementDatabase
    from ..experiments.database import MeasurementDatabase as _MDB
    _ORIG_STORE = _MDB.store_measurement

    def _store_with_env(self: _MDB, codename, meas, **kw):
        """A wrapper around the original store_measurement to also save the envelope."""
        # Call the original method to store the primary measurement data.
        ck = _ORIG_STORE(self, codename, meas, **kw)
        # Now, store the compliance envelope in a separate table.
        with self._get_connection() as conn:
            # Ensure the envelopes table exists.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS measurement_envelopes "
                "(codename TEXT PRIMARY KEY, envelope_json TEXT)"
            )
            # Insert or replace the envelope for the given measurement codename.
            conn.execute(
                "INSERT OR REPLACE INTO measurement_envelopes VALUES (?, ?)",
                (ck, json.dumps(meas.envelope)),
            )
        return ck

    _MDB.store_measurement = _store_with_env
    _LOG.info("Database patched: envelopes persisted in measurement_envelopes.")