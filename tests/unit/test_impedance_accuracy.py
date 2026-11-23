import json
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from math import degrees
from math import sqrt

import pytest

from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.experiments import Experiment
from pytestlab.experiments.results import NativeMeasurementResult
from pytestlab.instruments.ImpedanceAnalyzer import E4990AAccuracyConditions
from pytestlab.instruments.ImpedanceAnalyzer import IM3570AccuracyConditions
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceReading
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceSweep
from pytestlab.uncertainty import Distribution
from pytestlab.uncertainty import Kind
from pytestlab.uncertainty import Quantity

_KEYSIGHT = E4990AAccuracyConditions(
    setup_reference="run-acquisition-4tp",
    temperature_c=23,
    warmup_minutes=90,
    voltage_v_rms=0.5,
    measurement_time=5,
    dc_current_range_a=0.001,
    dc_bias_enabled=False,
)
_HIOKI = IM3570AccuracyConditions(
    setup_reference="run-acquisition-compensated-hioki",
    temperature_c=23,
    relative_humidity_percent=50,
    warmup_minutes=60,
    voltage_v_rms=1,
    range_ohm=1_000,
    speed_step=4,
    cable_length_m=0,
    dc_bias_enabled=False,
)
_MAG = "magnitude_accuracy_limit_ohm"
_PHASE = "phase_accuracy_limit_deg"


def _point(model, *, f=10_000, z=complex(300, -400), status=None):
    return ImpedanceReading(
        f, z, 1, 1, status, _model=model, _receipt=datetime(2026, 11, 23, tzinfo=UTC)
    )


def test_e4990a_equation_one_direct_port_retains_nominal_data():
    reading = _point("E4990A")
    plain = reading.to_measurement_result()
    result = reading.to_measurement_result(accuracy=_KEYSIGHT)
    # 0.075% + 100 * (0.0025 / 500 + 2.5e-9 * 500).
    fraction = 0.00075625
    assert result.values.drop(_MAG, _PHASE).equals(plain.values)
    assert result.values[_MAG][0] == pytest.approx(500 * fraction)
    assert result.values[_PHASE][0] == pytest.approx(degrees(fraction))
    assert result.envelope["accuracy"]["source"].startswith("Keysight E4990A")
    assert result.envelope["accuracy"]["conditions"]["setup_reference"] == _KEYSIGHT.setup_reference
    assert result.envelope["uncertainty_status"] == "not_evaluated"
    assert "uncertainty" not in result.envelope
    assert _MAG not in plain.values.columns
    assert result.uncertainty is None and isinstance(result, NativeMeasurementResult)
    assert not isinstance(plain, NativeMeasurementResult)


@pytest.mark.parametrize(
    ("changes", "settings"),
    [
        ({"f": 10_000_001}, _KEYSIGHT),  # Typical-only frequency regime.
        ({"f": 19}, _KEYSIGHT),
        ({"z": 0j}, _KEYSIGHT),
        ({}, replace(_KEYSIGHT, voltage_v_rms=0.6)),
        ({}, replace(_KEYSIGHT, dc_bias_enabled=True)),
        ({}, replace(_KEYSIGHT, temperature_c=29)),
        ({}, replace(_KEYSIGHT, warmup_minutes=89.999)),
        ({}, replace(_KEYSIGHT, dc_current_range_a=0.005)),
    ],
)
def test_e4990a_outside_supported_conditions_preserves_point_without_bound(changes, settings):
    reading = _point("E4990A", **changes)
    result = reading.to_measurement_result(accuracy=settings)
    assert result.values[_MAG][0] is None and result.values[_PHASE][0] is None
    assert result.envelope["accuracy"]["applicable_points"] == 0
    assert result.values["frequency_hz"][0] == reading.frequency_hz
    with pytest.raises(ValueError, match="no applicable rectangular bound"):
        reading.to_measurement_result(accuracy=settings, rectangular_type_b="magnitude")


def test_hioki_reproduces_catalog_500_ohm_example_and_applies_c_d_e():
    reading = _point("IM3570", status=0)
    result = reading.to_measurement_result(accuracy=_HIOKI)
    # Catalog §: 1 kΩ range at 10 kHz: ±0.12%rdg and ±0.088° at C=D=E=F=G=1.
    assert result.values[_MAG][0] == pytest.approx(0.6)
    assert result.values[_PHASE][0] == pytest.approx(0.088)
    changed = replace(_HIOKI, voltage_v_rms=0.1, speed_step=3, cable_length_m=1)
    adjusted = reading.to_measurement_result(accuracy=changed)
    assert adjusted.values[_MAG][0] == pytest.approx(3.6)  # C=2, D=2, E=1.5
    assert adjusted.values[_PHASE][0] == pytest.approx(0.528)
    low_range = _point("IM3570", z=complex(100), status=0).to_measurement_result(
        accuracy=replace(_HIOKI, range_ohm=300)
    )
    assert low_range.values[_MAG][0] == pytest.approx(0.12)
    assert low_range.values[_PHASE][0] == pytest.approx(0.07)


