from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from pytestlab import AutoInstrument
from pytestlab.config.bench_loader import load_bench_yaml
from pytestlab.errors import InstrumentParameterError

ROOT = Path(__file__).resolve().parents[2] / "pytestlab" / "profiles"


class FakeIO:
    def __init__(self, responses: dict[str, str] | None = None, status_byte: int = 1) -> None:
        self.responses = responses or {}
        self.status_byte = status_byte
        self.connected = False
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.terminations: list[str | None] = []

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def close(self) -> None:
        self.disconnect()

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str, delay: float | None = None) -> str:
        del delay
        self.queries.append(command)
        return self.responses.get(command, "0:ready")

    def query_raw(self, command: str, delay: float | None = None) -> bytes:
        return self.query(command, delay).encode()

    def set_timeout(self, timeout_ms: int) -> None:
        del timeout_ms

    def get_timeout(self) -> int:
        return 5000

    def set_read_termination(self, value: str | None) -> None:
        self.terminations.append(value)

    def read_status_byte(self) -> int:
        return self.status_byte


@pytest.mark.parametrize("profile", ["hp/HP4084B_legacy"])
def test_hp_profile_is_declarative_and_exposes_documented_limits(profile: str) -> None:
    data: dict[str, Any] = yaml.safe_load(
        (ROOT / "hp" / f"{profile.rsplit('/', 1)[1]}.yaml").read_text()
    )
    assert data["device_type"] == "instrument"
    assert data["capabilities"]["controller_family"] == ["HP4084A", "HP4084B"]
    assert data["capabilities"]["attached_matrix_family"] == ["HP4085A", "HP4085B"]
    assert data["capabilities"]["attached_matrix_model"] == "HP4085B"
    assert data["capabilities"]["identity"]["example_response"] == "HP 4084B REV. 3.0"
    assert data["capabilities"]["message_io"]["read_termination"] == "\n"
    assert data["driver"].endswith(":ProfileInstrument")
    assert "address" not in data
    assert "backend" not in data
    assert data["capabilities"]["error_queue"] is False
    assert data["capabilities"]["status_byte"]["flags"]["matrix_open"]["mask"] == 8
    assert data["capabilities"]["status_byte"]["flags"]["syntax_error"]["clears_on_read"] is True
    connect = data["operation_options"]["operations"]["connect"]
    assert (
        data["operation_options"]["operations"]["status_byte"]["backend_method"]
        == "read_status_byte"
    )
    assert [item["value"] for item in connect["parameters"]["port"]["options"]] == [
        1,
        2,
        3,
        4,
        5,
        6,
        8,
        9,
        10,
    ]
    assert connect["parameters"]["pin"]["min"] == 1
    assert connect["parameters"]["pin"]["max"] == 48
    assert connect["parameters"]["pin"]["integer"] is True

    instrument = AutoInstrument.from_preset(profile, simulate=True)
    assert (
        instrument.validate_operation_contract(strict=True, include_unsupported=True)["connect"][
            "supported"
        ]
        is True
    )
    identity_io = FakeIO(responses={"IDEX": "HP 4084B REV. 3.0"})
    identity_instrument = AutoInstrument.from_preset(
        profile, backend_override=identity_io, simulate=False
    )
    assert identity_instrument.execute_profile_operation("identify_extended") == "HP 4084B REV. 3.0"


@pytest.mark.parametrize(
    ("operation", "params", "command"),
    [
        ("connect", {"port": 1, "pin": 12}, "PC1ON12"),
        ("disconnect", {"pin": 2}, "PC0ON2"),
        ("guard", {"pin": 2}, "PC1GD2"),
        ("clear", {}, "CL"),
    ],
)
def test_hp_state_changing_operations_write_without_context(
    operation: str, params: dict[str, Any], command: str
) -> None:
    io = FakeIO()
    instrument = AutoInstrument.from_preset(
        "hp/HP4084B_legacy", backend_override=io, simulate=False
    )

    metadata = instrument.describe_operation(operation)["execution"]
    assert metadata["requires_context"] == []
    assert metadata["safety_class"] == "state-changing"
    instrument.execute_profile_operation(operation, **params)
    assert io.connected is True
    assert io.writes == [command]
    assert io.queries == []


