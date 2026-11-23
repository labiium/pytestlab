"""No hardware: documented, individual marker-level uncertainty components."""

import json
from dataclasses import replace
from math import sqrt

import pytest

from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.experiments import Experiment
from pytestlab.experiments.results import MeasurementResult
from pytestlab.experiments.results import NativeMeasurementResult
from pytestlab.instruments.SpectrumAnalyser import SpectrumMarker
from pytestlab.instruments.SpectrumAnalyser import SpectrumMarkerConditions
from pytestlab.instruments.SpectrumAnalyser import SpectrumTrace
from pytestlab.uncertainty import Quantity

_KEYSIGHT = SpectrumMarkerConditions(
    model="N9000A",
    evidence="verified CW setup #12",
    prerequisites_met=True,
    temperature_c=25,
    tone_frequency_hz=50e6,
    input_power_dbm=-40,
    span_hz=100e3,
    rbw_hz=3e3,
    vbw_hz=3e3,
    attenuation_db=10,
    preamp_on=False,
    accuracy_coupled=True,
)
_FSW = replace(
    _KEYSIGHT,
    model="FSW26",
    reference_level_dbm=-20,
    snr_db=28,
    sweep_time_auto=True,
    electronic_attenuator_on=False,
    yig_preselector_on=True,
    dc_coupled=True,
)


def _marker(model="N9000A", frequency=50e6):
    return SpectrumMarker(1, 2, frequency, -40.05, instrument=model, readout_timestamp=123.0)


def _quantity(result):
    stored = result.envelope["uncertainty"]
    assert stored["kind"] == "quantity"
    quantity = result.uncertainty
    assert isinstance(quantity, Quantity)
    assert quantity.to_dict() == stored["payload"]
    return quantity


def test_default_and_missing_evidence_do_not_synthesize_uncertainty():
    marker = _marker()
    regular = marker.to_measurement_result()
    requested = marker.to_measurement_result(uncertainty=True)
    assert type(regular) is MeasurementResult
    assert isinstance(requested, NativeMeasurementResult)
    assert regular.values.equals(requested.values)
    assert regular.uncertainty is None and requested.uncertainty is None
    assert regular.envelope["uncertainty_status"] == "not_evaluated"
    assert requested.envelope["uncertainty_status"] == "unavailable"
    assert "uncertainty" not in regular.envelope
    assert "uncertainty" not in requested.envelope
    assert regular.timestamp == requested.timestamp == 123.0


def test_keysight_limit_is_not_a_standard_uncertainty_without_explicit_distribution():
    result = _marker().to_measurement_result(uncertainty=True, conditions=_KEYSIGHT)
    assert result.envelope["uncertainty_status"] == "unavailable"
    assert result.envelope["manufacturer_component"]["kind"] == "accuracy_limit"
    assert result.envelope["manufacturer_component"]["half_width_db"] == 0.40
    assert "uncertainty" not in result.envelope
    assert isinstance(result, NativeMeasurementResult)
    assert result.uncertainty is None


@pytest.mark.parametrize(
    ("distribution", "divisor"), [("rectangular", sqrt(3)), ("triangular", sqrt(6))]
)
def test_keysight_uses_explicit_type_b_distribution(distribution, divisor):
    result = _marker().to_measurement_result(
        uncertainty=True, conditions=_KEYSIGHT, bound_distribution=distribution
    )
    quantity = _quantity(result)
    assert quantity.nominal == -40.05
    assert quantity.unit == "dBm"
    assert quantity.u == pytest.approx(0.40 / divisor)
    assert quantity.provenance is not None and not quantity.provenance.provenance_complete
    assert result.envelope["uncertainty_field"] == "amplitude_dbm"
    assert result.envelope["uncertainty_component_unit"] == "dB"
    assert result.envelope["condition_evidence"]["source"] == _KEYSIGHT.evidence
    assert result.envelope["manufacturer_component"]["selected_type_b_distribution"] == distribution


