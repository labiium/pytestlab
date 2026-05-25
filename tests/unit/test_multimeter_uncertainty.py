"""Unit tests for multimeter uncertainty calculation logic."""

from unittest.mock import Mock

from pytestlab.config.multimeter_config import AccuracySpec
from pytestlab.config.multimeter_config import FunctionSpec
from pytestlab.config.multimeter_config import MeasurementFunctionsSpec
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.config.multimeter_config import RangeSpec
from pytestlab.instruments.Multimeter import DMMFunction
from pytestlab.instruments.Multimeter import Multimeter


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
        role="measurement",
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy=AccuracySpec(percent_reading=0.1, percent_range=0.05),
                    ),
                    RangeSpec(
                        nominal_V=10.0,
                        accuracy=AccuracySpec(percent_reading=0.2, percent_range=0.1),
                    ),
                ]
            )
        ),
    )

    # Create multimeter instance
    multimeter = Multimeter(config=config, backend=mock_backend)

    # Mock the get_config method to return a known range
    multimeter.get_config = Mock(return_value=Mock(range_value=1.0))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter.scpi_engine = mock_scpi_engine

    # Test the uncertainty calculation
    measurement = multimeter.measure(DMMFunction.VOLTAGE_DC)

    # Verify that the measurement has uncertainty (should be a UFloat)
    assert hasattr(measurement.values, "n")  # nominal value
    assert hasattr(measurement.values, "s")  # standard deviation
    assert measurement.units == "V"
    assert measurement.measurement_type == "Volt Dc"  # Based on 'VOLT:DC' enum value


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
        role="measurement",
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy=AccuracySpec(percent_reading=0.1, percent_range=0.05),
                    )
                ]
            ),
            dc_current=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_A=0.1, accuracy=AccuracySpec(percent_reading=0.2, percent_range=0.1)
                    )
                ]
            ),
            resistance_4wire=FunctionSpec(
                ranges=[
                    RangeSpec(
                        nominal_ohm=1000.0,
                        accuracy=AccuracySpec(percent_reading=0.3, percent_range=0.15),
                    )
                ]
            ),
        ),
    )

    multimeter = Multimeter(config=config, backend=mock_backend)
    multimeter.get_config = Mock(return_value=Mock(range_value=1.0))

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


def test_multimeter_no_uncertainty_when_no_spec():
    """Test that the multimeter returns a float when no accuracy specification is available."""

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
        role="measurement",
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
    multimeter.get_config = Mock(return_value=Mock(range_value=1.0))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter.scpi_engine = mock_scpi_engine

    # Test measurement without accuracy spec
    measurement = multimeter.measure(DMMFunction.VOLTAGE_DC)

    # Should return a regular float, not UFloat
    assert isinstance(measurement.values, float)
    assert measurement.units == "V"
