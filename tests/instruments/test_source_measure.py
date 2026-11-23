from __future__ import annotations

import pytest

from pytestlab.config.loader import ConfigLoader
from pytestlab.config.source_measure_config import SourceMeasureConfig
from pytestlab.config.source_measure_config import SourceMeasureRange
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError
from pytestlab.experiments import MeasurementResult
from pytestlab.instruments.scpi_engine import SCPIEngine
from pytestlab.instruments.SourceMeasure import SourceMeasure
from pytestlab.instruments.SourceMeasure import TypedMeasurementResult


class FakeBackend:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.writes: list[str] = []
        self.responses = responses or {}
        self.fail_write: str | None = None

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, cmd: str) -> None:
        if self.fail_write == cmd:
            raise RuntimeError("simulated write failure")
        self.writes.append(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        self.writes.append(cmd)
        return self.responses[cmd]

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return self.query(cmd, delay).encode()

    def set_timeout(self, timeout_ms: int) -> None:
        pass

    def get_timeout(self) -> int:
        return 20000


SCPI = {
    "commands": {
        "force_voltage": {"template": "DV {channel},{voltage},{current_limit}"},
        "force_current": {"template": "DI {channel},{current},{voltage_compliance}"},
        "output_on": {"template": "CN{channel}"},
        "output_off": {"template": "CL{channel}"},
    },
    "queries": {
        "measure_voltage": {
            "template": "TV{channel}",
            "response": {
                "type": "raw",
                "header_width": 3,
                "value_start": 3,
                "header_fields": ["status", "channel", "measurement_type"],
                "status_map": {"N": "normal", "C": "compliance"},
                "expected_measurement_type": "V",
                "compliance_statuses": ["C"],
            },
        },
        "measure_current": {
            "template": "TI{channel}",
            "response": {
                "type": "raw",
                "header_width": 3,
                "value_start": 3,
                "header_fields": ["status", "channel", "measurement_type"],
                "status_map": {"N": "normal", "C": "compliance"},
                "expected_measurement_type": "I",
                "compliance_statuses": ["C"],
            },
        },
    },
}


def make_config() -> SourceMeasureConfig:
    return SourceMeasureConfig.model_validate(
        {
            "manufacturer": "Fixture",
            "model": "FixtureSMU",
            "device_type": "source_measure",
            "role": "source_measure",
            "capabilities": {"error_queue": False},
            "channels": [
                {
                    "channel_id": 1,
                    "description": "fixture channel",
                    "voltage_range": {"min": -10, "max": 10, "units": "V"},
                    "current_range": {"min": -1, "max": 1, "units": "A"},
                    "current_limit_range": {"min": 0, "max": 1, "units": "A"},
                    "voltage_compliance_range": {"min": -10, "max": 10, "units": "V"},
                }
            ],
            "scpi": SCPI,
        }
    )


def test_preflights_ranges_before_any_write() -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)

    with pytest.raises(InstrumentParameterError):
        smu.set_voltage(1, 11)
    with pytest.raises(InstrumentParameterError):
        smu.set_current(1, 2)
    assert backend.writes == []


def test_voltage_mode_pairs_compliance_and_off_does_not_zero() -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)

    smu.set_current(1, 0.1)
    assert backend.writes == []
    smu.set_voltage(1, 2.0)
    assert backend.writes == ["DV 1,2.0,0.1"]
    smu.output(1, True)
    smu.output(1, False)
    assert backend.writes[-2:] == ["CN1", "CL1"]
    assert "DZ1" not in backend.writes


def test_current_force_is_explicit_and_requires_voltage_compliance() -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)

    with pytest.raises(TypeError):
        smu.force_current(1, 0.1)  # type: ignore[call-arg]
    smu.force_current(1, 0.1, voltage_compliance=5)
    assert backend.writes == ["DI 1,0.1,5.0"]


def test_output_on_requires_a_configured_source_state() -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)

    with pytest.raises(InstrumentParameterError):
        smu.output(1, True)
    assert backend.writes == []


def test_typed_measurement_result_preserves_header_and_compliance() -> None:
    backend = FakeBackend({"TI1": "C1I1.25E-3"})
    smu = SourceMeasure(make_config(), backend)

    result = smu.read_current(1)

    assert isinstance(result, TypedMeasurementResult)
    assert isinstance(result, MeasurementResult)
    assert result.value.nominal == pytest.approx(1.25e-3)
    assert result.channel == 1
    assert result.status == "C"
    assert result.status_text == "compliance"
    assert result.envelope["physical_channel"] == 1


