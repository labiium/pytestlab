from __future__ import annotations

import json
import time
from types import SimpleNamespace

import polars as pl
import pytest

from pytestlab import MeasurementSession
from pytestlab.compliance.session import ComplianceConfig
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.experiments import Experiment
from pytestlab.experiments.results import MeasurementResult
from pytestlab.experiments.results import NativeMeasurementResult


class NativeCapture:
    """A stand-in for one of the concrete instrument result adapters."""

    def to_measurement_result(self) -> MeasurementResult:
        return MeasurementResult(
            values=pl.DataFrame({"axis": [100.0, 200.0], "real": [-0.1, 0.2], "imag": [0.3, -0.4]}),
            instrument="native test instrument",
            units="1",
            measurement_type="trace",
            timestamp=1_731_916_800.25,
            sampling_rate=125.0,
            envelope={
                "timestamp_kind": "host_receipt",
                "trace_order": ["S21"],
                "uncertainty_status": "not_evaluated",
            },
        )


def _assert_native_trial(data: pl.DataFrame, column: str) -> None:
    expected = NativeCapture().to_measurement_result()
    assert data.height == 1
    assert isinstance(data.schema[column], pl.List)
    assert data[column][0].struct.unnest().equals(expected.values)
    envelope = json.loads(data[f"{column}__measurement"][0])
    assert envelope["result"]["envelope"] == expected.envelope
    assert envelope["result"]["timestamp"] == expected.timestamp
    assert envelope["uncertainty"] == {}


@pytest.mark.parametrize("mapping", [False, True])
def test_session_accepts_native_measurement_directly_and_inside_mappings(mapping):
    with MeasurementSession("native", compliance=False) as session:
        session.parameter("point", [1])

        @session.acquire
        def captured():
            return {"captured": NativeCapture()} if mapping else NativeCapture()

        trial = session.run(show_progress=False)
    _assert_native_trial(trial.data, "captured")


def test_experiment_keeps_native_trial_nested_but_legacy_trial_layout_unchanged(tmp_path):
    experiment = Experiment("native")
    experiment.add_parameter("point", "1")
    experiment.add_trial(NativeCapture(), point=1)
    _assert_native_trial(experiment.data, "result")
    assert experiment.data["point"].to_list() == [1]
    path = tmp_path / "experiment.parquet"
    experiment.save_parquet(str(path))
    _assert_native_trial(pl.read_parquet(path), "result")

    legacy = Experiment("legacy")
    expected = NativeCapture().to_measurement_result()
    legacy.add_trial(expected)
    assert legacy.data.equals(expected.values)


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="Changing the process timezone needs tzset.")
def test_standalone_db_preserves_native_axis_identity_and_original_epoch(tmp_path, monkeypatch):
    expected = NativeCapture().to_measurement_result()
    try:
        with (
            monkeypatch.context() as environment,
            MeasurementDatabase(tmp_path / "native.db") as db,
        ):
            environment.setenv("TZ", "UTC0")
            time.tzset()
            key = db.store_measurement(None, NativeCapture())
            environment.setenv("TZ", "EST5")
            time.tzset()
            saved = db.retrieve_measurement(key)
            assert saved.values.equals(expected.values)
            assert saved.instrument == expected.instrument
            assert saved.units == expected.units
            assert saved.envelope == expected.envelope
            assert saved.timestamp == expected.timestamp
            assert saved.sampling_rate == expected.sampling_rate
    finally:
        time.tzset()


def test_native_adapter_must_return_measurement_result_and_serializable_metadata(tmp_path):
    class WrongType:
        def to_measurement_result(self):
            return {"values": 1.0}

    class WrongMetadata(NativeCapture):
        def to_measurement_result(self):
            result = super().to_measurement_result()
            result.envelope["opaque"] = object()
            return result

    with pytest.raises(TypeError, match="must return a MeasurementResult"):
        Experiment("bad").add_trial(WrongType())
    with MeasurementDatabase(tmp_path / "bad.db") as db:
        with pytest.raises(ValueError, match="envelope must be JSON-serializable"):
            db.store_measurement(None, WrongMetadata())


@pytest.mark.parametrize("kind", ["bare", "mapping", "enriched", "enriched_mapping", "legacy"])
def test_active_compliance_never_signs_an_uncanonical_native_capture(kind):
    class Evidence:
        def __init__(self):
            self.signatures = []
            self.timestamps = []
            self.audits = []

        def sign(self, digest):
            self.signatures.append(digest)
            return SimpleNamespace(to_dict=lambda: {"signature": "test"})

        def timestamp(self, digest):
            self.timestamps.append(digest)
            return SimpleNamespace(to_dict=lambda: {"timestamp": "test"})

        def append(self, audit):
            self.audits.append(audit)
            return "audit-id"

    class UncanonicalCapture(NativeCapture):
        def to_measurement_result(self):
            pytest.fail("Native conversion must not run inside existing evidence wrapping.")

    evidence = Evidence()
    config = ComplianceConfig(signer=evidence, auditor=evidence, timestamper=evidence)
    with MeasurementSession("evidence", compliance=config) as session:
        session.parameter("point", [2])

        @session.acquire
        def capture(point):
            assert point == 2
            if kind == "legacy":
                return MeasurementResult(0.5, "legacy", "V", "voltage")
            if kind.startswith("enriched"):
                converted = NativeMeasurementResult(0.5, "enriched", "W", "power")
                return {"capture": converted} if kind == "enriched_mapping" else converted
            if kind == "mapping":
                return {"capture": UncanonicalCapture()}
            return UncanonicalCapture()

        if kind == "legacy":
            experiment = session.run(show_progress=False)
            assert experiment.data["value"].to_list() == [0.5]
            assert len(evidence.timestamps) == len(evidence.signatures) == 1
            assert [row.success for row in evidence.audits] == [True]
        else:
            with pytest.raises(RuntimeError, match="not supported in signed"):
                session.run(show_progress=False)
            assert not evidence.signatures and not evidence.timestamps
            assert [row.success for row in evidence.audits] == [False]


def test_compliance_config_with_no_evidence_components_still_accepts_native():
    with MeasurementSession("no evidence", compliance=ComplianceConfig()) as session:
        session.parameter("point", [1])

        @session.acquire
        def capture():
            return NativeCapture()

        experiment = session.run(show_progress=False)
    _assert_native_trial(experiment.data, "capture")
