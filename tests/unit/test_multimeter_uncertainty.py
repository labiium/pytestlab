"""Unit tests for multimeter uncertainty calculation logic."""

from unittest.mock import Mock

import pytest

from pytestlab.config.device_config import DeviceRole
from pytestlab.config.multimeter_config import AccuracySpec
from pytestlab.config.multimeter_config import FunctionSpec
from pytestlab.config.multimeter_config import MeasurementFunctionsSpec
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.config.multimeter_config import RangeSpec
from pytestlab.instruments.Multimeter import DMMFunction
from pytestlab.instruments.Multimeter import Multimeter
from pytestlab.uncertainty import Quantity as MeasurementQuantity


def test_multimeter_uncertainty_calculation():
    """Test that the multimeter correctly calculates uncertainty from range specifications."""

    # Create a mock multimeter with a simple configuration
    mock_backend = Mock()
    mock_backend.write = Mock()

    # Mock different responses for different queries
    def mock_query(query, delay=None):
        if "SYSTem:ERRor" in query:
            return '0,"No error"'
        elif "READ" in query or "MEASURE" in query:
            return "0.5"
        else:
            return "OK"

    mock_backend.query = Mock(side_effect=mock_query)

    # Create a simple multimeter config with dc_voltage function
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy=AccuracySpec(reading_percent=0.1, range_percent=0.05),
                    ),
                    RangeSpec(
                        nominal_V=10.0,
                        accuracy=AccuracySpec(reading_percent=0.2, range_percent=0.1),
                    ),
                ]
            )
        ),
    )

    # Create multimeter instance
    multimeter = Multimeter(config=config, backend=mock_backend)

    # Mock the get_config method to return a known range
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter.scpi_engine = mock_scpi_engine

    # Test the uncertainty calculation
    measurement = multimeter.measure(DMMFunction.VOLTAGE_DC)

    # Verify that the measurement carries native uncertainty metadata.
    assert hasattr(measurement.values, "n")  # nominal value
    assert hasattr(measurement.values, "s")  # standard deviation
    assert measurement.units == "V"
    assert measurement.measurement_type == "Volt Dc"  # Based on 'VOLT:DC' enum value


def test_uncertainty_source_key_is_instance_unique_without_hardware_identity():
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
    )
    first = Multimeter(config=config, backend=Mock(write=Mock(), query=Mock()))
    second = Multimeter(config=config, backend=Mock(write=Mock(), query=Mock()))

    assert first._uncertainty_source_key() == first._uncertainty_source_key()
    assert first._uncertainty_source_key() != second._uncertainty_source_key()


def test_multimeter_range_field_detection():
    """Test that the multimeter correctly detects range fields for different function types."""

    mock_backend = Mock()
    mock_backend.write = Mock()

    # Mock different responses for different queries
    def mock_query(query, delay=None):
        if "SYSTem:ERRor" in query:
            return '0,"No error"'
        elif "READ" in query or "MEASURE" in query:
            return "0.5"
        else:
            return "OK"

    mock_backend.query = Mock(side_effect=mock_query)

    # Create config with different function types
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy=AccuracySpec(reading_percent=0.1, range_percent=0.05),
                    )
                ]
            ),
            dc_current=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_A=0.1, accuracy=AccuracySpec(reading_percent=0.2, range_percent=0.1)
                    )
                ]
            ),
            resistance_4wire=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_ohm=1000.0,
                        accuracy=AccuracySpec(reading_percent=0.3, range_percent=0.15),
                    )
                ]
            ),
        ),
    )

    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter.scpi_engine = mock_scpi_engine

    # Test voltage measurement (should use nominal_V)
    voltage_measurement = multimeter.measure(DMMFunction.VOLTAGE_DC)
    assert voltage_measurement.units == "V"

    # Test current measurement (should use nominal_A)
    current_measurement = multimeter.measure(DMMFunction.CURRENT_DC)
    assert current_measurement.units == "A"

    # Test resistance measurement (should use nominal_ohm)
    resistance_measurement = multimeter.measure(DMMFunction.FRESISTANCE)
    assert resistance_measurement.units == "Ω"


