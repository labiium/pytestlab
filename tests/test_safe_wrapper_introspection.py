from types import SimpleNamespace

import pytest

from pytestlab.bench import SafeDeviceWrapper
from pytestlab.bench import SafetyLimitError
from pytestlab.bench import _SafeChannelFacade


class _Device:
    config = SimpleNamespace(model="fake")

    def measure(self) -> float:
        return 1.0

    def query(self, _command: str) -> str:
        return "unsafe"

    def write(self, _command: str) -> None:
        raise AssertionError("raw write must never be forwarded")


class _Channel:
    def enable(self) -> "_Channel":
        return self

    def measure(self) -> float:
        return 1.0


def test_safe_device_dir_exposes_public_guarded_interface() -> None:
    wrapper = SafeDeviceWrapper(_Device(), {}, "measurement")

    names = dir(wrapper)

    assert {"is_instrument", "measure", "role", "safety_limits"} <= set(names)
    assert "query" not in names
    assert "write" not in names
    assert not any(name.startswith("_") for name in names)
    assert wrapper.measure() == 1.0
    with pytest.raises(SafetyLimitError, match="Raw query commands are disabled"):
        wrapper.query("*IDN?")


def test_safe_channel_dir_exposes_public_guarded_interface() -> None:
    wrapper = SafeDeviceWrapper(_Device(), {}, "stimulus")
    channel = _SafeChannelFacade(wrapper, _Channel(), 1)

    names = dir(channel)

    assert {"enable", "measure", "set"} <= set(names)
    assert not any(name.startswith("_") for name in names)
    assert channel.enable() is channel
    assert channel.measure() == 1.0
