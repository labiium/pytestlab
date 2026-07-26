from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest
from uncertainties import ufloat
from uncertainties.core import UFloat

import pytestlab.uncertainty.budget as budget_mod
import pytestlab.uncertainty.units as units_mod
from pytestlab.config.device_config import DeviceRole
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.results import MeasurementResult
from pytestlab.experiments.uncertainty_serialization import deserialize_uncertain_value
from pytestlab.experiments.uncertainty_serialization import serialize_uncertain_value
from pytestlab.instruments.uncertainty_adapters import dc_load_measurement_context
from pytestlab.instruments.uncertainty_adapters import dc_load_range_value
from pytestlab.instruments.uncertainty_adapters import dc_load_readback_accuracy
from pytestlab.instruments.uncertainty_adapters import dmm_measurement_context
from pytestlab.instruments.uncertainty_adapters import dmm_range_value
from pytestlab.instruments.uncertainty_adapters import nonzero_uncertainty_quantity
from pytestlab.instruments.uncertainty_adapters import oscilloscope_measurement_context
from pytestlab.instruments.uncertainty_adapters import psu_measurement_context
from pytestlab.uncertainty import AtomRegistry
from pytestlab.uncertainty import Distribution as UncertaintyDistribution
from pytestlab.uncertainty import Quantity as MeasurementQuantity
from pytestlab.uncertainty import UnitCompatibilityError
from pytestlab.uncertainty.specs import AccuracySpec
from pytestlab.uncertainty.specs import BandAccuracySpec
from pytestlab.uncertainty.specs import ExpressionAccuracySpec
from pytestlab.uncertainty.specs import RepeatabilityAccuracySpec
from pytestlab.uncertainty.specs import UncertaintyContext
from pytestlab.uncertainty.specs import standard_uncertainty_from_model


class RecordingLogger:
    def __init__(self) -> None:
        self.debugs: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def debug(self, message: str) -> None:
        self.debugs.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)


_HELPER_REGISTRY = AtomRegistry()


def test_uncertainty_strict_defaults_to_fail_loud():
    assert (
        InstrumentConfig(
            manufacturer="Test", model="X", device_type="instrument", role=DeviceRole.MEASUREMENT
        ).uncertainty_strict
        is True
    )


def test_pint_invalid_product_units_raise_unit_compatibility_error():
    if units_mod._UNIT_REGISTRY is None:
        pytest.skip("Pint is not installed in this environment")

    with pytest.raises(UnitCompatibilityError, match="Incompatible units"):
        units_mod.product_nominal(1.0, "definitely_not_a_unit", 2.0, "V", "mul")

    with pytest.raises(UnitCompatibilityError, match="Incompatible units"):
        units_mod.product_nominal(1.0, "V", 2.0, "definitely_not_a_unit", "truediv")


def test_product_units_keep_string_fallback_when_pint_is_unavailable(monkeypatch):
    monkeypatch.setattr(units_mod, "_UNIT_REGISTRY", None)

    assert units_mod.product_nominal(1.0, "made_up_unit", 2.0, "V", "mul") == (
        2.0,
        "made_up_unit*V",
        1.0,
    )
    assert units_mod.product_nominal(1.0, "V", 2.0, "made_up_unit", "truediv") == (
        0.5,
        "V/made_up_unit",
        1.0,
    )


def quantity(offset: float, unit: str = "V", nominal: float = 1.0) -> MeasurementQuantity:
    return AccuracySpec(
        offset=offset,
        distribution=UncertaintyDistribution.STANDARD,
        source="cal-sheet",
    ).quantity(nominal, unit=unit, registry=_HELPER_REGISTRY)


def test_adapter_nonzero_zero_and_error_paths_are_explicit():
    logger = RecordingLogger()
    context = UncertaintyContext(reading=1.0, unit="V")

    result = nonzero_uncertainty_quantity(
        AccuracySpec(offset=0.1, distribution=UncertaintyDistribution.STANDARD),
        context,
        logger=logger,
        label="nonzero",
    )
    assert isinstance(result, MeasurementQuantity)
    assert logger.debugs[-1].startswith("Applied nonzero")

    zero = nonzero_uncertainty_quantity(AccuracySpec(), context, logger=logger, label="zero")
    assert zero is None
    assert "u=0" in logger.debugs[-1]

    missing_range = nonzero_uncertainty_quantity(
        AccuracySpec(range_percent=1.0),
        context,
        logger=logger,
        label="bad-range",
        warning_level="info",
    )
    assert missing_range is None
    assert "range_value is required" in logger.infos[-1]

    with pytest.raises(ValueError, match="range_value is required"):
        nonzero_uncertainty_quantity(
            AccuracySpec(range_percent=1.0),
            context,
            logger=logger,
            label="strict-range",
            strict=True,
        )


