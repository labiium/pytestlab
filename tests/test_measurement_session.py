"""
Unit tests for the notebook-friendly MeasurementSession.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from pytestlab.measurements import Measurement
from pytestlab.measurements import step


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
    first_vec = df["vec"][0]
    second_vec = df["vec"][1]

    def _to_list(value):
        if hasattr(value, "to_list"):
            return value.to_list()
        if hasattr(value, "tolist"):
            return value.tolist()
        return list(value)

    first_list = _to_list(first_vec)
    second_list = _to_list(second_vec)

    assert first_list == [0, 1, 2]
    assert second_list == [1, 2, 3]


def test_step_spec_logarithmic_parameter():
    with Measurement("LogSteps") as session:
        session.parameter("freq", step.log(start=1e3, stop=1e6, count=3))

        @session.acquire
        def capture(freq):
            return {"freq_value": freq}

    df = session.run(show_progress=False).data
    freqs = df["freq"].to_list()
    expected = np.logspace(3, 6, 3)
    assert np.allclose(freqs, expected)


def test_step_spec_points_with_complex_values():
    values = [1 + 1j, 2 - 0.25j, -0.5 + 0.75j]
    with Measurement("ComplexSpec") as session:
        session.parameter("impedance", step.points(values))

        @session.acquire
        def identity(impedance):
            return {"echo": impedance}

    df = session.run(show_progress=False).data
    assert df["impedance"].to_list() == values
    assert df["echo"].to_list() == values
