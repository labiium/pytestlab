from __future__ import annotations

import numpy as np
import pytest

from pytestlab.experiments.sweep import _grid_sweep_impl
from pytestlab.experiments.sweep import _parameter_grid_axis


@pytest.mark.parametrize("count", [1, 2, 3, 1001])
def test_parameter_grid_repairs_overflowing_finite_spans(count):
    maximum = np.finfo(np.float64).max
    axis = _parameter_grid_axis(-maximum, maximum, count)

    assert len(axis) == count
    assert np.isfinite(axis).all()
    assert axis[0] == -maximum
    if count > 1:
        assert axis[-1] == maximum
        assert np.all(axis[1:] >= axis[:-1])


@pytest.mark.parametrize(
    ("start", "stop", "count"),
    [
        (-0.0, 0.0, 3),
        (0.0, -0.0, 3),
        (np.nextafter(0.0, 1.0), np.nextafter(0.0, 2.0), 3),
        (np.finfo(np.float64).max, np.finfo(np.float64).max, 3),
        (-np.finfo(np.float64).max, -np.finfo(np.float64).max, 3),
    ],
)
def test_parameter_grid_preserves_numpy_for_finite_spans(start, stop, count):
    actual = _parameter_grid_axis(start, stop, count)
    expected = np.linspace(start, stop, count)
    np.testing.assert_array_equal(actual, expected)


def test_parameter_grid_count_one_uses_start_coordinate():
    maximum = np.finfo(np.float64).max
    results = _grid_sweep_impl(lambda value: value, [(-maximum, maximum)], 1)
    assert results == [([-maximum], -maximum)]