def test_adapter_context_builders_cover_driver_return_shape_inputs():
    dmm_range = SimpleNamespace(nominal_V=10.0, max=None, max_val=None, resolution=0.001)
    assert dmm_range_value(SimpleNamespace(value="VOLT:DC"), dmm_range) == 10.0
    assert dmm_range_value("FREQ", SimpleNamespace(max=100.0, max_val=200.0)) == 100.0
    dmm_context = dmm_measurement_context(
        reading=5.0,
        unit="V",
        function=SimpleNamespace(value="VOLT:DC"),
        range_spec=dmm_range,
        measurement_type="Volt Dc",
    )
    assert dmm_context is not None
    assert dmm_context.metadata == {"measurement_type": "Volt Dc"}
    assert (
        dmm_measurement_context(
            reading=5.0,
            unit="V",
            function="VOLT:DC",
            range_spec=SimpleNamespace(max=None, max_val=None),
            measurement_type="Volt Dc",
        )
        is None
    )

    psu_config = SimpleNamespace(
        channels=[
            SimpleNamespace(
                voltage_range=SimpleNamespace(max=20.0, resolution=0.01),
                current_limit_range=SimpleNamespace(max=2.0, resolution=0.001),
            )
        ]
    )
    psu_context = psu_measurement_context(
        psu_config, channel=1, reading=1.5, unit="A", function="read_current"
    )
    assert psu_context.range_value == 2.0
    assert psu_context.resolution == 0.001

    scope_config = SimpleNamespace(
        bandwidth=100e6,
        channels=[SimpleNamespace(channel_range=SimpleNamespace(max_val=5.0, resolution=0.02))],
    )
    scope_context = oscilloscope_measurement_context(
        scope_config, channel=1, reading=2.0, unit="V", function="measure_vpp"
    )
    assert scope_context.range_value == 5.0
    assert scope_context.bandwidth == 100e6

    readback = SimpleNamespace(
        current_accuracy="current", voltage_accuracy="voltage", power_accuracy="power"
    )
    assert dc_load_range_value(SimpleNamespace(max_current_A=4.0), "A") == 4.0
    assert dc_load_range_value(SimpleNamespace(max_voltage_V=40.0), "V") == 40.0
    assert dc_load_range_value(SimpleNamespace(max=80.0), "W") == 80.0
    assert dc_load_readback_accuracy(readback, "current") == "current"
    assert dc_load_readback_accuracy(readback, "voltage") == "voltage"
    assert dc_load_readback_accuracy(readback, "power") == "power"
    assert dc_load_readback_accuracy(readback, "resistance") is None
    assert (
        dc_load_measurement_context(
            reading=9.0, unit="W", function="power", range_value=None, channel=2
        ).range_value
        is None
    )


def test_serializer_round_trips_all_uncertain_value_shapes(tmp_path):
    measured = quantity(0.2, nominal=3.3)
    payload, metadata = serialize_uncertain_value(measured)
    restored = deserialize_uncertain_value(payload, metadata)
    assert isinstance(restored, MeasurementQuantity)
    # Atom provenance survives the round trip.
    assert any(atom["source"] == "cal-sheet" for atom in restored.to_dict()["atoms"].values())

    scalar, scalar_meta = serialize_uncertain_value(ufloat(1.2, 0.03))
    scalar_restored = deserialize_uncertain_value(scalar, scalar_meta)
    assert scalar_restored.nominal_value == pytest.approx(1.2)
    assert scalar_restored.std_dev == pytest.approx(0.03)

    arr = np.array([[ufloat(1.0, 0.1), ufloat(2.0, 0.2)]], dtype=object)
    arr_payload, arr_meta = serialize_uncertain_value(arr)
    arr_restored = deserialize_uncertain_value(arr_payload, arr_meta)
    assert arr_restored.shape == (1, 2)
    assert arr_restored[0, 1].std_dev == pytest.approx(0.2)

    values = [ufloat(4.0, 0.4), ufloat(5.0, 0.5)]
    list_payload, list_meta = serialize_uncertain_value(values)
    list_restored = deserialize_uncertain_value(list_payload, list_meta)
    assert [item.nominal_value for item in list_restored] == [4.0, 5.0]

    plain_payload, plain_meta = serialize_uncertain_value(12.0)
    assert deserialize_uncertain_value(plain_payload, plain_meta) == 12.0

    with MeasurementDatabase(tmp_path / "ufloat_shapes") as db:
        key = db.store_measurement(
            None,
            MeasurementResult(values=arr, instrument="array", units="V", measurement_type="grid"),
        )
        db_restored = db.retrieve_measurement(key)
    restored_array = cast(np.ndarray, db_restored.values)
    assert restored_array[0, 0].nominal_value == pytest.approx(1.0)
    assert restored_array[0, 1].std_dev == pytest.approx(0.2)


