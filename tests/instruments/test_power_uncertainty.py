"""Datasheet RF sensor terms on offline, manufacturer-specific SCPI fixtures."""

from dataclasses import replace
from math import log
from math import sqrt

import pytest

from pytestlab import Experiment
from pytestlab.config.loader import load_device_profile
from pytestlab.experiments import MeasurementDatabase
from pytestlab.experiments.results import NativeMeasurementResult
from pytestlab.instruments.PowerMeter import PowerCWConditions
from pytestlab.instruments.PowerMeter import PowerMeter
from pytestlab.uncertainty import is_report_grade
from tests.instruments.test_rf_power_meter import _KEY_VERIFIED
from tests.instruments.test_rf_power_meter import _RS_VERIFIED
from tests.instruments.test_rf_power_meter import _VerifiedTranscript


@pytest.fixture
def keysight():
    backend = _VerifiedTranscript({**_KEY_VERIFIED, "SENS1:AVER:COUN?": "1024"})
    return PowerMeter(load_device_profile("keysight/U2000A_PM"), backend), backend


@pytest.fixture
def rs():
    backend = _VerifiedTranscript(_RS_VERIFIED)
    return PowerMeter(load_device_profile("rohdeschwarz/NRP18AN"), backend), backend


_KEY_CONDITIONS = PowerCWConditions(2.4e9, 22.0, 1800.0, zero_age_s=60.0)
_RS_CONDITIONS = PowerCWConditions(
    2.4e9,
    22.0,
    1800.0,
    temperature_storage_s=10800,
    path_selection="automatic",
    transition_offset_db=0,
)


@pytest.mark.parametrize(("temperature", "half_width"), [(0, 3.5), (15, 3), (35, 3), (55, 3.5)])
def test_keysight_published_bound_is_not_a_standard_uncertainty(keysight, temperature, half_width):
    meter, backend = keysight
    reading = meter.acquire_power()
    before = list(backend.events)
    nominal = reading.to_measurement_result()
    assert nominal.envelope["uncertainty_status"] == "not_evaluated"
    assert nominal.uncertainty is None
    conditions = replace(_KEY_CONDITIONS, ambient_temperature_c=temperature)
    record = reading.to_measurement_result(cw_conditions=conditions)
    assert isinstance(record, NativeMeasurementResult)
    assert record.nominal == reading.value and record.units == reading.unit
    assert record.timestamp == reading.received_at_utc.timestamp()
    assert record.envelope["accuracy_limit"]["half_width_percent"] == half_width
    assert record.envelope["uncertainty_status"] == "accuracy_limit_only"
    assert record.uncertainty is None and record.sigma is None
    assert backend.events == before


@pytest.mark.parametrize(
    ("distribution", "divisor"), [("rectangular", sqrt(3)), ("triangular", sqrt(6))]
)
def test_keysight_type_b_requires_explicit_bounded_distribution(keysight, distribution, divisor):
    meter, _ = keysight
    reading = meter.acquire_power(unit="mW")
    record = reading.to_measurement_result(
        cw_conditions=replace(_KEY_CONDITIONS, accuracy_limit_distribution=distribution)
    )
    q = record.uncertainty
    assert q is not None
    assert q.unit == "W" and record.units == "mW"
    assert q.nominal == pytest.approx(reading.value * 1e-3)
    assert q.u == pytest.approx(q.nominal * 0.03 / divisor)
    assert record.envelope["accuracy_limit"]["half_width_percent"] == 3.0
    assert any(distribution in assumption for assumption in q.measurement_model.assumptions)
    assert not is_report_grade(q)


def test_rs_datasheet_k2_attaches_watts_without_changing_dbm_and_roundtrips(rs, tmp_path):
    meter, _ = rs
    reading = meter.acquire_power()
    record = reading.to_measurement_result(cw_conditions=_RS_CONDITIONS)
    assert isinstance(record, NativeMeasurementResult)
    assert record.units == "dBm" and record.nominal == reading.value
    q = record.uncertainty
    assert q is not None and q.unit == "W"
    assert q.nominal == pytest.approx(10 ** ((reading.value - 30) / 10))
    assert q.u == pytest.approx(q.nominal * log(10) / 10 * (0.094 / 2))
    assert record.envelope["accuracy_component"]["coverage_factor"] == 2
    assert not is_report_grade(q)
    with MeasurementDatabase(tmp_path / "rf-power") as db:
        restored = db.retrieve_measurement(db.store_measurement(None, record))
    assert restored.units == "dBm" and restored.nominal == record.nominal
    assert restored.uncertainty is not None
    assert restored.uncertainty.u == pytest.approx(q.u)
    exp = Experiment("power")
    exp.add_trial(record)
    assert "result__measurement" in exp.data.columns


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"frequency_hz": 2.5e9}, "frequencies must match"),
        ({"warmup_s": 1799}, "30 minutes"),
        ({"ambient_temperature_c": 25.1}, "supported above"),
        ({"temperature_storage_s": None}, "three hours"),
        ({"temperature_storage_s": 10799}, "three hours"),
        ({"path_selection": "fixed"}, "automatic path selection"),
        ({"transition_offset_db": -2}, "0 dB"),
        ({"accuracy_limit_distribution": "rectangular"}, "k=2"),
    ],
)
def test_rs_conditions_leave_good_power_nominal_when_inapplicable(rs, override, reason):
    meter, _ = rs
    reading = meter.acquire_power()
    conditions = replace(_RS_CONDITIONS, **override)
    record = reading.to_measurement_result(cw_conditions=conditions)
    assert isinstance(record, NativeMeasurementResult)
    assert record.nominal == reading.value and record.uncertainty is None
    assert record.envelope["uncertainty_status"] == "not_applicable"
    assert reason in record.envelope["uncertainty_reason"]


def test_keysight_missing_zero_or_1024_averages_does_not_claim_a_bound(keysight):
    meter, _ = keysight
    reading = meter.acquire_power()
    conditions = replace(_KEY_CONDITIONS, zero_age_s=None)
    reduced_count = replace(reading, settings=replace(reading.settings, averaging_count=8))
    for data, condition in ((reading, conditions), (reduced_count, _KEY_CONDITIONS)):
        no_model = data.to_measurement_result(cw_conditions=condition)
        assert no_model.uncertainty is None
        assert "accuracy_limit" not in no_model.envelope
        assert "1024 averages" in no_model.envelope["uncertainty_reason"]


def test_no_datasheet_model_for_non_average_or_low_power(rs):
    meter, _ = rs
    reading = meter.acquire_power()
    for data in (
        replace(reading, value=-40.0),
        replace(reading, settings=replace(reading.settings, mode="peak")),
        replace(reading, settings=replace(reading.settings, trigger_source="external_1")),
    ):
        record = data.to_measurement_result(cw_conditions=_RS_CONDITIONS)
        assert record.uncertainty is None and record.nominal == data.value
        assert record.envelope["uncertainty_status"] == "not_applicable"