@pytest.mark.parametrize(
    ("frequency", "yig", "expanded"),
    [
        (9e3, True, 0.37),
        (10e6, True, 0.37),
        (10e6 + 1, True, 0.27),
        (3.6e9, True, 0.27),
        (3.6e9 + 1, True, 0.37),
        (8e9, True, 0.37),
        (8e9, False, 1.0),
        (8e9 + 1, True, 1.4),
        (22e9, False, 1.0),
        (22e9 + 1, False, 1.2),
        (26.5e9, True, 1.7),
    ],
)
def test_fsw_uses_frequency_band_yig_state_and_documented_k2(frequency, yig, expanded):
    conditions = replace(_FSW, tone_frequency_hz=frequency, yig_preselector_on=yig)
    result = _marker("FSW26", frequency).to_measurement_result(
        uncertainty=True, conditions=conditions
    )
    assert _quantity(result).u == pytest.approx(expanded / 2)
    assert result.envelope["manufacturer_component"]["expanded_db"] == expanded
    assert result.envelope["manufacturer_component"]["coverage_factor"] == 2
    assert result.envelope["manufacturer_component"]["coverage_probability"] == 0.95
    assert result.envelope["correlation_status"] == "not_evaluated"


@pytest.mark.parametrize(
    "change",
    [
        {"model": "N9000B"},
        {"prerequisites_met": False},
        {"evidence": " "},
        {"temperature_c": 30.01},
        {"tone_frequency_hz": 51e6},
        {"input_power_dbm": -50.001},
        {"attenuation_db": 20},
        {"rbw_hz": 1e6 + 1},
        {"vbw_hz": 30e3 + 1},
        {"accuracy_coupled": None},
        {"span_hz": 5e6},
        {"preamp_on": True},
        {"temperature_c": float("nan")},
    ],
)
def test_keysight_refuses_out_of_scope_or_unknown_conditions(change):
    result = _marker().to_measurement_result(
        uncertainty=True, conditions=replace(_KEYSIGHT, **change), bound_distribution="rectangular"
    )
    assert result.envelope["uncertainty_status"] == "unavailable"
    assert "uncertainty" not in result.envelope


@pytest.mark.parametrize(
    "change",
    [
        {"temperature_c": 19.9},
        {"snr_db": 20},
        {"span_hz": 300e3},
        {"reference_level_dbm": 31},
        {"sweep_time_auto": False},
        {"electronic_attenuator_on": None},
        {"attenuation_db": 15},
        {"yig_preselector_on": False},
        {"yig_preselector_on": None},
    ],
)
def test_fsw_refuses_out_of_scope_or_unknown_conditions(change):
    result = _marker("FSW26").to_measurement_result(
        uncertainty=True, conditions=replace(_FSW, **change)
    )
    assert result.envelope["uncertainty_status"] == "unavailable"
    assert "uncertainty" not in result.envelope


def test_fsw_below_10mhz_needs_dc_coupling():
    result = _marker("FSW26", 7e6).to_measurement_result(
        uncertainty=True,
        conditions=replace(_FSW, tone_frequency_hz=7e6, dc_coupled=False),
    )
    assert result.envelope["uncertainty_status"] == "unavailable"


def test_no_other_result_or_unbound_marker_gets_uncertainty():
    raw = SpectrumMarker(1, 1, 50e6, -40.05, instrument="N9000A")
    raw_result = raw.to_measurement_result(uncertainty=True, conditions=_KEYSIGHT)
    assert raw_result.envelope["uncertainty_status"] == "unavailable"
    trace = SpectrumTrace(1, (50e6,), (-40.05,), "frequency", "dBm")
    assert trace.to_measurement_result().envelope["uncertainty_status"] == "not_evaluated"


def test_native_uncertainty_survives_storage_without_changing_shape(tmp_path):
    raw = _marker("FSW26")
    result = raw.to_measurement_result(uncertainty=True, conditions=_FSW)
    with MeasurementDatabase(tmp_path / "marker.sqlite") as database:
        key = database.store_measurement(None, result)
        restored = database.retrieve_measurement(key)
    assert restored.values.equals(raw.to_measurement_result().values)
    assert restored.envelope == result.envelope
    assert _quantity(restored).u == pytest.approx(0.135)


def test_direct_trial_preserves_conditioned_and_unavailable_marker_envelopes():
    experiment = Experiment("markers")
    raw = _marker("FSW26")
    conditioned = raw.to_measurement_result(uncertainty=True, conditions=_FSW)
    unavailable = raw.to_measurement_result(uncertainty=True)
    experiment.add_trial(conditioned)
    experiment.add_trial(unavailable)
    assert experiment.data.height == 2
    assert experiment.data["result"][0].struct.unnest().equals(conditioned.values)
    meta = experiment.data["result__measurement"].to_list()
    assert json.loads(meta[0])["result"]["envelope"] == conditioned.envelope
    assert json.loads(meta[1])["result"]["envelope"] == unavailable.envelope