def test_database_adds_metadata_column_to_existing_measurement_tables(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE measurements (
            codename TEXT PRIMARY KEY,
            instrument_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            value_data NPBLOB NOT NULL,
            units TEXT,
            measurement_type TEXT,
            notes TEXT
        );
    """)
    conn.close()

    with MeasurementDatabase(tmp_path / "legacy") as db:
        columns = {
            row[1] for row in db._get_connection().execute("PRAGMA table_info(measurements)")
        }
        assert "metadata" in columns
        key = db.store_measurement(
            None,
            MeasurementResult(
                values=ufloat(2.0, 0.2),
                instrument="legacy",
                units="V",
                measurement_type="voltage",
            ),
        )
        restored = db.retrieve_measurement(key)

    restored_value = cast(UFloat, restored.values)
    assert restored_value.nominal_value == pytest.approx(2.0)
    assert restored_value.std_dev == pytest.approx(0.2)


def test_scientific_edge_cases_and_provenance_are_preserved():
    context = UncertaintyContext(reading=-10.0, unit="V", range_value=20.0, resolution=0.001)
    budget = AccuracySpec(
        reading_ppm=1000.0,
        range_fraction=0.01,
        counts=3,
        distribution=UncertaintyDistribution.STANDARD,
        source="datasheet-page-7",
    ).evaluate(context)
    labels = {entry.label for entry in budget.entries}
    assert labels == {"gain", "range", "counts"}
    assert {entry.source for entry in budget.entries} == {"datasheet-page-7"}

    with pytest.raises(ValueError, match="range_value is required"):
        AccuracySpec(range_percent=1.0).evaluate(UncertaintyContext(reading=1.0, unit="V"))
    with pytest.raises(ValueError, match="resolution is required"):
        AccuracySpec(counts=1).evaluate(UncertaintyContext(reading=1.0, unit="V"))

    edge_band = BandAccuracySpec(
        variable="frequency",
        bands=[{"min": 10.0, "max": 20.0, "offset": 0.2, "distribution": "standard"}],
    )
    lo = edge_band.evaluate(UncertaintyContext(reading=1.0, unit="V", frequency=10.0))
    hi = edge_band.evaluate(UncertaintyContext(reading=1.0, unit="V", frequency=20.0))
    assert lo.entries[0].contribution == pytest.approx(0.2)
    assert hi.entries[0].contribution == pytest.approx(0.2)
    with pytest.raises(ValueError, match="frequency"):
        edge_band.evaluate(UncertaintyContext(reading=1.0, unit="V"))
    with pytest.raises(ValueError, match="No uncertainty band"):
        edge_band.evaluate(UncertaintyContext(reading=1.0, unit="V", frequency=21.0))

    with pytest.raises(ValueError, match="Unknown expression variable"):
        ExpressionAccuracySpec(expression="reading + missing").evaluate(
            UncertaintyContext(reading=1.0)
        )
    with pytest.raises(ValueError, match="Unsupported expression node"):
        ExpressionAccuracySpec(expression="max(reading, 1)").evaluate(
            UncertaintyContext(reading=1.0)
        )
    with pytest.raises(ValueError, match="'bandwidth' is required"):
        ExpressionAccuracySpec(expression="0.001*bandwidth").evaluate(
            UncertaintyContext(reading=1.0, unit="V")
        )
    zero_context = ExpressionAccuracySpec(
        expression="range + resolution + channel + sample_count + calibration_age_days",
        distribution=UncertaintyDistribution.STANDARD,
    ).evaluate(
        UncertaintyContext(
            reading=1.0,
            unit="V",
            range_value=0.0,
            resolution=0.0,
            channel=0,
            sample_count=0,
            calibration_age_days=0.0,
        )
    )
    assert zero_context.combined_standard_uncertainty == 0.0
    expression_budget = ExpressionAccuracySpec(
        expression="-sqrt(abs(reading)) + gain",
        parameters={"gain": 3.0},
        distribution=UncertaintyDistribution.STANDARD,
    ).evaluate(UncertaintyContext(reading=4.0, unit="V"))
    assert expression_budget.entries[0].contribution == pytest.approx(1.0)

    assert (
        standard_uncertainty_from_model(AccuracySpec(offset=0.5), UncertaintyContext(reading=1.0))
        > 0
    )


def test_monte_carlo_spec_behaves_as_composite_analytically():
    """MonteCarloAccuracySpec.evaluate now merges its components analytically."""

    from pytestlab.uncertainty.specs import MonteCarloAccuracySpec

    budget = MonteCarloAccuracySpec(
        components=[
            AccuracySpec(offset=0.1, distribution=UncertaintyDistribution.TRIANGULAR),
            AccuracySpec(
                offset=0.2, distribution=UncertaintyDistribution.NORMAL, coverage_factor=2.0
            ),
        ],
        samples=200,
        seed=7,
    ).evaluate(UncertaintyContext(reading=1.0, unit="V"), AtomRegistry())
    assert len(budget.entries) == 2
    assert budget.combined_standard_uncertainty > 0


def test_quantity_operations_cover_units_scalars_and_zero_nominal(monkeypatch):
    voltage = quantity(0.1, "V", 2.0)

    assert voltage.relative_u == pytest.approx(0.05)
    assert quantity(0.1, "V", 0.0).relative_u == float("inf")
    assert voltage.to_ufloat().std_dev == pytest.approx(0.1)
    assert float(voltage) == pytest.approx(2.0)
    assert int(voltage) == 2
    assert str(voltage).endswith(" V")

    assert (voltage - quantity(0.2, "V", 1.0)).nominal == pytest.approx(1.0)
    assert (voltage / 2).u == pytest.approx(0.05)
    assert (1 + voltage).nominal == pytest.approx(3.0)
    assert (5 - voltage).nominal == pytest.approx(3.0)
    assert (2 * voltage).u == pytest.approx(0.2)
    reciprocal = 2 / voltage
    assert reciprocal.nominal == pytest.approx(1.0)
    assert reciprocal.u == pytest.approx(0.05)
    # Same-registry operands required for arithmetic.
    shared = AtomRegistry()
    va = AccuracySpec(offset=0.1, distribution=UncertaintyDistribution.STANDARD).quantity(
        2.0, unit="V", registry=shared
    )
    ca = AccuracySpec(offset=0.01, distribution=UncertaintyDistribution.STANDARD).quantity(
        0.5, unit="A", registry=shared
    )
    ratio = va / ca
    assert ratio.u > 0

    monkeypatch.setattr(units_mod, "_UNIT_REGISTRY", None)
    fallback_product = va * ca
    assert fallback_product.unit == "V*A"
    assert (va / ca).unit == "V/A"
    same = AtomRegistry()
    a = AccuracySpec(offset=0.1, distribution=UncertaintyDistribution.STANDARD).quantity(
        1.0, unit="V", registry=same
    )
    b = AccuracySpec(offset=0.2, distribution=UncertaintyDistribution.STANDARD).quantity(
        2.0, unit="V", registry=same
    )
    assert (a + b).nominal == 3.0
    with pytest.raises(UnitCompatibilityError):
        _ = a + AccuracySpec(offset=0.1).quantity(1000.0, unit="mV", registry=same)


def test_scipy_fallback_is_default_only(monkeypatch):
    real_import_module = importlib.import_module

    def blocked_import(name: str, package: str | None = None):
        if name == "scipy.stats":
            raise ImportError("blocked for fallback test")
        return real_import_module(name, package)

    # u = 0.1 (standard offset), so expanded at k=2 is 0.2.
    budget = AccuracySpec(offset=0.1, distribution=UncertaintyDistribution.STANDARD).evaluate(
        UncertaintyContext(reading=1.0, unit="V"), AtomRegistry()
    )
    monkeypatch.setattr(budget_mod, "_SCIPY_STATS", None)
    monkeypatch.setattr(budget_mod.importlib, "import_module", blocked_import)

    assert budget.coverage_factor_for(0.95) == pytest.approx(2.0)
    assert budget.expanded_uncertainty(confidence=0.95) == pytest.approx(0.2)
    with pytest.raises(RuntimeError, match="scipy is required"):
        budget.coverage_factor_for(0.9)
    with pytest.raises(ValueError, match="between 0 and 1"):
        budget.coverage_factor_for(1.0)


def test_repeatability_without_standard_error_and_zero_budget_dof():
    empty = MeasurementQuantity.constant(1.0, "V").budget()
    assert empty.effective_degrees_of_freedom is None
    repeatability = RepeatabilityAccuracySpec(
        observations=[1.0, 1.2, 0.8],
        use_standard_error=False,
    ).evaluate(UncertaintyContext(reading=1.0, unit="V"), AtomRegistry())
    assert repeatability.entries[0].contribution == pytest.approx(0.2)
    assert repeatability.entries[0].kind == "type_a"
