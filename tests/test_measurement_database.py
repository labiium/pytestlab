"""
Tests for the MeasurementDatabase (auto-codename, store/retrieve/search).
"""
from __future__ import annotations

import numpy as np
import pytest

from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.results import MeasurementResult


def test_store_and_retrieve_experiment(tmp_db_file, simple_experiment):
    with MeasurementDatabase(tmp_db_file) as db:
        key = db.store_experiment(None, simple_experiment)
        assert key.startswith("EXP_")

        exp_out = db.retrieve_experiment(key)
        assert exp_out.name == simple_experiment.name
        assert list(db.list_experiments()) == [key]


def test_store_and_retrieve_measurement(tmp_db_file):
    meas = MeasurementResult(values=np.array([1.23]), instrument="DMM_X", units="V", measurement_type="Voltage")

    with MeasurementDatabase(tmp_db_file) as db:
        key = db.store_measurement(None, meas)
        assert key.startswith("MEAS_")

        meas_out = db.retrieve_measurement(key)
        np.testing.assert_allclose(meas_out.values, meas.values)

        # searching by instrument
        assert db.list_measurements() == [key]


def test_overwrite_policy(tmp_db_file, simple_experiment):
    with MeasurementDatabase(tmp_db_file) as db:
        # first insert
        key = db.store_experiment("MYKEY", simple_experiment)
        # second insert with same key but overwrite disabled should raise
        with pytest.raises(ValueError):
            db.store_experiment("MYKEY", simple_experiment, overwrite=False)
        # now overwrite
        db.store_experiment("MYKEY", simple_experiment, overwrite=True)
        assert db.retrieve_experiment("MYKEY").name == simple_experiment.name
