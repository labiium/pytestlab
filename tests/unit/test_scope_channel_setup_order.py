from __future__ import annotations

import pytest

from pytestlab import AutoInstrument


class ProbeRescalingScope:
    """Model a scope whose displayed vertical axis follows probe attenuation."""

    def __init__(self) -> None:
        self.axis = [0.1, 0.02]
        self.probe_attenuation = 10
        self.calls: list[tuple] = []

    def get_channel_axis(self, channel: int) -> list[float]:
        assert channel == 1
        return self.axis.copy()

    def set_channel_axis(self, channel: int, scale: float, offset: float) -> None:
        assert channel == 1
        self.calls.append(("axis", scale, offset))
        self.axis = [scale, offset]

    def set_probe_attenuation(self, channel: int, attenuation: int) -> None:
        assert channel == 1
        self.calls.append(("probe", attenuation))
        factor = attenuation / self.probe_attenuation
        self.axis = [self.axis[0] * factor, self.axis[1] * factor]
        self.probe_attenuation = attenuation


@pytest.fixture
def scope_and_receiver(monkeypatch):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    receiver = ProbeRescalingScope()
    monkeypatch.setattr(scope, "get_channel_axis", receiver.get_channel_axis)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: str(
            {
                "probe_get": receiver.probe_attenuation,
                "get_channel_scale": receiver.axis[0],
                "get_channel_offset": receiver.axis[1],
            }[alias]
        ),
    )

    def apply(command):
        token, value = command.rsplit(" ", 1)
        if token.upper().endswith(":PROBE"):
            receiver.set_probe_attenuation(1, float(value))
        elif token.upper().endswith(":SCALE"):
            receiver.set_channel_axis(1, float(value), receiver.axis[1])
        elif token.upper().endswith(":OFFSET"):
            receiver.set_channel_axis(1, receiver.axis[0], float(value))

    monkeypatch.setattr(scope, "_send_command", apply)
    return scope, receiver


def test_probe_change_precedes_scale_and_offset_and_leaves_requested_axis(scope_and_receiver):
    scope, receiver = scope_and_receiver

    scope.channel(1).setup(
        scale=0.1,
        offset=0.3,
        probe_attenuation=1,
    )

    assert receiver.calls[0] == ("probe", 1)
    assert receiver.axis == [0.1, 0.3]


def test_probe_only_setup_does_not_rewrite_vertical_axis(scope_and_receiver):
    scope, receiver = scope_and_receiver

    scope.channel(1).setup(probe_attenuation=1)

    assert receiver.calls == [("probe", 1)]
    assert receiver.axis == pytest.approx([0.01, 0.002])


def test_all_none_setup_remains_a_noop(scope_and_receiver):
    scope, receiver = scope_and_receiver

    scope.channel(1).setup()

    assert receiver.calls == []
    assert receiver.axis == pytest.approx([0.1, 0.02])
