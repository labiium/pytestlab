"""Offline contract tests for generic native multimeter profile execution."""

from __future__ import annotations

import time
from threading import Event
from threading import Thread

import pytest

from pytestlab.config.device_config import DeviceRole
from pytestlab.config.loader import load_device_profile
from pytestlab.config.multimeter_config import AccuracySpec
from pytestlab.config.multimeter_config import FunctionSpec
from pytestlab.config.multimeter_config import MeasurementFunctionsSpec
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.config.multimeter_config import RangeSpec
from pytestlab.instruments.Multimeter import Multimeter
from pytestlab.instruments.scpi_engine import ValidationError


class RecordingBackend:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.reads: list[str] = []
        self.responses = responses or {}

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def set_read_termination(self, _termination: str) -> None:
        pass

    def set_timeout(self, _timeout_ms: int) -> None:
        pass

    def get_timeout(self) -> int:
        return 1000

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str, delay: float | None = None) -> str:
        del delay
        self.queries.append(command)
        return self.responses.get(command, "0.125")

    def read(self) -> str:
        self.reads.append("read")
        return self.responses.get("read", self.responses.get("", "0.125"))

    def query_raw(self, command: str, delay: float | None = None) -> bytes:
        del command, delay
        return b""

    def supports_native_status_byte(self) -> bool:
        return False


class UnsupportedReadBackend(RecordingBackend):
    def supports_read(self) -> bool:
        return False


class BlockingReadBackend(RecordingBackend):
    def __init__(self) -> None:
        super().__init__()
        self.read_started = Event()
        self.release_read = Event()

    def supports_read(self) -> bool:
        return True

    def read(self) -> str:
        self.reads.append("read")
        self.read_started.set()
        assert self.release_read.wait(timeout=2)
        return "0.125"


def _semantic_options():
    return {
        "measure": {
            "transport": {"measure": "measure"},
            "parameters": {
                "function": {"kind": "enum", "source": "measurement_functions"},
                "range_val": {
                    "kind": "open_string",
                    "required": False,
                    "transport_parameter": False,
                },
                "resolution": {
                    "kind": "open_string",
                    "required": False,
                    "transport_parameter": False,
                },
            },
        },
    }


def _dmm(scpi: dict[str, object], backend: RecordingBackend) -> Multimeter:
    config = MultimeterConfig(
        manufacturer="Test",
        model="TestDMM",
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        capabilities={"error_queue": False},
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="Voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
            )
        ),
        operation_options=_semantic_options(),
        scpi=scpi,
    )
    return Multimeter(config=config, backend=backend)


def test_query_alias_executes_setup_sequence_and_parses_final_response() -> None:
    backend = RecordingBackend()
    dmm = _dmm(
        {
            "queries": {
                "measure": {
                    "sequence": ["FUNC {function}", "TRIG SYN", ""],
                    "response": {"type": "scpi_float"},
                }
            }
        },
        backend,
    )

    result = dmm.measure("dc_voltage", uncertainty=False)

    assert float(result) == pytest.approx(0.125)
    assert backend.writes == ["FUNC VOLT:DC", "TRIG SYN"]
    assert backend.queries == [""]


def test_measure_preflights_every_template_before_sending() -> None:
    backend = RecordingBackend()
    dmm = _dmm(
        {
            "queries": {
                "measure": {
                    "sequence": ["FUNC {function}", "BROKEN {missing}", ""],
                    "response": {"type": "scpi_float"},
                }
            }
        },
        backend,
    )

    with pytest.raises(Exception, match="Missing parameter"):
        dmm.measure("dc_voltage", uncertainty=False)
    assert backend.writes == []
    assert backend.queries == []


def test_3458a_profile_maps_generic_dcv_and_uses_ascii_synchronous_read() -> None:
    profile = load_device_profile("agilent/3458A")
    assert profile.device_type == "multimeter"
    backend = RecordingBackend(responses={"": "1.25\r\n"})
    dmm = Multimeter(config=profile, backend=backend)

    assert dmm._scpi_engine.describe("measure")["response"]["transport"] == "read"
    assert dmm._scpi_engine.describe("read")["response"]["transport"] == "read"
    result = dmm.measure("dc_voltage", range_val="10", uncertainty=False)

    assert float(result) == pytest.approx(1.25)
    assert backend.writes == [
        "FUNC DCV,10,",
        "NPLC 1",
        "NRDGS 1,AUTO",
        "OFORMAT ASCII",
        "TARM AUTO",
        "TRIG SYN",
    ]
    assert backend.queries == []
    assert backend.reads == ["read"]
    assert not any("PRESET" in command or "RESET" in command for command in backend.writes)


def test_3458a_configuration_reuses_profile_sequence_without_read() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend()
    dmm = Multimeter(config=profile, backend=backend)

    dmm.configure_measurement("dc_voltage", range_val="1")

    assert backend.writes == [
        "FUNC DCV,1,",
        "NPLC 1",
        "NRDGS 1,AUTO",
        "OFORMAT ASCII",
        "TARM AUTO",
        "TRIG SYN",
    ]
    assert backend.queries == []


