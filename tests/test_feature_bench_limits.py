from __future__ import annotations

from types import SimpleNamespace

import pytest

from pytestlab.bench import SafeDeviceWrapper
from pytestlab.bench import SafetyLimitError
from pytestlab.config.bench_config import MeasurementPlanEntry
from pytestlab.config.bench_config import SafetyLimitChannel
from pytestlab.config.bench_config import SafetyLimits
from pytestlab.config.source_measure_config import SourceMeasureConfig
from pytestlab.experiments import MeasurementResult
from pytestlab.instruments.SourceMeasure import SourceMeasure
from pytestlab.measurement_plan import execute_declared_measurement


class IO:
    def __init__(self):
        self.calls = []

    def connect(self):
        pass

    def close(self):
        pass

    def disconnect(self):
        pass

    def write(self, cmd):
        self.calls.append(cmd)

    def query(self, cmd, delay=None):
        self.calls.append(cmd)
        return "N3I+1e-3"

    def query_raw(self, cmd, delay=None):
        return b""

    def get_timeout(self):
        return 2000

    def set_timeout(self, value):
        pass


def limited(maximum=2):
    def rating(lower, upper, units):
        return {"min": lower, "max": upper, "units": units}

    config = SourceMeasureConfig.model_validate(
        {
            "manufacturer": "Fictional",
            "model": "Synthetic SMU",
            "role": "source_measure",
            "capabilities": {"standard_commands": False, "error_queue": False},
            "channels": [
                {
                    "channel_id": 3,
                    "description": "Explicit synthetic channel",
                    "voltage_range": rating(-10, 10, "V"),
                    "current_range": rating(-1, 1, "A"),
                    "current_limit_range": rating(0, 0.1, "A"),
                    "voltage_compliance_range": rating(-10, 10, "V"),
                }
            ],
            "scpi": {
                "commands": {
                    "force_voltage": {"template": "VSET {channel} {voltage} {current_limit}"},
                    "force_current": {"template": "ISET {channel} {current} {voltage_compliance}"},
                    "output_on": {"template": "ENABLE {channel}"},
                    "output_off": {"template": "DISABLE {channel}"},
                }
            },
        }
    )
    io = IO()
    source = SourceMeasure(config, io)
    limits = SafetyLimits.model_validate(
        {
            "channels": {
                3: {
                    "voltage": {"min": -maximum, "max": maximum},
                    "current": {"max_abs": 0.02},
                    "zero_tolerance": 0.001,
                    "settle_tolerance": 0.002,
                }
            }
        }
    )
    return SafeDeviceWrapper(source, limits, "source_measure"), io


@pytest.mark.parametrize("value", [-3, 3, float("nan"), float("inf"), True])
def test_custom_voltage_bounds_reject_before_a_source_write(value):
    source, io = limited()
    with pytest.raises((SafetyLimitError, ValueError)):
        source.channel(3).set(voltage=value, current_limit=0.01)
    assert io.calls == []


def test_joint_channel_configuration_preflights_both_bench_and_hardware_limits():
    source, io = limited()
    with pytest.raises((SafetyLimitError, ValueError)):
        source.channel(3).set(voltage=1, current_limit=0.03)
    assert io.calls == []
    facade = source.channel(3)
    assert facade.set(voltage=-1, current_limit=0.01).on().off() is facade
    assert io.calls == ["VSET 3 -1.0 0.01", "ENABLE 3", "DISABLE 3"]


def test_signed_current_force_has_bounds_and_negative_compliance_is_rejected():
    source, io = limited()
    source.force_current(3, -0.01, voltage_compliance=1)
    assert io.calls == ["ISET 3 -0.01 1.0"]
    for current in (-0.03, 0.03):
        with pytest.raises((SafetyLimitError, ValueError)):
            source.force_current(3, current, voltage_compliance=1)
    with pytest.raises((SafetyLimitError, ValueError)):
        source.set_current(3, current_limit=-0.01)
    assert len(io.calls) == 1


@pytest.mark.parametrize(
    "data",
    [
        {"voltage": {"min": 2, "max": 1}},
        {"voltage": {"max": float("nan")}},
        {"current": {"max_abs": -1}},
        {"voltage": {"max": True}},
        {"voltage": {"maximum": 1}},
        {"zero_tolerance": True},
        {"settle_tolerance": float("inf")},
    ],
)
def test_invalid_custom_limit_schema_is_rejected(data):
    with pytest.raises(ValueError):
        SafetyLimitChannel.model_validate(data)


def test_limited_handles_reject_raw_escape_hatches():
    source, io = limited()
    for method in (source.write, source.query, source.query_raw):
        with pytest.raises(SafetyLimitError):
            method("UNVALIDATED")
    assert io.calls == []


def test_native_source_measure_target_retains_the_native_result_envelope():
    expected = MeasurementResult(
        values=0.001,
        units="A",
        instrument="synthetic",
        measurement_type="Current",
        envelope={"channel": 3, "compliance": False},
    )
    source = SimpleNamespace(read_current=lambda channel: expected)
    entry = MeasurementPlanEntry.model_validate(
        {
            "name": "dut_current",
            "resource": "bias",
            "target": {"kind": "source_measure_readback", "channel": 3, "quantity": "current"},
        }
    )
    result = execute_declared_measurement(SimpleNamespace(bias=source), entry, {})
    assert result is expected
    assert result.envelope["channel"] == 3


def test_bench_bounds_cannot_widen_static_equipment_ratings():
    source, io = limited(maximum=20)
    with pytest.raises(ValueError):
        source.channel(3).set(voltage=11, current_limit=0.01)
    assert io.calls == []