def test_multimeter_accepts_profile_loaded_advanced_uncertainty_model():
    mock_backend = Mock()
    mock_backend.write = Mock()

    def mock_query(query, delay=None):
        if "SYSTem:ERRor" in query:
            return '0,"No error"'
        if "READ" in query or "MEASURE" in query:
            return "0.5"
        return "OK"

    mock_backend.query = Mock(side_effect=mock_query)

    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy={
                            "model": "expression",
                            "expression": "0.01*reading + 0.001*range",
                            "distribution": "standard",
                        },
                    )
                ]
            )
        ),
        calibration_certificates=[
            {
                "certificate_id": "CAL-DMM-1",
                "issuing_lab": "Accredited Lab",
                "accreditation_id": "LAB-1",
                "entries": [{"function": "VOLT:DC", "range_value": 1.0, "unit": "V"}],
            }
        ],
    )

    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))
    multimeter.scpi_engine = Mock(build=Mock(return_value=["READ?"]))

    measurement = multimeter.measure(DMMFunction.VOLTAGE_DC)

    assert isinstance(measurement.values, MeasurementQuantity)
    assert measurement.values.u == pytest.approx(0.006)
    assert measurement.values.measurement_model is not None
    assert measurement.values.measurement_model.function == "VOLT:DC"
    assert measurement.values.provenance is not None
    assert measurement.values.provenance.data_origin.value == "measured"
    budget = measurement.values.budget()
    assert any(entry.label == "expression" for entry in budget.entries)
    assert all(entry.traceability is not None for entry in budget.entries)
    assert {entry.traceability.certificate_id for entry in budget.entries} == {"CAL-DMM-1"}


def test_multimeter_nominal_non_report_grade_quantity_when_no_spec():
    """Missing accuracy metadata returns an explicit non-report-grade Quantity."""

    mock_backend = Mock()
    mock_backend.write = Mock()

    # Mock different responses for different queries
    def mock_query(query, delay=None):
        if "SYSTem:ERRor" in query:
            return '0,"No error"'
        elif "READ" in query or "MEASURE" in query:
            return "0.5"
        else:
            return "OK"

    mock_backend.query = Mock(side_effect=mock_query)

    # Create config without accuracy specifications
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        # No accuracy field
                    )
                ]
            )
        ),
    )

    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter.scpi_engine = mock_scpi_engine

    # Test measurement without accuracy spec
    measurement = multimeter.measure(DMMFunction.VOLTAGE_DC)

    assert isinstance(measurement.values, MeasurementQuantity)
    assert measurement.values.nominal == pytest.approx(0.5)
    assert measurement.values.u == pytest.approx(0.0)
    assert not measurement.values.is_report_grade
    assert any(
        "no applicable accuracy specification" in blocker
        for blocker in measurement.values.report_grade_blockers()
    )
    assert measurement.units == "V"


def test_multimeter_strict_uncertainty_raises_model_errors():
    mock_backend = Mock()
    mock_backend.write = Mock()
    mock_backend.query = Mock(
        side_effect=lambda query, delay=None: '0,"No error"' if "SYSTem:ERRor" in query else "0.5"
    )

    config = MultimeterConfig(
        manufacturer="Test",
        model="StrictDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        uncertainty_strict=True,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy={
                            "model": "expression",
                            "expression": "0.01*bandwidth",
                            "distribution": "standard",
                        },
                    )
                ]
            )
        ),
    )

    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))
    multimeter.scpi_engine = Mock(build=Mock(return_value=["READ?"]))

    with pytest.raises(ValueError, match="'bandwidth' is required"):
        multimeter.measure(DMMFunction.VOLTAGE_DC)


def test_multimeter_strict_uncertainty_allows_missing_range_context_as_non_report_grade():
    mock_backend = Mock()
    mock_backend.write = Mock()
    mock_backend.query = Mock(
        side_effect=lambda query, delay=None: '0,"No error"' if "SYSTem:ERRor" in query else "0.5"
    )

    config = MultimeterConfig(
        manufacturer="Test",
        model="StrictDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        uncertainty_strict=True,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        accuracy=AccuracySpec(range_percent=1.0),
                    )
                ]
            )
        ),
    )

    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))
    multimeter.scpi_engine = Mock(build=Mock(return_value=["READ?"]))

    measurement = multimeter.measure(DMMFunction.VOLTAGE_DC)

    assert isinstance(measurement.values, MeasurementQuantity)
    assert not measurement.values.is_report_grade
    assert any(
        "could not find a matching range specification" in blocker
        for blocker in measurement.values.report_grade_blockers()
    )
