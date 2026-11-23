from __future__ import annotations

import numpy as np
import polars as pl

from pytestlab.experiments import Experiment
from pytestlab.experiments import MeasurementDatabase
from pytestlab.experiments import MeasurementResult
from pytestlab.experiments.results import NativeMeasurementResult
from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty.atoms import AtomRegistry


def test_stored_uncertainty_restores_correlated_samples_without_replacing_table(tmp_path):
    registry = AtomRegistry()
    scale_error = registry.mint(nominal=0.0, std_uncertainty=0.1, label="shared calibration")
    samples = QuantityArray(
        [0.1, -0.2],
        registry=registry,
        atom_sensitivities={scale_error.uid: np.array([1.0, -1.0])},
        diagonal_variance=[0.01, 0.02],
    )
    nominal = pl.DataFrame({"real": [0.1], "imag": [-0.2]})
    result = NativeMeasurementResult(
        nominal,
        "VNA",
        "1",
        "s_parameters",
        envelope={
            "uncertainty_status": "externally_evaluated",
            "uncertainty": {"kind": "quantity_array", "payload": samples.to_dict()},
        },
    )

    experiment = Experiment("calibrated")
    experiment.add_trial(result)
    trial = experiment.measurements["result"][0]
    assert isinstance(trial, NativeMeasurementResult)
    assert trial.values.equals(nominal)
    assert isinstance(trial_uncertainty := trial.uncertainty, QuantityArray)
    np.testing.assert_allclose(
        trial_uncertainty.covariance_matrix(), [[0.02, -0.01], [-0.01, 0.03]]
    )

    with MeasurementDatabase(tmp_path / "measurements.db") as db:
        saved = db.retrieve_measurement(db.store_measurement(None, result))

    assert isinstance(saved, NativeMeasurementResult)
    refiled = Experiment("refiled")
    refiled.add_trial(saved)
    assert refiled.measurements["result"][0].values.equals(nominal)
    assert saved.values.equals(nominal)
    assert isinstance(restored := saved.uncertainty, QuantityArray)
    np.testing.assert_allclose(restored.covariance_matrix(), [[0.02, -0.01], [-0.01, 0.03]])


def test_nominal_accuracy_bound_is_not_an_evaluated_uncertainty():
    nominal = MeasurementResult(1.0, "meter", "W", "power", envelope={"accuracy_limit": 0.1})
    assert nominal.uncertainty is None
    quantity = Quantity.constant(1.0, "W")
    legacy = MeasurementResult(quantity, "meter", "W", "power")
    assert legacy.uncertainty is quantity
