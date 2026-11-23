from __future__ import annotations

import pytest

from pytestlab.config.device_config import DeviceConfig
from pytestlab.config.device_config import DeviceRole
from pytestlab.prober import GenericProberDevice


class Wire:
    def __init__(self, response: str = "0") -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def connect(self) -> None:
        self.calls.append(("connect", ""))

    def disconnect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, command: str) -> None:
        self.calls.append(("write", command))

    def query(self, command: str, delay: float | None = None) -> str:
        self.calls.append(("query", command))
        return self.response

    def set_timeout(self, timeout_ms: int) -> None:
        pass

    def get_timeout(self) -> int:
        return 1000


def make(values: dict[str, object], wire: Wire | None = None) -> tuple[GenericProberDevice, Wire]:
    wire = Wire() if wire is None else wire
    config = DeviceConfig(
        manufacturer="Example",
        model="prober",
        device_type="prober",
        role=DeviceRole.DUT_CONTROL,
        motion={
            "axes": [{"name": "x"}],
            "queries": {
                "vacuum_state": {
                    "template": "VACUUM?",
                    "response": {"type": "state_map", "values": values},
                }
            },
        },
    )
    return GenericProberDevice(config, wire), wire


@pytest.mark.parametrize("values", [{}, {"0": "false"}, {"0": 0}, {"0": None}])
def test_empty_or_non_bool_vacuum_map_fails_before_connect(values) -> None:
    prober, wire = make(values)

    with pytest.raises(NotImplementedError, match="vacuum state readback"):
        prober.get_vacuum_state()

    assert wire.calls == []


@pytest.mark.parametrize(("response", "expected"), [("0", False), ("1", True)])
def test_vacuum_state_returns_explicit_bool(response: str, expected: bool) -> None:
    prober, wire = make({"0": False, "1": True}, Wire(response))

    assert prober.get_vacuum_state() is expected
    assert wire.calls == [("connect", ""), ("query", "VACUUM?")]


@pytest.mark.parametrize("value", ["false", "unknown", 0, 1, None])
def test_non_bool_vacuum_readback_fails(value, monkeypatch) -> None:
    prober, _ = make({"0": False, "1": True})
    backend = prober._profile_backend()
    monkeypatch.setattr(backend, "motion_query", lambda _query: value)

    with pytest.raises(ValueError, match="vacuum readback must map to a bool"):
        prober.get_vacuum_state()