def test_session_stores_numeric_value_and_measurement_metadata() -> None:
    from pytestlab.measurements.session import MeasurementSession

    backend = FakeBackend({"TI1": "N1I1.25E-3"})
    smu = SourceMeasure(make_config(), backend)
    session = MeasurementSession(compliance=False)
    session.parameter("step", [0])

    @session.acquire
    def measure(step: int):
        return {"current": smu.read_current(1)}

    experiment = session.run(show_progress=False)
    assert experiment is not None
    row = session.data.to_dicts()[0]
    assert row["current"] == pytest.approx(1.25e-3)
    assert "current__measurement" in row
    assert '"physical_channel": 1' in row["current__measurement"]


def test_non_numeric_source_setting_is_rejected_before_write() -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)

    with pytest.raises(InstrumentParameterError):
        smu.set_voltage(1, "1")  # type: ignore[arg-type]
    with pytest.raises(InstrumentParameterError):
        smu.output(1, "off")  # type: ignore[arg-type]
    assert backend.writes == []


def test_hp4142b_profile_preserves_verified_range_and_polarity_fields() -> None:
    config = ConfigLoader.load("hp/4142B")
    engine = SCPIEngine(config.scpi.model_dump(exclude_none=True))

    assert engine.build("force_voltage", channel=3, voltage=5.0, current_limit=0.1) == [
        "DV 3,0,5.0,0.1,0"
    ]
    assert engine.build("force_current", channel=3, current=0.01, voltage_compliance=20.0) == [
        "DI 3,0,0.01,20.0,0"
    ]


def test_unknown_status_and_wrong_measurement_type_are_rejected() -> None:
    backend = FakeBackend({"TI1": "Z1I1.25E-3"})
    smu = SourceMeasure(make_config(), backend)
    with pytest.raises(InstrumentDataError, match="unknown measurement status"):
        smu.read_current(1)

    backend = FakeBackend({"TI1": "N1V1.25E-3"})
    smu = SourceMeasure(make_config(), backend)
    with pytest.raises(InstrumentDataError, match="measurement type"):
        smu.read_current(1)


def test_preflight_fails_missing_output_readback_without_io() -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)

    with pytest.raises(InstrumentConfigurationError, match="get_output_state"):
        smu.preflight_channel(1)
    assert backend.writes == []


def test_operation_contract_uses_public_method_names() -> None:
    smu = SourceMeasure(make_config(), FakeBackend())
    operations = set(smu.list_operations())
    assert {
        "id",
        "set_voltage",
        "set_current",
        "force_current",
        "output",
        "read_voltage",
        "read_current",
        "get_output_state",
    } <= operations
    assert "force_voltage" not in operations
    assert "measure_voltage" not in operations
    assert "source_voltage" not in operations


@pytest.mark.parametrize("bad_channel", [True, 1.0, -1])
def test_invalid_channel_ids_are_rejected_before_any_io(bad_channel: object) -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)

    with pytest.raises(InstrumentParameterError):
        smu.set_voltage(bad_channel, 1.0)  # type: ignore[arg-type]
    with pytest.raises(InstrumentParameterError):
        smu.channel(bad_channel)  # type: ignore[arg-type]
    assert backend.writes == []


def test_failed_force_invalidates_active_proof_but_keeps_requested_audit() -> None:
    backend = FakeBackend()
    smu = SourceMeasure(make_config(), backend)
    smu.set_current(1, 0.1)
    smu.set_voltage(1, 2.0)
    backend.fail_write = "DV 1,3.0,0.1"

    with pytest.raises(InstrumentCommunicationError):
        smu.set_voltage(1, 3.0)
    config = smu.get_channel_configuration(1)
    assert config["mode"] is None
    assert config["output"] is None
    assert config["requested"]["voltage"] == 3.0
    with pytest.raises(InstrumentParameterError):
        smu.output(1, True)
    assert "CN1" not in backend.writes