def test_unknown_profile_accuracy_remains_explicitly_nominal() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend()
    dmm = Multimeter(config=profile, backend=backend)

    result = dmm.measure("dc_voltage", uncertainty=True)

    assert result.values.nominal_value == pytest.approx(0.125)
    assert result.values.u == 0


def test_3458a_configuration_query_parses_native_csv_response() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend(responses={"FUNC?": "DCV,10,0.001\r\n"})
    dmm = Multimeter(config=profile, backend=backend)

    result = dmm.get_config()

    assert result.measurement_mode == "Voltage"
    assert result.range_value == pytest.approx(10.0)
    assert result.resolution == "0.001"
    assert result.units == "V"
    assert backend.queries == ["FUNC?"]


def test_known_fixture_accuracy_is_applied_only_when_profile_supplies_it() -> None:
    backend = RecordingBackend()
    config = MultimeterConfig(
        manufacturer="Fixture",
        model="FixtureDMM",
        operation_options=_semantic_options(),
        device_type="multimeter",
        role=DeviceRole.MEASUREMENT,
        capabilities={"error_queue": False},
        measurement_functions=MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                label="Voltage",
                unit="V",
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
                ranges=[
                    RangeSpec(
                        nominal_V=1.0,
                        accuracy=AccuracySpec(reading_percent=0.1, range_percent=0.05),
                    )
                ],
            )
        ),
        scpi={
            "queries": {
                "measure": {
                    "template": "MEASURE:VOLT:DC? {range},{resolution}",
                    "response": {"type": "scpi_float"},
                }
            }
        },
    )
    dmm = Multimeter(config=config, backend=backend)

    result = dmm.measure("dc_voltage", range_val="1")

    assert result.values.nominal_value == pytest.approx(0.125)
    assert result.values.u > 0


def test_nplc_override_is_rendered_for_measure_and_configuration() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend()
    dmm = Multimeter(config=profile, backend=backend)

    dmm.measure("dc_voltage", nplc=10, uncertainty=False)
    assert "NPLC 10" in backend.writes

    backend.writes.clear()
    dmm.configure_measurement("dc_voltage", nplc=0.5)
    assert "NPLC 0.5" in backend.writes


@pytest.mark.parametrize("bad_nplc", [True, False, float("nan"), float("inf"), -1, 1001, "1"])
def test_invalid_nplc_is_rejected_before_any_io(bad_nplc: object) -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend()
    dmm = Multimeter(config=profile, backend=backend)

    with pytest.raises(Exception, match="nplc"):
        dmm.measure("dc_voltage", nplc=bad_nplc, uncertainty=False)

    assert backend.writes == []
    assert backend.queries == []
    assert backend.reads == []


def test_nplc_is_not_silently_ignored_by_unknown_profile_alias() -> None:
    backend = RecordingBackend()
    dmm = _dmm(
        {"queries": {"measure": {"template": "MEASURE?", "response": {"type": "float"}}}},
        backend,
    )

    with pytest.raises(Exception, match="does not declare nplc"):
        dmm.measure("dc_voltage", nplc=1, uncertainty=False)

    assert backend.writes == []
    assert backend.queries == []
    assert backend.reads == []


def test_trigger_source_uses_semantic_on_read_and_rejects_bus_for_3458a() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend()
    dmm = Multimeter(config=profile, backend=backend)

    dmm.set_trigger_source("ON_READ")
    assert backend.writes == ["TRIG SYN"]

    backend.writes.clear()
    with pytest.raises(Exception, match="Unsupported semantic option"):
        dmm.set_trigger_source("BUS")
    assert backend.writes == []


def test_3458a_range_rejects_non_numeric_command_text_before_io() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend()
    dmm = Multimeter(config=profile, backend=backend)

    with pytest.raises(ValidationError, match="range"):
        dmm.measure("dc_voltage", range_val="1;RESET", uncertainty=False)

    assert backend.writes == []
    assert backend.queries == []
    assert backend.reads == []


def test_3458a_configuration_query_maps_profile_numeric_function_code() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = RecordingBackend(responses={"FUNC?": "1,10\r\n"})
    dmm = Multimeter(config=profile, backend=backend)

    result = dmm.get_config()

    assert result.measurement_mode == "Voltage"
    assert result.range_value == pytest.approx(10.0)
    assert result.units == "V"


def test_native_read_capability_is_checked_before_setup_writes() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = UnsupportedReadBackend()
    dmm = Multimeter(config=profile, backend=backend)

    with pytest.raises(Exception, match="support.*read"):
        dmm.measure("dc_voltage", uncertainty=False)

    assert backend.writes == []
    assert backend.queries == []
    assert backend.reads == []


def test_native_measurement_transaction_is_serialized_across_threads() -> None:
    profile = load_device_profile("agilent/3458A")
    backend = BlockingReadBackend()
    dmm = Multimeter(config=profile, backend=backend)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            dmm.measure("dc_voltage", uncertainty=False)
        except BaseException as error:
            errors.append(error)

    first = Thread(target=run)
    second = Thread(target=run)
    first.start()
    assert backend.read_started.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    assert len(backend.writes) == 6
    backend.release_read.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert errors == []
    assert len(backend.writes) == 12
    assert backend.queries == []
    assert backend.reads == ["read", "read"]
