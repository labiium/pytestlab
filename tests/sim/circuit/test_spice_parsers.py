from __future__ import annotations

import numpy as np
import pytest

from pytestlab.sim.circuit.models import SourceDescriptor
from pytestlab.sim.circuit.spice import NgspiceRunError
from pytestlab.sim.circuit.spice import _extract_vectors
from pytestlab.sim.circuit.spice import _parse_complex_wrdata
from pytestlab.sim.circuit.spice import _parse_real_wrdata


def test_real_wrdata_filters_nonfinite_scale_rows() -> None:
    data = np.asarray(
        [
            [0.0, 1.0],
            [np.nan, 2.0],
            [2.0, 3.0],
        ],
        dtype=float,
    )

    scale, series = _parse_real_wrdata(data, 1)

    assert scale.tolist() == [0.0, 2.0]
    assert series[:, 0].tolist() == [1.0, 3.0]


def test_complex_wrdata_rejects_missing_imaginary_vector() -> None:
    data = np.asarray([[10.0, 1.0]], dtype=float)

    with pytest.raises(NgspiceRunError, match="expected 3"):
        _parse_complex_wrdata(data, 1)


def test_real_wrdata_rejects_missing_vectors() -> None:
    data = np.empty((2, 0), dtype=float)

    with pytest.raises(NgspiceRunError, match="column count"):
        _parse_real_wrdata(data, 1)


def test_extract_vectors_preserves_current_vector_order() -> None:
    series = np.asarray(
        [
            [1.0, -0.1, 0.001],
            [2.0, -0.2, 0.002],
        ],
        dtype=float,
    )
    sources = (
        SourceDescriptor(
            kind="psu",
            key="psu1.CH1",
            vsrc_name="VSB",
            hi_node="vout",
            lo_node="0",
        ),
    )

    nodes, source_currents, element_currents = _extract_vectors(
        ["vout"],
        sources,
        ["dmm1.I"],
        series,
    )

    assert nodes["vout"].tolist() == [1.0, 2.0]
    assert source_currents["psu1.CH1"].tolist() == [-0.1, -0.2]
    assert element_currents["dmm1.I"].tolist() == [0.001, 0.002]
