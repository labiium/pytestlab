"""Offline result conveniences for held, fresh and legacy VNA data."""

import csv
import time

import polars as pl
import pytest

from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.instruments.VectorNetworkAnalyser import SParameterBin
from pytestlab.instruments.VectorNetworkAnalyser import SParameterData
from pytestlab.instruments.VectorNetworkAnalyser import SParameterTrace


@pytest.fixture
def instrument_result():
    return SParameterData(
        [100e6, 150e6, 200e6],
        [[0.3 + 0.4j, 0.4 - 0.7j, -0.2j], [0.1j, -0.1j, -0.3 + 0.4j]],
        ["S21", "S11"],
        axis_source="instrument",
        trace_identity_verified=True,
    )


def test_named_trace_preserves_slot_order_source_and_original_fields(instrument_result):
    result = instrument_result
    result.fresh = True
    trace = result.trace(" s11 ")
    assert trace == SParameterTrace(
        "S11", (100e6, 150e6, 200e6), (0.1j, -0.1j, -0.3 + 0.4j), "instrument", True, True
    )
    assert result.param_names == ["S21", "S11"]
    assert result.s_params[1] == list(trace.values)
    assert result.frequencies == list(trace.frequencies)
    with pytest.raises(KeyError, match="S12"):
        result.trace("S12")


@pytest.mark.parametrize(
    ("requested", "bin_frequency", "value"),
    [
        (100e6, 100e6, 0.3 + 0.4j),
        (125e6, 100e6, 0.3 + 0.4j),  # equally close, lower bin
        (125e6 + 1, 150e6, 0.4 - 0.7j),
        (150e6, 150e6, 0.4 - 0.7j),
        (200e6, 200e6, -0.2j),
    ],
)
def test_lookup_returns_actual_bin_not_requested_frequency(
    instrument_result, requested, bin_frequency, value
):
    assert instrument_result.trace("S21").at_frequency(requested) == SParameterBin(
        "S21", bin_frequency, value
    )


@pytest.mark.parametrize(
    "requested", [100e6 - 1, 200e6 + 1, float("nan"), float("inf"), True, "1e8"]
)
def test_lookup_refuses_extrapolation_and_non_numeric_frequency(instrument_result, requested):
    with pytest.raises(ValueError, match="measured span"):
        instrument_result.trace("S21").at_frequency(requested)


def test_legacy_nominal_result_can_export_but_not_claim_measured_bin(tmp_path):
    legacy = SParameterData([2.0], [[-1.25 + 2.5j]], ["S11"])
    trace = legacy.trace("s11")
    with pytest.raises(ValueError, match="instrument axis and verified trace"):
        trace.at_frequency(2.0)
    path = tmp_path / "legacy.csv"
    legacy.to_csv(path)
    with path.open(encoding="utf-8", newline="") as source:
        assert list(csv.DictReader(source)) == [
            {
                "frequency_hz": "2.0",
                "axis_source": "profile_nominal",
                "trace_identity_verified": "false",
                "fresh": "false",
                "S11_real": "-1.25",
                "S11_imag": "2.5",
            }
        ]


def test_export_keeps_trace_order_exact_complex_values_and_provenance(instrument_result, tmp_path):
    result = instrument_result
    result.fresh = True
    path = tmp_path / "sweep.csv"
    result.to_csv(path)
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        assert reader.fieldnames == [
            "frequency_hz",
            "axis_source",
            "trace_identity_verified",
            "fresh",
            "S21_real",
            "S21_imag",
            "S11_real",
            "S11_imag",
        ]
    assert [float(row["frequency_hz"]) for row in rows] == result.frequencies
    for name, expected in zip(result.param_names, result.s_params, strict=True):
        assert [
            complex(float(row[f"{name}_real"]), float(row[f"{name}_imag"])) for row in rows
        ] == (expected)
    assert all(
        (row["axis_source"], row["trace_identity_verified"], row["fresh"])
        == ("instrument", "true", "true")
        for row in rows
    )


def test_export_refuses_overwrite_by_default_and_accepts_explicit_overwrite(
    instrument_result, tmp_path
):
    path = tmp_path / "sweep.csv"
    path.write_text("existing")
    with pytest.raises(FileExistsError):
        instrument_result.to_csv(path)
    assert path.read_text() == "existing"
    instrument_result.to_csv(path, overwrite=True)
    assert path.read_text().startswith("frequency_hz,")


@pytest.mark.parametrize("fault", ["axis", "duplicate", "length", "nonfinite"])
def test_invalid_result_leaves_existing_file_intact(instrument_result, tmp_path, fault):
    result = instrument_result
    if fault == "axis":
        result.frequencies.reverse()
    elif fault == "duplicate":
        result.param_names[0] = "S11"
    elif fault == "length":
        result.s_params[0].pop()
    else:
        result.s_params[0][0] = complex("nan")
    path = tmp_path / "sweep.csv"
    path.write_text("existing")
    with pytest.raises(ValueError):
        result.to_csv(path, overwrite=True)
    assert path.read_text() == "existing"


def test_local_magnitude_extrema_and_phase_use_measured_bins(instrument_result):
    trace = instrument_result.trace("S21")
    result = trace.magnitude_extrema(start_hz=110e6, stop_hz=200e6)
    assert result.minimum.frequency_hz == 200e6
    assert result.maximum.frequency_hz == 150e6
    assert result.minimum.phase_deg == -90
    assert result.minimum.magnitude_db == pytest.approx(-13.97940009)
    assert result.maximum.magnitude_db == pytest.approx(-1.870866433)
    with pytest.raises(ValueError, match="No measured"):
        trace.magnitude_extrema(start_hz=110e6, stop_hz=120e6)


def test_zero_magnitude_and_equal_extrema_are_not_fabricated(instrument_result):
    instrument_result.s_params[0] = [0j, 1j, -1j]
    result = instrument_result.trace("S21").magnitude_extrema()
    assert result.minimum.magnitude_db == -float("inf")
    assert result.minimum.phase_deg is None
    assert result.maximum.frequency_hz == 150e6


def test_native_result_preserves_signed_float64_pairs_without_promoting_caller_flags(
    instrument_result, tmp_path
):
    instrument_result.fresh = True
    t = time.time()
    measurement = instrument_result.to_measurement_result()
    assert measurement.timestamp <= t
    assert instrument_result.to_measurement_result().timestamp == measurement.timestamp
    assert measurement.values.schema == dict.fromkeys(
        ["frequency_hz", "S21_real", "S21_imag", "S11_real", "S11_imag"], pl.Float64
    )
    assert measurement.values["frequency_hz"].to_list() == instrument_result.frequencies
    for name, expected in zip(
        instrument_result.param_names, instrument_result.s_params, strict=True
    ):
        assert [
            complex(i, q)
            for i, q in zip(
                measurement.values[f"{name}_real"], measurement.values[f"{name}_imag"], strict=True
            )
        ] == expected
    assert measurement.units == "1"
    assert measurement.envelope["uncertainty_status"] == "not_evaluated"
    meta = measurement.envelope["vna"]
    assert meta["capture_origin"] == "caller"
    assert meta["axis_source"] == "caller_supplied"
    assert not meta["fresh"] and not meta["trace_identity_verified"]
    assert meta["context"] is None and meta["identity"] is None

    with MeasurementDatabase(tmp_path / "vna") as db:
        key = db.store_measurement(None, instrument_result)
        restored = db.retrieve_measurement(key)
    assert restored.values.equals(measurement.values)
    assert restored.envelope == measurement.envelope
