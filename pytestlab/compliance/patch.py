from __future__ import annotations

import json
import hashlib
from datetime import datetime

from .._log import get_logger
from .signature import Signer
from .tsa import LinkedTSA
from .audit import AuditTrail

_LOG = get_logger("compliance.patch")

def apply_patches(homedir):
    """
    Apply all compliance patches to PyTestLab.
    """
    _SIGNER = Signer(homedir / "hsm")
    _TSA = LinkedTSA(homedir / "tsa.json")
    _TRAIL = AuditTrail(homedir / "audit.sqlite", _TSA)

    # Patch MeasurementResult
    from ..experiments import results as _results_mod
    _OriginalMR = _results_mod.MeasurementResult

    class _SignedResult(_OriginalMR):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            payload = {
                "instrument": self.instrument,
                "measurement_type": self.measurement_type,
                "units": self.units,
                "values_sha256": hashlib.sha256(
                    str(self.values).encode()
                ).hexdigest(),
                "timestamp": self.timestamp,
            }
            self.envelope = _SIGNER.sign(payload) | {"payload": payload}
            self.prov = {
                "entity": {
                    f"ex:{self.envelope['sha']}": {
                        "prov:type": "ex:MeasurementResult",
                        "prov:label": self.measurement_type,
                        "prov:value": payload["values_sha256"],
                        "prov:generatedAtTime": datetime.utcfromtimestamp(
                            self.timestamp
                        ).isoformat() + "Z",
                    }
                }
            }
            _TRAIL.append(
                actor="pytestlab",
                action="create_result",
                envelope=self.envelope,
            )

        def save(self, path: str) -> None:
            super().save(path)
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
        ck = _ORIG_STORE(self, codename, meas, **kw)
        with self._get_connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS measurement_envelopes "
                "(codename TEXT PRIMARY KEY, envelope_json TEXT)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO measurement_envelopes VALUES (?, ?)",
                (ck, json.dumps(meas.envelope)),
            )
        return ck

    _MDB.store_measurement = _store_with_env
    _LOG.info("Database patched: envelopes persisted in measurement_envelopes.")