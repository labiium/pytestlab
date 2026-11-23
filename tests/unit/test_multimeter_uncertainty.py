"""Unit tests for multimeter uncertainty calculation logic."""

from unittest.mock import Mock

import pytest

from pytestlab.config.device_config import DeviceRole
from pytestlab.config.multimeter_config import AccuracySpec
from pytestlab.config.multimeter_config import FunctionSpec
from pytestlab.config.multimeter_config import MeasurementFunctionsSpec
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.config.multimeter_config import RangeSpec
from pytestlab.instruments.Multimeter import Multimeter
from pytestlab.instruments.scpi_engine import SCPIEngine
from pytestlab.uncertainty import Quantity as MeasurementQuantity


def _profile_dmm(config: MultimeterConfig) -> MultimeterConfig:
    """Give synthetic DMM configs the same semantic contract as real profiles."""
    function_options = []
    range_options = [{"value": "AUTO", "transport": {"value": "AUTO"}}]
    functions = config.measurement_functions
    if functions is not None:
        for function_id, function in functions.model_dump(exclude_none=True).items():
            if not isinstance(function, dict):
                continue
            token = (function.get("transport") or {}).get("function_token")
            if token is None:
                continue
            function_options.append(
                {
                    "value": function_id,
                    "label": function.get("label"),
                    "unit": function.get("unit"),
                    "transport": {"value": token},
                }
            )
            for range_spec in function.get("ranges", []):
                nominal = next(
                    (value for key, value in range_spec.items() if key.startswith("nominal_")),
                    None,
                )
                if nominal is not None:
                    if not any(option["value"] == str(nominal) for option in range_options):
                        range_options.append(
                            {
                                "value": str(nominal),
                                "aliases": [str(float(nominal)).removesuffix(".0")],
                                "transport": {"value": nominal},
                            }
                        )
    config.operation_options = {
        "measure": {
            "transport": {"measure": "measure"},
            "parameters": {
                "function": {
                    "kind": "enum",
                    "options": function_options,
                    "bindings": [{"alias": "measure", "parameter": "function"}],
                },
                "range_val": {
                    "kind": "enum",
                    "required": False,
                    "transport_parameter": False,
                    "options": range_options,
                },
                "resolution": {
                    "kind": "open_string",
                    "required": False,
                    "strict": False,
                    "transport_parameter": False,
                },
            },
        }
    }
    return config


def _real_metadata_engine(mock_engine: Mock) -> Mock:
    """Keep command stubs while providing real profile-presence metadata."""
    real = SCPIEngine(
        {
            "commands": {"clear": {"template": "*CLS"}},
            "queries": {
                "measure": {"template": "MEASURE:{function} {range},{resolution}"},
                "get_error": {"template": "SYSTem:ERRor?"},
            },
        }
    )
    wrapped = Mock(wraps=real)
    source_build = mock_engine.build
    if source_build.side_effect is not None:
        wrapped.build.side_effect = source_build.side_effect
    else:
        wrapped.build.side_effect = lambda alias, **kwargs: (
            real.build(alias, **kwargs) if alias == "get_error" else source_build.return_value
        )
    return wrapped


def test_multimeter_uncertainty_calculation():
    """Test that the multimeter correctly calculates uncertainty from range specifications."""

    # Create a mock multimeter with a simple configuration
    mock_backend = Mock()
    mock_backend.write = Mock()

    # Mock different responses for different queries
    def mock_query(query, delay=None):
        if "ERR" in query.upper():
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
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy=AccuracySpec(reading_percent=0.1, range_percent=0.05),
                    ),
                    RangeSpec(
                        nominal_V=10.0,
                        accuracy=AccuracySpec(reading_percent=0.2, range_percent=0.1),
                    ),
                ],
            )
        ),
    )

    # Create multimeter instance
    config = _profile_dmm(config)
    multimeter = Multimeter(config=config, backend=mock_backend)

    # Mock the get_config method to return a known range
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter._scpi_engine = _real_metadata_engine(mock_scpi_engine)

    # Test the uncertainty calculation
    measurement = multimeter.measure("dc_voltage")

    # Verify that the measurement carries native uncertainty metadata.
    assert hasattr(measurement.values, "n")  # nominal value
    assert hasattr(measurement.values, "s")  # standard deviation
    assert measurement.units == "V"
    assert measurement.measurement_type == "DC voltage"


