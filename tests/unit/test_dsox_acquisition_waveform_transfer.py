from __future__ import annotations

import pytest

from pytestlab import AutoInstrument


@pytest.mark.parametrize(
    "response",
    ["AVER", "PEAK"],
)
def test_average_and_peak_select_normal_record_transfer(response, monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    sent: list[str] = []
    queries: list[str] = []
    monkeypatch.setattr(scope, "_send_command", sent.append)
    monkeypatch.setattr(scope, "_query", lambda query: queries.append(query) or response)
    monkeypatch.setattr(scope, "_wait", lambda: None)

    selected_mode = scope._configure_waveform_transfer("CHANnel1", "byte")

    assert selected_mode == "set_wave_points_mode_normal"
    assert ":WAVeform:POINts:MODE NORMal" in sent
    assert ":WAVeform:POINts:MODE RAW" not in sent
    assert queries == [":ACQuire:TYPE?"]


@pytest.mark.parametrize("response", ["NORM", "HRES"])
def test_normal_and_high_resolution_keep_raw_record_transfer(response, monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    sent: list[str] = []
    monkeypatch.setattr(scope, "_send_command", sent.append)
    monkeypatch.setattr(scope, "_query", lambda query: "MAIN" if "MODE?" in query else response)
    monkeypatch.setattr(scope, "_wait", lambda: None)

    selected_mode = scope._configure_waveform_transfer("CHANnel1", "byte")

    assert selected_mode == "set_wave_points_mode_raw"
    assert ":WAVeform:POINts:MODE RAW" in sent
    assert ":WAVeform:POINts:MODE NORMal" not in sent


def test_acquisition_trace_records_profile_selected_points_mode(monkeypatch) -> None:
    import numpy as np
    import polars as pl

    from pytestlab.instruments.Oscilloscope import ChannelReadingResult

    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    result = ChannelReadingResult(
        instrument="DSOX1204G",
        units="V",
        measurement_type="ChannelVoltageTime",
        values=pl.DataFrame(
            {"Time (s)": np.array([0.0, 1e-9]), "Channel 1 (V)": np.array([0.0, 1.0])}
        ),
        envelope={"waveform_transfer": {"points_mode_aliases": ["set_wave_points_mode_normal"]}},
    )
    monkeypatch.setattr(scope, "get_time_axis", lambda: (1e-3, 0.0))
    monkeypatch.setattr(scope, "read_channels", lambda *_args, **_kwargs: result)

    captured = scope.acquire_waveform(1, uncertainty=False)

    assert "set_wave_points_mode_normal" in captured.acquisition.commands
    assert "set_wave_points_mode_raw" not in captured.acquisition.commands