def test_hioki_sweep_leaves_unknown_status_range_or_conditions_unbounded():
    valid = _point("IM3570", status=0)
    readings = (
        valid,
        replace(valid, point=2, frequency_hz=10_001),
        replace(valid, point=3, status=2),
        replace(valid, point=4, impedance_ohm=600_000j),
        replace(valid, point=5, status=None),
    )
    sweep = ImpedanceSweep(readings, 1, _model="IM3570")
    result = sweep.to_measurement_result(accuracy=_HIOKI)
    assert result.values[_MAG].to_list() == [pytest.approx(0.6), None, None, None, None]
    assert result.values["status"].to_list() == [0, 0, 2, 0, None]
    assert result.envelope["accuracy"]["applicable_points"] == 1
    for settings in (
        replace(_HIOKI, relative_humidity_percent=81),
        replace(_HIOKI, warmup_minutes=59),
        replace(_HIOKI, dc_bias_enabled=True),
        replace(_HIOKI, range_ohm=1e6),
    ):
        assert valid.to_measurement_result(accuracy=settings).values[_MAG][0] is None
    with pytest.raises(ValueError, match="match the model"):
        valid.to_measurement_result(accuracy=_KEYSIGHT)
    with pytest.raises(ValueError, match="documented setup reference"):
        valid.to_measurement_result(accuracy=replace(_HIOKI, setup_reference=" "))
    with pytest.raises(ValueError, match="finite"):
        valid.to_measurement_result(accuracy=replace(_HIOKI, temperature_c=float("nan")))
    with pytest.raises(ValueError, match="match the model"):
        replace(valid, _model=None).to_measurement_result(accuracy=_HIOKI)


@pytest.mark.parametrize(
    "component,unit,half_width", [("magnitude", "ohm", 0.6), ("phase", "deg", 0.088)]
)
def test_explicit_rectangular_type_b_single_component_and_database(
    tmp_path, component, unit, half_width
):
    reading = _point("IM3570", status=0)
    result = reading.to_measurement_result(accuracy=_HIOKI, rectangular_type_b=component)
    payload = result.envelope["uncertainty"]
    assert payload["kind"] == "quantity"
    quantity = result.uncertainty
    assert isinstance(quantity, Quantity)
    assert quantity.nominal == (
        reading.magnitude_ohm if component == "magnitude" else reading.phase_deg
    )
    assert quantity.unit == unit
    assert quantity.u == pytest.approx(half_width / sqrt(3))
    atoms = list(quantity.registry.atoms.values())
    assert len(atoms) == 1
    assert atoms[0].distribution == Distribution.RECTANGULAR and atoms[0].kind == Kind.TYPE_B
    assert (
        atoms[0].traceability is not None
        and not atoms[0].traceability.supports_si_traceability_claim
    )
    assert result.envelope["uncertainty_status"] == "partial_type_b"
    with MeasurementDatabase(tmp_path / "impedance.db") as db:
        restored = db.retrieve_measurement(db.store_measurement(None, result))
    assert restored.values.equals(result.values)
    assert restored.envelope == result.envelope
    assert isinstance(restored.uncertainty, Quantity)
    assert restored.uncertainty.u == pytest.approx(quantity.u)
    experiment = Experiment("native impedance trial")
    experiment.add_trial(result)
    row = experiment.data["result"][0].struct.unnest()
    assert row.equals(result.values)
    metadata = json.loads(experiment.data["result__measurement"][0])
    assert metadata["result"]["envelope"] == result.envelope


def test_rectangular_phase_model_refuses_a_phase_interval_crossing_wrap():
    reading = _point("IM3570", z=-500 + 0j, status=0)
    with pytest.raises(ValueError, match="no applicable rectangular bound"):
        reading.to_measurement_result(accuracy=_HIOKI, rectangular_type_b="phase")
    with pytest.raises(ValueError, match="accuracy conditions"):
        reading.to_measurement_result(rectangular_type_b="phase")
