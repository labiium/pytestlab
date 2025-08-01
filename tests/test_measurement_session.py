"""
Unit tests for the notebook-friendly MeasurementSession.
"""
from __future__ import annotations

import numpy as np
import polars as pl
from pytestlab.measurements import Measurement


def test_basic_sweep():
    with Measurement("UnitTest") as meas:
        meas.parameter("A", [1, 2, 3])
        meas.parameter("B", [10, 20])

        @meas.acquire
        def calc_sum(A, B):
            return {"SUM": A + B}

    exp = meas.run(show_progress=False)

    # 6 rows = 3*2 combinations
    assert len(exp.data) == 6
    # column existence
    assert set(exp.data.columns) == {"A", "B", "timestamp", "SUM"}
    # Data correctness (first point)
    first = exp.data.row(0)
    assert first[2] >= 0  # timestamp
    assert first[3] == first[0] + first[1]

    # Polars dtype check
    assert isinstance(exp.data, pl.DataFrame)


def test_vector_return():
    with Measurement("Vec") as m:
        m.parameter("idx", [0, 1])

        @m.acquire
        def vec(idx):
            return {"vec": np.arange(3) + idx}

    df = m.run(show_progress=False).data
    assert df["vec"][0].tolist() == [0, 1, 2]
    assert df["vec"][1].tolist() == [1, 2, 3]