def test_autorange_uses_single_measure_query_without_preflight_io():
    """Autorange should rely on the normal post-command error check."""
    backend = Mock()

    def query(command, delay=None):
        if "ERR" in command.upper():
            return '0,"No error"'
        if "MEASURE" in command or "READ" in command:
            return "0.5"
        return "OK"

    backend.query.side_effect = query
    config = MultimeterConfig(
        model="TestDMM",
        manufacturer="Test",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
            )
        ),
    )
    config = _profile_dmm(config)
    config = _profile_dmm(config)
    dmm = Multimeter(config=config, backend=backend)
    engine = Mock()

    def build(alias, **kwargs):
        if alias == "measure":
            return ["MEASURE:VOLT:DC? AUTO,DEF"]
        if alias == "clear":
            return ["*CLS"]
        if alias == "get_error":
            return ["SYSTem:ERRor?"]
        raise KeyError(alias)

    engine.build.side_effect = build
    dmm._scpi_engine = _real_metadata_engine(engine)
    result = dmm.measure("dc_voltage", uncertainty=False)

    assert float(result.values) == pytest.approx(0.5)
    queried = [call.args[0] for call in backend.query.call_args_list]
    assert queried.count("MEASURE:VOLT:DC? AUTO,DEF") == 1
    assert not any("IDN" in command.upper() for command in queried)
    assert not any("READ" in command.upper() for command in queried)
    assert queried == ["MEASURE:VOLT:DC? AUTO,DEF", "SYSTem:ERRor?"]
    backend.write.assert_not_called()


def test_measure_requires_the_profile_measure_alias():
    """A DMM measurement is one profile-defined operation, not a fallback sequence."""
    backend = Mock()
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
            )
        ),
    )
    config = _profile_dmm(config)
    dmm = Multimeter(config=config, backend=backend)
    dmm._scpi_engine = _real_metadata_engine(Mock(build=Mock(side_effect=KeyError("measure"))))

    from pytestlab.errors import InstrumentConfigurationError

    with pytest.raises(InstrumentConfigurationError, match="'measure' SCPI alias"):
        dmm.measure("dc_voltage", uncertainty=False)

    backend.write.assert_not_called()
    backend.query.assert_not_called()


def test_exact_explicit_profile_range_avoids_redundant_config_query():
    backend = Mock()
    backend.query.side_effect = lambda command, delay=None: (
        '0,"No error"' if "ERRor" in command else "0.5"
    )
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_V=10.0,
                        accuracy=AccuracySpec(reading_percent=0.2, range_percent=0.1),
                    )
                ],
            )
        ),
    )
    config = _profile_dmm(config)
    dmm = Multimeter(config=config, backend=backend)
    object.__setattr__(
        dmm,
        "get_config",
        Mock(side_effect=AssertionError("fixed profile range is authoritative")),
    )
    engine = Mock()
    engine.build.side_effect = lambda alias, **kwargs: {
        "measure": ["MEASURE:VOLT:DC? 10,DEF"],
        "get_error": ["SYSTem:ERRor?"],
    }[alias]
    dmm._scpi_engine = _real_metadata_engine(engine)

    result = dmm.measure("dc_voltage", range_val="10")

    assert result.values.nominal_value == 0.5
    assert result.values.u > 0
    dmm.get_config.assert_not_called()
    assert [call.args[0] for call in backend.query.call_args_list] == [
        "MEASURE:VOLT:DC? 10,DEF",
        "SYSTem:ERRor?",
    ]


def test_non_profile_fixed_range_is_rejected_when_not_declared():
    backend = Mock()
    backend.query.side_effect = lambda command, delay=None: (
        '0,"No error"' if "ERRor" in command else "0.5"
    )
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[RangeSpec(nominal_V=10.0)],
            )
        ),
    )
    config = _profile_dmm(config)
    dmm = Multimeter(config=config, backend=backend)
    object.__setattr__(dmm, "get_config", Mock(return_value=Mock(range_value=10.0)))
    engine = Mock()
    engine.build.side_effect = lambda alias, **kwargs: {
        "measure": ["MEASURE:VOLT:DC? 9,DEF"],
        "get_error": ["SYSTem:ERRor?"],
    }[alias]
    dmm._scpi_engine = _real_metadata_engine(engine)

    with pytest.raises(ValueError, match="Unsupported semantic option"):
        dmm.measure("dc_voltage", range_val="9")

    dmm.get_config.assert_not_called()


def test_nominal_measurement_skips_uncertainty_range_work_but_keeps_error_check():
    backend = Mock()
    backend.query.side_effect = lambda command, delay=None: (
        '0,"No error"' if "ERRor" in command else "0.5"
    )
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[RangeSpec(nominal_V=10.0)],
            )
        ),
    )
    config = _profile_dmm(config)
    dmm = Multimeter(config=config, backend=backend)
    object.__setattr__(
        dmm,
        "get_config",
        Mock(side_effect=AssertionError("nominal measurement must not query configuration")),
    )
    engine = Mock()
    engine.build.side_effect = lambda alias, **kwargs: {
        "measure": ["MEASURE:VOLT:DC? 10,DEF"],
        "get_error": ["SYSTem:ERRor?"],
    }[alias]
    dmm._scpi_engine = _real_metadata_engine(engine)

    result = dmm.measure("dc_voltage", range_val="10", uncertainty=False)

    assert float(result) == pytest.approx(0.5)
    assert not isinstance(result.values, MeasurementQuantity)
    dmm.get_config.assert_not_called()
    assert [call.args[0] for call in backend.query.call_args_list] == [
        "MEASURE:VOLT:DC? 10,DEF",
        "SYSTem:ERRor?",
    ]


