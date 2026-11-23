"""
Unit tests for the notebook-friendly MeasurementSession.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from pytestlab import Bench
from pytestlab.experiments import MeasurementDatabase
from pytestlab.experiments import MeasurementResult
from pytestlab.instruments.Oscilloscope import ChannelReadingResult
from pytestlab.measurements import Measurement
from pytestlab.measurements import step
from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty import uq


def test_context_exit_logs_device_close_failure(caplog, monkeypatch):
    from pytestlab.devices import AutoDevice

    class BrokenDevice:
        def close(self) -> None:
            raise RuntimeError("close failed")

    session = Measurement("Cleanup", compliance=False)
    broken_device = BrokenDevice()
    monkeypatch.setattr(AutoDevice, "from_config", lambda *args, **kwargs: broken_device)
    assert session.device("broken", "unused") is broken_device

    with caplog.at_level(logging.ERROR):
        assert session.__exit__(None, None, None) is False

    assert "Failed to close device 'broken'" in caplog.text


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


def test_direct_measurement_result_preserves_uncertainty_metadata(tmp_path):
    with Measurement("Result", compliance=False) as session:
        session.parameter("index", [0])

        @session.acquire
        def voltage():
            return MeasurementResult(
                Quantity.constant(1.25, "V"),
                instrument="dmm",
                units="V",
                measurement_type="voltage_dc",
            )

        @session.acquire
        def waveform():
            return {
                "samples": QuantityArray.from_samples([1.0, 2.0], unit="V", independent_std=0.1),
                "native": uq(1.2, 0.03, "V"),
                "sequence": [uq(2.0, 0.1, "V"), uq(3.0, 0.2, "V")],
            }

    df = session.run(show_progress=False).data
    assert df["voltage"][0] == pytest.approx(1.25)
    metadata = json.loads(df["voltage__measurement"][0])
    assert metadata["result"]["instrument"] == "dmm"
    assert metadata["uncertainty"]["value_kind"] == "quantity"
    assert df["samples"].dtype != pl.Object
    native = json.loads(df["native__measurement"][0])
    assert native["uncertainty"]["quantity"]["standard_uncertainty"] == pytest.approx(0.03)
    assert df["sequence"][0].to_list() == [2.0, 3.0]
    sequence = json.loads(df["sequence__measurement"][0])
    assert sequence["uncertainty"]["value_kind"] == "quantity_list"
    df.write_ipc(tmp_path / "session.arrow")


def test_table_measurement_session_round_trip(tmp_path):
    database_path = tmp_path / "session.sqlite"
    bench_path = tmp_path / "bench.yaml"
    bench_path.write_text(
        f"""bench_name: Offline trace bench
experiment:
  title: Trace trials
  description: Offline waveform storage
  database_path: {database_path}
devices:
  dmm:
    profile: keysight/EDU34450A
    backend:
      type: sim
"""
    )

    traces = [
        pl.DataFrame(
            {
                "Time (s)": pl.Series([0, 1, 2], dtype=pl.Float32),
                "Channel 1 (V)": [0.1, 0.2, None],
                "sample_at": pl.Series([1, 2, 3]).cast(pl.Datetime("ns", "UTC")),
            }
        ),
        pl.DataFrame(
            schema={
                "Time (s)": pl.Float32,
                "Channel 1 (V)": pl.Float64,
                "sample_at": pl.Datetime("ns", "UTC"),
            }
        ),
    ]
    with Bench.open(bench_path) as bench, Measurement(bench=bench, compliance=False) as session:
        session.parameter("trial", [0, 1, 2])

        @session.acquire
        def trace(trial):
            return (
                {
                    "waveform": ChannelReadingResult(
                        values=traces[trial],
                        instrument="scope",
                        units="V",
                        measurement_type="waveform",
                        timestamp=12.25,
                        envelope={"fresh": True, "axis_unit": "s", "channels": [1]},
                        sampling_rate=2e6,
                    )
                }
                if trial < len(traces)
                else {}
            )

        @session.acquire
        def dmm_reading(dmm):
            return dmm.measure("dc_voltage")

        @session.acquire
        def samples(trial):
            if trial == 2:
                return {}
            return {
                "samples": MeasurementResult(
                    values=np.array([1.25, 2.5] if trial == 0 else [], dtype=np.float32),
                    instrument="power",
                    units="W",
                    measurement_type="power_buffer",
                ),
                "counts": np.array([2**64 - 1] if trial == 0 else [], dtype=np.uint64),
            }

        experiment = session.run(show_progress=False)
        assert experiment.data.height == 3
        assert experiment.data.schema["waveform"] == pl.List(pl.Struct(traces[0].schema))
        assert experiment.data.schema["samples"] == pl.List(pl.Float32)
        assert experiment.data.schema["counts"] == pl.List(pl.UInt64)
        assert experiment.data["samples"].to_list() == [[1.25, 2.5], [], None]
        assert experiment.data["counts"].to_list() == [[2**64 - 1], [], None]
        assert experiment.data["dmm_reading"].dtype == pl.Float64
        assert_frame_equal(experiment.data["waveform"][0].struct.unnest(), traces[0])
        assert_frame_equal(experiment.data["waveform"][1].struct.unnest(), traces[1])
        assert experiment.data["waveform"][2] is None
        assert json.loads(experiment.data["waveform__measurement"][0])["result"] == {
            "instrument": "scope",
            "units": "V",
            "measurement_type": "waveform",
            "timestamp": 12.25,
            "envelope": {"fresh": True, "axis_unit": "s", "channels": [1]},
            "sampling_rate": 2e6,
        }
        parquet = tmp_path / "trials.parquet"
        experiment.save_parquet(str(parquet))
        assert_frame_equal(pl.read_parquet(parquet), experiment.data)

    with MeasurementDatabase(database_path) as db:
        [codename] = db.list_experiments()
        assert_frame_equal(db.retrieve_experiment(codename).data, experiment.data)


def test_table_measurement_requires_consistent_sample_schema():
    with Measurement(compliance=False) as session:
        session.parameter("trial", [1, 2])

        @session.acquire
        def spectrum(trial):
            return MeasurementResult(
                values=pl.DataFrame({"Frequency (Hz)": [1e6], f"Trace {trial} (dBm)": [-20.0]}),
                instrument="spectrum",
                units="dBm",
                measurement_type="trace",
            )

        with pytest.raises(ValueError, match="'spectrum' must use the same sample schema"):
            session.run(show_progress=False)


def test_table_measurement_rejects_object_samples():
    with Measurement(compliance=False) as session:
        session.parameter("trial", [1])

        @session.acquire
        def spectrum():
            return MeasurementResult(
                values=pl.DataFrame({"power": pl.Series([object()], dtype=pl.Object)}),
                instrument="spectrum",
                units="dBm",
                measurement_type="trace",
            )

        with pytest.raises(ValueError, match="'spectrum' table contains a Polars Object column"):
            session.run(show_progress=False)


def test_masked_vector_cannot_silently_store_underlying_samples():
    with Measurement(compliance=False) as session:
        session.parameter("trial", [1])

        @session.acquire
        def power():
            return {"samples": np.ma.array([1.0, 999.0], mask=[False, True])}

        with pytest.raises(
            ValueError, match="'samples' uses a NumPy masked array.*table with nulls"
        ):
            session.run(show_progress=False)
