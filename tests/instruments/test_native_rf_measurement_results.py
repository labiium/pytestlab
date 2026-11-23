"""Offline checks for the native result adapters, not instrument qualification."""

from datetime import UTC
from datetime import datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from pytestlab import MeasurementResult
from pytestlab.config.loader import load_device_profile
from pytestlab.experiments import MeasurementDatabase
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceMeasurementSweep
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceParameter
from pytestlab.instruments.PowerMeter import PowerInputReflection
from pytestlab.instruments.PowerMeter import PowerMeter
from tests.instruments.test_rf_power_meter import _BUFFER
from tests.instruments.test_rf_power_meter import _KEY_VERIFIED
from tests.instruments.test_rf_power_meter import _TRACE
from tests.instruments.test_rf_power_meter import _TraceTranscript
from tests.instruments.test_rf_power_meter import _VerifiedTranscript
from tests.unit.test_impedance_analyzer import KEYSIGHT_SWEEP
from tests.unit.test_impedance_analyzer import _instrument


@pytest.mark.parametrize("method", ["measure_power", "acquire_power"])
def test_power_scalar_keeps_quantity_labels_and_receipt_time(method):
    backend = _VerifiedTranscript(_KEY_VERIFIED)
    meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), backend)
    before = datetime.now(UTC).timestamp()
    raw = getattr(meter, method)(1, unit="mW")
    after = datetime.now(UTC).timestamp()
    prior = list(backend.events)
    result = raw.to_measurement_result()
    assert isinstance(result, MeasurementResult)
    assert result.nominal == pytest.approx(raw.value)
    assert (result.instrument, result.units, result.measurement_type) == (
        "U2000A",
        "mW",
        "rf_power",
    )
    assert result.envelope["correction_frequency_hz"] == 2.4e9
    assert result.envelope["timestamp_kind"] == "host_receipt"
    assert before <= result.timestamp <= after
    assert result.envelope["uncertainty_status"] == "not_evaluated"
    assert result.sigma is None and backend.events == prior


@pytest.mark.parametrize("kind", ["buffer", "trace"])
def test_power_samples_use_indices_and_do_not_invent_a_clock(kind):
    if kind == "buffer":
        meter = PowerMeter(
            load_device_profile("rohdeschwarz/NRP18AN"), _VerifiedTranscript(_BUFFER)
        )
        raw = meter.acquire_power_buffer(unit="mW")
    else:
        meter = PowerMeter(load_device_profile("keysight/U2000A_PM"), _TraceTranscript(_TRACE))
        raw = meter.acquire_power_trace(unit="mW")
    result = raw.to_measurement_result(instrument="rf")
    assert result.instrument == "rf" and result.units == "mW"
    assert result.measurement_type == f"rf_power_{kind}"
    assert result.values.schema == {"sample_index": pl.Int64, "power": pl.Float64}
    assert result.values["sample_index"].to_list() == list(range(len(raw.values)))
    assert result.values["power"].to_list() == list(raw.values)
    assert result.timestamp == raw.received_at_utc.timestamp()
    assert result.sampling_rate is None and result.sigma is None
    if kind == "trace":
        assert result.envelope["time_window_s"] == list(raw.settings.time_window_s)
        assert result.envelope["resolution"] == raw.resolution


def test_reflection_preserves_reported_expanded_uncertainty_without_inventing_phase_uncertainty(
    tmp_path,
):
    raw = PowerInputReflection(2.4e9, 0.22, -35.0, 0.005, "sensor_input", None)
    result = raw.to_measurement_result()
    assert result.values["expanded_magnitude_uncertainty"].item() == 0.005
    assert result.envelope["expanded_magnitude_uncertainty_coverage_factor"] == 2
    assert result.envelope["uncertainty_status"] == "instrument_reported"
    assert result.envelope["column_units"]["phase_deg"] == "deg"
    assert result.sigma is None
    with MeasurementDatabase(tmp_path / "reflection") as db:
        restored = db.retrieve_measurement(db.store_measurement(None, result))
    for record in (result, restored):
        assert record.uncertainty is not None
        assert record.uncertainty.unit == "1"
        assert record.uncertainty.nominal == 0.22
        assert record.uncertainty.u == pytest.approx(0.005 / 2)
        assert "reflection magnitude" in record.uncertainty.provenance.origin_detail
        assert record.values["phase_deg"].item() == -35.0


def test_impedance_point_and_sweep_keep_native_complex_values_and_status():
    analyzer, backend = _instrument("keysight/E4990A", KEYSIGHT_SWEEP)
    raw_point = analyzer.read_impedance(2)
    raw_sweep = analyzer.read_impedance_sweep()
    before = list(backend.mock_calls)
    point = raw_point.to_measurement_result()
    sweep = raw_sweep.to_measurement_result()
    assert point.instrument == sweep.instrument == "E4990A"
    assert point.envelope["timestamp_kind"] == sweep.envelope["timestamp_kind"] == "host_receipt"
    assert point.timestamp <= sweep.timestamp
    assert point.values["impedance_real_ohm"].item() == 30.0
    assert point.values["impedance_imag_ohm"].item() == -40.0
    assert point.values["status"].item() is None and point.values["fresh"].item() is None
    assert_frame_equal(sweep.values, raw_sweep.to_dataframe())
    assert sweep.envelope["acquisition"] == "held"
    assert point.sigma is None and sweep.sigma is None
    assert backend.mock_calls == before


def test_impedance_scalar_trace_uses_its_parameter_and_engineering_unit():
    raw = ImpedanceMeasurementSweep(ImpedanceParameter.PHASE, (1e3, 2e3), (-45.0, 12.0), 1, (0, 0))
    result = raw.to_measurement_result(instrument="ia")
    assert result.instrument == "ia"
    assert result.units == "deg"
    assert result.envelope["parameter"] == raw.parameter.value
    assert result.envelope["column_units"] == {"frequency_hz": "Hz", "value": "deg"}
    assert result.envelope["timestamp_kind"] == "conversion"
    assert_frame_equal(result.values, raw.to_dataframe())