def test_hp_fractional_pin_is_rejected_before_backend_io() -> None:
    io = FakeIO()
    instrument = AutoInstrument.from_preset(
        "hp/HP4084B_legacy", backend_override=io, simulate=False
    )

    with pytest.raises(InstrumentParameterError, match="integer"):
        instrument.execute_profile_operation(
            "connect",
            port=1,
            pin=1.5,
        )
    assert io.connected is False
    assert io.writes == []


def test_hp_whole_float_pin_is_wired_as_an_integer() -> None:
    io = FakeIO()
    instrument = AutoInstrument.from_preset(
        "hp/HP4084B_legacy", backend_override=io, simulate=False
    )

    instrument.execute_profile_operation(
        "connect",
        port=1,
        pin=1.0,
    )
    assert io.writes == ["PC1ON1"]


def test_pa200_has_no_identity_or_error_queue_and_uses_response_queries() -> None:
    io = FakeIO(
        responses={"ReadProberStatus": "0:ready:contact:remote", "SetExternalMode R": "0:remote"},
        status_byte=16,
    )
    instrument = AutoInstrument.from_preset(
        "suss/PA200_legacy", backend_override=io, simulate=False
    )

    assert "identify" not in instrument.list_operations()
    assert instrument.config.capabilities["identity"] is False
    assert instrument.config.capabilities["error_queue"] is False
    assert instrument.config.capabilities["message_io"]["read_termination"] == "\n"
    assert (
        instrument.describe_operation("set_external_mode")["execution"]["safety_class"]
        == "state-changing"
    )
    assert (
        instrument.describe_operation("stop_all_movements")["execution"]["safety_class"]
        == "state-changing"
    )
    assert instrument.execute_profile_operation("read_prober_status") == "0:ready:contact:remote"
    assert instrument.execute_profile_operation("set_external_mode", mode="remote") == "0:remote"
    assert io.queries == ["ReadProberStatus", "SetExternalMode R"]
    assert instrument.execute_profile_operation("status_byte") == 16


@pytest.mark.parametrize(
    ("profile", "identity_command", "identity_response"),
    [
        ("agilent/3458A_legacy", "ID?", "HP3458A"),
        ("hp/4142B_legacy", "*IDN?", "HP4142B"),
    ],
)
def test_readonly_reference_profiles_expose_only_identity_and_native_status(
    profile: str, identity_command: str, identity_response: str
) -> None:
    io = FakeIO(responses={identity_command: identity_response}, status_byte=0)
    instrument = AutoInstrument.from_preset(profile, backend_override=io, simulate=False)

    assert set(instrument.config.operation_options.operations) == {"identify", "status_byte"}
    assert instrument.config.capabilities["error_queue"] is False
    assert instrument.config.capabilities["status_byte"]["flags"] == {}
    assert instrument.config.capabilities["message_io"]["read_termination"] == "\n"
    assert instrument.execute_profile_operation("identify") == identity_response
    assert instrument.execute_profile_operation("status_byte") == 0
    assert io.queries == [identity_command]
    assert io.terminations == ["\n"]


def test_pa200_mode_is_constrained_to_documented_values() -> None:
    instrument = AutoInstrument.from_preset("suss/PA200_legacy", simulate=True)
    options = instrument.list_operation_options("set_external_mode", "mode")
    assert [item["value"] for item in options] == ["remote", "local"]
    with pytest.raises(InstrumentParameterError):
        instrument.execute_profile_operation("set_external_mode", mode="automatic")


def test_profile_instrument_bench_example_parses_without_allocating_hardware() -> None:
    config = load_bench_yaml(
        Path(__file__).resolve().parents[2] / "examples" / "profile_instrument_bench.yaml"
    )
    assert config.instruments["hp4084b"].address == "GPIB0::22::INSTR"
    assert config.instruments["pa200"].address == "GPIB0::1::INSTR"
    assert config.instruments["hp4084b"].backend == {"type": "lamb"}
    assert config.instruments["pa200"].backend == {"type": "lamb"}