def test_uncertainty_source_key_is_instance_unique_without_hardware_identity():
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
            )
        ),
    )
    config = _profile_dmm(config)
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
        if "ERR" in query.upper():
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
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy=AccuracySpec(reading_percent=0.1, range_percent=0.05),
                    )
                ],
            ),
            dc_current=FunctionSpec(
                label="DC current",
                unit="A",
                transport={"function_token": "CURR:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_A=0.1, accuracy=AccuracySpec(reading_percent=0.2, range_percent=0.1)
                    )
                ],
            ),
            resistance_4wire=FunctionSpec(
                label="4-wire resistance",
                unit="Ω",
                transport={"function_token": "FRES", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_ohm=1000.0,
                        accuracy=AccuracySpec(reading_percent=0.3, range_percent=0.15),
                    )
                ],
            ),
        ),
    )

    config = _profile_dmm(config)
    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter._scpi_engine = _real_metadata_engine(mock_scpi_engine)

    # Test voltage measurement (should use nominal_V)
    voltage_measurement = multimeter.measure("dc_voltage")
    assert voltage_measurement.units == "V"

    # Test current measurement (should use nominal_A)
    current_measurement = multimeter.measure("dc_current")
    assert current_measurement.units == "A"

    # Test resistance measurement (should use nominal_ohm)
    resistance_measurement = multimeter.measure("resistance_4wire")
    assert resistance_measurement.units == "Ω"


def test_multimeter_accepts_profile_loaded_advanced_uncertainty_model():
    mock_backend = Mock()
    mock_backend.write = Mock()

    def mock_query(query, delay=None):
        if "ERR" in query.upper():
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
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy={
                            "model": "expression",
                            "expression": "0.01*reading + 0.001*range",
                            "distribution": "standard",
                        },
                    )
                ],
            )
        ),
        calibration_certificates=[
            {
                "certificate_id": "CAL-DMM-1",
                "issuing_lab": "Accredited Lab",
                "accreditation_id": "LAB-1",
                "entries": [{"function": "dc_voltage", "range_value": 1.0, "unit": "V"}],
            }
        ],
    )

    config = _profile_dmm(config)
    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))
    multimeter._scpi_engine = _real_metadata_engine(Mock(build=Mock(return_value=["READ?"])))

    measurement = multimeter.measure("dc_voltage")

    assert isinstance(measurement.values, MeasurementQuantity)
    assert measurement.values.u == pytest.approx(0.006)
    assert measurement.values.measurement_model is not None
    assert measurement.values.measurement_model.function == "dc_voltage"
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
        if "ERR" in query.upper():
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
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        # No accuracy field
                    )
                ],
            )
        ),
    )

    config = _profile_dmm(config)
    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))

    # Mock the SCPI engine to avoid actual SCPI communication
    mock_scpi_engine = Mock()
    mock_scpi_engine.build = Mock(return_value=["READ?"])
    multimeter._scpi_engine = _real_metadata_engine(mock_scpi_engine)

    # Test measurement without accuracy spec
    measurement = multimeter.measure("dc_voltage")

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
        side_effect=lambda query, delay=None: '0,"No error"' if "ERR" in query.upper() else "0.5"
    )

    config = MultimeterConfig(
        manufacturer="Test",
        model="StrictDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        uncertainty_strict=True,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy={
                            "model": "expression",
                            "expression": "0.01*bandwidth",
                            "distribution": "standard",
                        },
                    )
                ],
            )
        ),
    )

    config = _profile_dmm(config)
    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))
    multimeter._scpi_engine = _real_metadata_engine(Mock(build=Mock(return_value=["READ?"])))

    with pytest.raises(ValueError, match="'bandwidth' is required"):
        multimeter.measure("dc_voltage")


def test_multimeter_strict_uncertainty_allows_missing_range_context_as_non_report_grade():
    mock_backend = Mock()
    mock_backend.write = Mock()
    mock_backend.query = Mock(
        side_effect=lambda query, delay=None: '0,"No error"' if "ERR" in query.upper() else "0.5"
    )

    config = MultimeterConfig(
        manufacturer="Test",
        model="StrictDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        uncertainty_strict=True,
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="DC voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        accuracy=AccuracySpec(range_percent=1.0),
                    )
                ],
            )
        ),
    )

    config = _profile_dmm(config)
    multimeter = Multimeter(config=config, backend=mock_backend)
    object.__setattr__(multimeter, "get_config", Mock(return_value=Mock(range_value=1.0)))
    multimeter._scpi_engine = _real_metadata_engine(Mock(build=Mock(return_value=["READ?"])))

    measurement = multimeter.measure("dc_voltage")

    assert isinstance(measurement.values, MeasurementQuantity)
    assert not measurement.values.is_report_grade
    assert any(
        "could not find a matching range specification" in blocker
        for blocker in measurement.values.report_grade_blockers()
    )
