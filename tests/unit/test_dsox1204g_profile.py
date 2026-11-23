from __future__ import annotations

import pytest

from pytestlab import AutoInstrument


def test_dsox_fra_keeps_legacy_lifecycle_supported(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    commands: list[str] = []

    report = scope._operation_support_report("frequency_response_analysis")
    assert report.supported is True
    assert report.missing_capability_metadata == ()
    assert report.missing_required_aliases == ()

    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query", lambda _query: "100,1,1000,2")

    result = scope.franalysis_sweep(
        input_channel=1,
        output_channel=2,
        start_freq=100,
        stop_freq=1000,
        amplitude=1,
        points=2,
    )

    assert ":FUNCtion:FRANalysis" in commands
    assert ":DISABLE" in commands
    assert ":FRANalysis:RUN" not in commands
    assert result.values.columns == ["Frequency (Hz)", "Magnitude"]


@pytest.mark.parametrize(
    "model",
    [
        "DSOX1204G",
        "DSOX1202G",
        "DSOX3054G",
        "MSOX2024A",
    ],
)
@pytest.mark.parametrize(("state", "token"), [(True, "ON"), (False, "OFF")])
def test_wave_gen_serializes_boolean_state_as_scpi_token(
    monkeypatch, model: str, state: bool, token: str
) -> None:
    scope = AutoInstrument.from_config(f"keysight/{model}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)

    discovered = scope.describe_operation("wave_generator_basic")
    discovered_values = [option["value"] for option in discovered["parameters"]["state"]["options"]]
    resolved = scope._resolve_operation_parameter("wave_generator_basic", "state", state)
    scope.wave_gen(state)

    assert discovered_values == [True, False]
    assert all(type(value) is bool for value in discovered_values)
    assert resolved.value is state
    assert commands == [f"WGEN:OUTP {token}"]
    assert resolved.transport_value == token
