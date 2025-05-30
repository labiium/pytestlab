#!/usr/bin/env python3
"""
advanced_demo.py – End-to-end showcase
======================================

* MeasurementSession with two parameters and two instruments
* Auto-generated experiment code on DB insert
* Rich DataFrame with scalar + vector columns
"""
from __future__ import annotations

import numpy as np

from pytestlab.measurements import Measurement
from pytestlab.experiments.database import MeasurementDatabase

# ─── Fake HW for demo (remove in real lab) ───────────────────────────
class DummyPSU:
    def set_voltage(self, *_): ...
    def output(self, *_): ...
    def close(self): ...

class DummyDMM:
    def measure(self, **_) -> "DummyRes":  # noqa: D401
        return DummyRes()
    def close(self): ...

class DummyRes:
    @property
    def values(self):  # noqa: D401
        return np.random.random()

from pytestlab.measurements import session as _ms  # pylint: disable=wrong-import-order
_ms.AutoInstrument.from_config = lambda *a, **k: DummyPSU() if "PSU" in a[0] else DummyDMM()  # type: ignore  # monkey-patch

# ─── Real demo code starts here ──────────────────────────────────────
with Measurement("Demo sweep", "auto-generated DB key") as m:
    psu = m.instrument("PSU", "Dummy/PSU")
    dmm = m.instrument("DMM", "Dummy/DMM")

    m.parameter("V_BIAS", np.linspace(0, 5, 6), unit="V")
    m.parameter("REP", range(3))

    @m.acquire
    def read_current(V_BIAS):
        psu.set_voltage(1, V_BIAS)
        return {"I_D": float(dmm.measure().values)}

exp = m.run()

with MeasurementDatabase("demo_db") as db:
    key = db.store_experiment(None, exp)  # codename auto-generated
    print("Stored as", key)
    print("DB now contains:", db.list_experiments())
