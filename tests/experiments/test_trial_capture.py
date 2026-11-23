from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from pytestlab import MeasurementResult
from pytestlab import MeasurementSession
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.experiments import Experiment
from pytestlab.instruments.Oscilloscope import ChannelReadingResult
from pytestlab.instruments.SpectrumAnalyser import SpectrumTrace
from pytestlab.uncertainty import AtomRegistry
from pytestlab.uncertainty import Quantity


def test_indexed_spectrum_and_direct_trials_keep_their_order_after_storage(tmp_path):
    traces = (
        SpectrumTrace(1, (1.0e6, 2.0e6), (-45.0, -70.0), "frequency", "dBm"),
        SpectrumTrace(1, (1.5e6, 2.5e6), (-12.0, -125.0), "frequency", "dBm"),
    )
    with MeasurementSession("spectrum", compliance=False) as session:
        session.parameter("repeat", [0, 1])

        @session.acquire
        def spectrum_trace(repeat):
            return traces[repeat]

        experiment = session.run(show_progress=False)

    assert list(experiment.measurements) == ["spectrum_trace"]
    captures = experiment.measurements["spectrum_trace"]
    assert len(captures) == 2
    assert captures[0].values.equals(traces[0].to_measurement_result().values)
    assert captures[1].values.equals(traces[1].to_measurement_result().values)
    assert captures[-1].values.equals(captures[1].values)
    assert [capture.values["amplitude"][0] for capture in captures[:]] == [-45.0, -12.0]
    assert captures[1].envelope == traces[1].to_measurement_result().envelope
    assert captures[1].envelope["acquisition"] == "unknown"
    assert captures[1].units == "dBm"

    direct = Experiment("direct")
    for trace in traces:
        direct.add_trial(trace)
    assert list(direct.measurements) == ["result"]
    assert direct.measurements["result"][0].values.equals(captures[0].values)
    expected = direct.measurements["result"][1]
    with MeasurementDatabase(tmp_path / "captures.db") as database:
        saved_name = database.store_experiment(None, experiment)
        direct_name = database.store_experiment(None, direct)
        session_saved = database.retrieve_experiment(saved_name).measurements["spectrum_trace"][1]
        direct_saved = database.retrieve_experiment(direct_name).measurements["result"][1]
    parquet = tmp_path / "spectrum.parquet"
    experiment.save_parquet(str(parquet))
    reloaded = Experiment("read Parquet")
    reloaded.data = pl.read_parquet(parquet)
    parquet_saved = reloaded.measurements["spectrum_trace"][1]
    for saved, original in (
        (session_saved, captures[1]),
        (direct_saved, expected),
        (parquet_saved, captures[1]),
    ):
        assert saved.values.equals(original.values)
        assert saved.envelope == original.envelope
        assert saved.timestamp == original.timestamp
        assert saved.instrument == original.instrument
        assert saved.units == original.units


def test_existing_scope_table_and_scalar_quantity_capture_restore_without_metadata_loss():
    waveform = ChannelReadingResult(
        values=pl.DataFrame({"Time (s)": [0.0, 0.25], "Channel 1 (V)": [-1.0, 2.0]}),
        instrument="scope",
        units="V",
        measurement_type="ChannelVoltageTime",
        timestamp=1_700_000_000.25,
        sampling_rate=4.0,
        envelope={"channel": 1},
    )
    registry = AtomRegistry()
    voltage = Quantity.from_atom(
        registry.mint(nominal=1.2, std_uncertainty=0.05, label="sensor", unit="V"), registry
    )
    scalar = MeasurementResult(voltage, "meter", "V", "dc_voltage", timestamp=1_700_000_000.5)
    vector = MeasurementResult(np.asarray([0, 255], dtype=np.uint8), "meter", "1", "samples")
    with MeasurementSession("existing captures", compliance=False) as session:
        session.parameter("repeat", [1])

        @session.acquire
        def acquire():
            return {"waveform": waveform, "voltage": scalar, "vector": vector}

        experiment = session.run(show_progress=False)
    wave = experiment.measurements["waveform"][0]
    assert wave.values.equals(waveform.values)
    assert (wave.envelope, wave.timestamp, wave.sampling_rate) == (
        waveform.envelope,
        waveform.timestamp,
        waveform.sampling_rate,
    )
    measured = experiment.measurements["voltage"][0]
    assert isinstance(measured.values, Quantity)
    assert measured.values.nominal == voltage.nominal
    assert measured.values.u == pytest.approx(voltage.u)
    assert measured.values.budget() == voltage.budget()
    numeric = experiment.measurements["vector"][0].values
    assert numeric.dtype == np.uint8
    assert numeric.tolist() == [0, 255]

    legacy_flat = Experiment("legacy flat")
    legacy_flat.add_trial(waveform)
    with pytest.raises(KeyError, match="No stored measurement"):
        legacy_flat.measurements["Channel 1 (V)"]


def test_missing_capture_keeps_its_trial_index_between_typed_captures():
    values = pl.DataFrame(schema={"frequency_hz": pl.Float64, "sample": pl.Int16})
    blank = MeasurementResult(values, "fixture", "V", "trace")
    nonempty = MeasurementResult(
        pl.DataFrame({"frequency_hz": [1e6], "sample": pl.Series([1], dtype=pl.Int16)}),
        "fixture",
        "V",
        "trace",
    )
    with MeasurementSession("optional capture", compliance=False) as session:
        session.parameter("repeat", [1, 2, 3])

        @session.acquire
        def acquire(repeat):
            return {} if repeat == 2 else {"trace": blank if repeat == 1 else nonempty}

        experiment = session.run(show_progress=False)
    captures = experiment.measurements["trace"]
    empty, missing, final = captures
    assert empty.values.is_empty() and empty.values.schema == values.schema
    assert missing is None and captures[1] is None
    assert final.values.equals(nonempty.values)
    assert captures[-1].values.equals(final.values)
    with pytest.raises(IndexError, match="Trial 3 is out of range"):
        captures[3]