def test_static_channel_ratings_reject_bool_duplicate_and_wrong_units() -> None:
    with pytest.raises(ValueError, match="not bool"):
        SourceMeasureRange.model_validate({"min": False, "max": 1, "units": "V"})
    data = make_config().model_dump()
    duplicate = data | {"channels": [data["channels"][0], data["channels"][0]]}
    with pytest.raises(ValueError, match="unique"):
        SourceMeasureConfig.model_validate(duplicate)
    wrong_units = make_config().model_dump()
    wrong_units["channels"][0]["voltage_range"]["units"] = "mV"
    with pytest.raises(ValueError, match="units must be 'V'"):
        SourceMeasureConfig.model_validate(wrong_units)
    bad_channel_id = make_config().model_dump()
    bad_channel_id["channels"][0]["channel_id"] = True
    with pytest.raises(ValueError, match="channel_id must be an integer"):
        SourceMeasureConfig.model_validate(bad_channel_id)


def test_partial_multi_channel_output_failure_invalidates_every_channel() -> None:
    data = make_config().model_dump()
    second = dict(data["channels"][0])
    second["channel_id"] = 2
    data["channels"] = [data["channels"][0], second]
    smu_config = SourceMeasureConfig.model_validate(data)
    backend = FakeBackend()
    smu = SourceMeasure(smu_config, backend)
    smu.channel(1).set(voltage=1.0, current_limit=0.1)
    smu.channel(2).set(voltage=1.0, current_limit=0.1)
    backend.fail_write = "CN2"

    with pytest.raises(InstrumentCommunicationError):
        smu.output([1, 2], True)
    for channel in (1, 2):
        snapshot = smu.get_channel_configuration(channel)
        assert snapshot["mode"] is None
        assert snapshot["output"] is None
        assert snapshot["requested"]["output"] is True


def test_profile_command_sequences_are_sent_in_order_and_prevalidated() -> None:
    data = make_config().model_dump()
    data["scpi"]["commands"]["force_voltage"] = {
        "sequence": ["PREP {channel}", "DV {channel},{voltage},{current_limit}"]
    }
    smu = SourceMeasure(SourceMeasureConfig.model_validate(data), FakeBackend())
    smu.set_current(1, 0.1)
    smu.set_voltage(1, 2.0)
    assert smu._backend.writes == ["PREP 1", "DV 1,2.0,0.1"]

    bad_data = make_config().model_dump()
    bad_data["scpi"]["commands"]["force_voltage"] = {
        "sequence": ["PREP {channel}", "DV {missing},{voltage},{current_limit}"]
    }
    bad_backend = FakeBackend()
    bad_smu = SourceMeasure(SourceMeasureConfig.model_validate(bad_data), bad_backend)
    bad_smu.set_current(1, 0.1)
    with pytest.raises(Exception, match="missing"):
        bad_smu.set_voltage(1, 2.0)
    assert bad_backend.writes == []

    query_data = make_config().model_dump()
    query_data["scpi"]["queries"]["measure_current"]["sequence"] = [
        "CONF {channel}",
        "TI{channel}",
    ]
    query_backend = FakeBackend({"TI1": "N1I1.25E-3"})
    query_smu = SourceMeasure(SourceMeasureConfig.model_validate(query_data), query_backend)
    query_smu.read_current(1)
    assert query_backend.writes == ["CONF 1", "TI1"]


def test_output_state_requires_boolean_profile_map_and_rejects_unknown_tokens() -> None:
    data = make_config().model_dump()
    data["scpi"]["queries"]["get_output_state"] = {
        "template": "OUT{channel}",
        "response": {"type": "str", "state_map": {"ON": True, "OFF": False}},
    }
    backend = FakeBackend({"OUT1": "2"})
    smu = SourceMeasure(SourceMeasureConfig.model_validate(data), backend)
    with pytest.raises(InstrumentDataError, match="unknown output state"):
        smu.get_output_state(1)
    assert backend.writes == ["OUT1"]

    for raw in ("false", "unknown"):
        bad_backend = FakeBackend({"OUT1": raw})
        bad_smu = SourceMeasure(SourceMeasureConfig.model_validate(data), bad_backend)
        with pytest.raises(InstrumentDataError, match="unknown output state"):
            bad_smu.get_output_state(1)

    invalid_map = make_config().model_dump()
    invalid_map["scpi"]["queries"]["get_output_state"] = {
        "template": "OUT{channel}",
        "response": {"type": "str", "state_map": {"ON": 1, "OFF": 0}},
    }
    invalid_smu = SourceMeasure(SourceMeasureConfig.model_validate(invalid_map), FakeBackend())
    with pytest.raises(InstrumentConfigurationError, match="booleans"):
        invalid_smu.preflight_channel(1)
