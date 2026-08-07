from __future__ import annotations

import numpy as np
import pytest

from pytestlab.experiments.uncertainty_serialization import deserialize_uncertain_value
from pytestlab.experiments.uncertainty_serialization import serialize_uncertain_value
from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty import correlated_values
from pytestlab.uncertainty import covariance_matrix


def test_legacy_scalar_payload_migrates_to_native_quantity() -> None:
    restored = deserialize_uncertain_value(
        np.array([1.2, 0.03]),
        {"value_kind": "ufloat", "nominal": 1.2, "standard_uncertainty": 0.03},
        unit="V",
    )

    assert isinstance(restored, Quantity)
    assert restored.nominal == 1.2
    assert restored.u == 0.03
    assert restored.unit == "V"


def test_legacy_array_payload_migrates_to_native_quantities() -> None:
    restored = deserialize_uncertain_value(
        np.array([[[1.0, 0.1], [2.0, 0.2]]]),
        {"value_kind": "ufloat_ndarray", "shape": [1, 2]},
        unit="V",
    )

    assert isinstance(restored, np.ndarray)
    assert restored.shape == (1, 2)
    assert all(isinstance(value, Quantity) for value in restored.flat)
    assert restored[0, 1].nominal == 2.0
    assert restored[0, 1].u == 0.2


def test_native_quantity_sequences_keep_models_and_correlations() -> None:
    values = correlated_values(
        [1.0, 2.0],
        [[0.01, 0.002], [0.002, 0.04]],
        labels=["x", "y"],
    )

    payload, metadata = serialize_uncertain_value(values)
    restored = deserialize_uncertain_value(payload, metadata)

    assert isinstance(restored, list)
    assert covariance_matrix(restored) == pytest.approx(covariance_matrix(values))

    array = np.empty((1, 2), dtype=object)
    array[0] = values
    payload, metadata = serialize_uncertain_value(array)
    restored_array = deserialize_uncertain_value(payload, metadata)

    assert isinstance(restored_array, np.ndarray)
    assert restored_array.shape == (1, 2)
    assert covariance_matrix(restored_array.reshape(-1).tolist()) == pytest.approx(
        covariance_matrix(values)
    )
