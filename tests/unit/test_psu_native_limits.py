import pytest

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.uncertainty_adapters import psu_measurement_context
from pytestlab.uncertainty.metrology import CalibrationCertificate


@pytest.fixture
def supply_with_command_log():
    supply = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
    commands = []
    supply._send_command = commands.append
    return supply, commands


@pytest.mark.parametrize(
    ("channel", "voltage"),
    [(1, 6.18), (2, 30.9), (3, 30.9)],
)
def test_voltage_accepts_manual_programmable_maximum(supply_with_command_log, channel, voltage):
    supply, commands = supply_with_command_log

    supply.set_voltage(channel, voltage)

    assert commands == [f"VOLT {voltage}, (@{channel})"]


@pytest.mark.parametrize(
    ("channel", "current"),
    [(1, 5.15), (2, 1.03), (3, 1.03)],
)
def test_current_accepts_manual_programmable_maximum(supply_with_command_log, channel, current):
    supply, commands = supply_with_command_log

    supply.set_current(channel, current)

    assert commands == [f"CURR {current}, (@{channel})"]


@pytest.mark.parametrize("channel,current", [(1, 0.002), (2, 0.001), (3, 0.001)])
def test_current_accepts_channel_specific_minimum(supply_with_command_log, channel, current):
    supply, commands = supply_with_command_log

    supply.set_current(channel, current)

    assert commands == [f"CURR {current}, (@{channel})"]


@pytest.mark.parametrize(
    ("channel", "current"),
    [(1, 0.0), (1, 0.001), (2, 0.0), (2, 0.0005), (3, 0.0), (3, 0.0005)],
)
def test_current_rejects_below_channel_minimum_before_io(supply_with_command_log, channel, current):
    supply, commands = supply_with_command_log

    with pytest.raises(InstrumentParameterError):
        supply.set_current(channel, current)

    assert commands == []


@pytest.mark.parametrize(
    ("operation", "channel", "value"),
    [
        ("set_voltage", 1, 6.1801),
        ("set_voltage", 2, 30.9001),
        ("set_voltage", 3, 30.9001),
        ("set_current", 1, 5.1501),
        ("set_current", 2, 1.0301),
        ("set_current", 3, 1.0301),
    ],
)
def test_setter_rejects_just_above_channel_max_before_io(
    supply_with_command_log, operation, channel, value
):
    supply, commands = supply_with_command_log
    setter = getattr(supply, operation)

    with pytest.raises(InstrumentParameterError):
        setter(channel, value)

    assert commands == []


@pytest.mark.parametrize(
    ("operation", "channel", "parameter", "expected_max"),
    [
        ("set_voltage", 1, "voltage", 6.18),
        ("set_voltage", 2, "voltage", 30.9),
        ("set_voltage", 3, "voltage", 30.9),
        ("set_current", 1, "current", 5.15),
        ("set_current", 2, "current", 1.03),
        ("set_current", 3, "current", 1.03),
    ],
)
def test_operation_description_reports_selected_channel_maximum(
    supply_with_command_log, operation, channel, parameter, expected_max
):
    supply, _ = supply_with_command_log

    description = supply.describe_operation(operation, context={"channel": channel})

    assert description["parameters"][parameter]["constraints"]["max"] == expected_max


@pytest.mark.parametrize("channel,expected_min", [(1, 0.002), (2, 0.001), (3, 0.001)])
def test_operation_description_reports_selected_channel_current_minimum(
    supply_with_command_log, channel, expected_min
):
    supply, _ = supply_with_command_log

    description = supply.describe_operation("set_current", context={"channel": channel})

    assert description["parameters"]["current"]["constraints"]["min"] == expected_min


@pytest.mark.parametrize("channel,expected_min", [(1, 0.002), (2, 0.001), (3, 0.001)])
def test_channel_current_limit_range_reports_native_minimum(
    supply_with_command_log, channel, expected_min
):
    supply, _ = supply_with_command_log

    assert supply.config.channels[channel - 1].current_limit_range.min == expected_min


@pytest.mark.parametrize(
    ("channel", "voltage_max", "current_min", "current_max", "nominal_rating"),
    [
        (1, 6.18, 0.002, 5.15, "0–6 V, 0–5 A"),
        (2, 30.9, 0.001, 1.03, "0–30 V, 0–1 A"),
        (3, 30.9, 0.001, 1.03, "0–30 V, 0–1 A"),
    ],
)
def test_channel_ranges_report_accepted_setpoints_and_preserve_nominal_ratings(
    supply_with_command_log, channel, voltage_max, current_min, current_max, nominal_rating
):
    supply, _ = supply_with_command_log
    channel_spec = supply.config.channels[channel - 1]

    assert channel_spec.voltage_range.max == voltage_max
    assert channel_spec.current_limit_range.min == current_min
    assert channel_spec.current_limit_range.max == current_max
    assert nominal_rating in channel_spec.description
    assert "accepted setpoints" in channel_spec.description


def test_programming_headroom_does_not_change_nominal_calibration_context(
    supply_with_command_log,
):
    supply, commands = supply_with_command_log
    supply.config.calibration_certificates = [
        CalibrationCertificate(
            certificate_id="nominal-range-certificate",
            accreditation_id="LAB-123",
            entries=[
                {
                    "function": "read_voltage",
                    "channel": 1,
                    "range_value": 6.0,
                    "unit": "V",
                    "reference_standard": "nominal 6 V range standard",
                }
            ],
        )
    ]

    supply.set_voltage(1, 6.18)
    context = psu_measurement_context(
        supply.config,
        channel=1,
        reading=6.0,
        unit="V",
        function="read_voltage",
    )

    assert commands == ["VOLT 6.18, (@1)"]
    assert context.range_value == 6.0
    assert context.traceability is not None
    assert context.traceability.certificate_id == "nominal-range-certificate"


@pytest.mark.parametrize(("channel", "below_min"), [(1, 0.001), (2, 0.0005), (3, 0.0005)])
def test_channel_set_rejects_current_below_min_before_any_write(
    supply_with_command_log, channel, below_min
):
    supply, commands = supply_with_command_log

    with pytest.raises(InstrumentParameterError):
        supply.channel(channel).set(voltage=1.0, current_limit=below_min)

    assert commands == []


def test_channel_set_validates_all_setpoints_before_first_write(supply_with_command_log):
    supply, commands = supply_with_command_log

    with pytest.raises(InstrumentParameterError):
        supply.channel(2).set(voltage=5.0, current_limit=1.04)

    assert commands == []


def test_channel_three_accepts_positive_current(supply_with_command_log):
    supply, commands = supply_with_command_log

    supply.set_current(3, 0.25)

    assert commands == ["CURR 0.25, (@3)"]
