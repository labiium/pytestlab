from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from pytestlab import AutoInstrument
from pytestlab.instruments.Oscilloscope import Preamble
from pytestlab.uncertainty import QuantityArray


@pytest.mark.parametrize(
    ("method_name", "measurement_type", "response"),
    [
        ("measure_voltage_peak_to_peak", "P2PV", "2.0"),
        ("measure_rms_voltage", "rms_voltage", "0.5"),
    ],
)
def test_scalar_voltage_uncertainty_falls_back_to_waveform_accuracy(
    method_name: str, measurement_type: str, response: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = AutoInstrument.from_config("keysight/MXR404A", backend_override=MagicMock())
    monkeypatch.setattr(scope, "_query", lambda _query: response)

    result = getattr(scope, method_name)(1)

    assert result.measurement_type == measurement_type
    assert result.values.u > 0.0
    assert result.values.provenance.provenance_complete is True
    assert result.values.measurement_model.function in {"measure_vpp", "measure_vrms"}
    assert "waveform_ch1" in result.values.provenance.origin_detail


def test_waveform_uncertainty_uses_profile_accuracy_and_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", backend_override=MagicMock())
    monkeypatch.setattr(scope, "_send_command", lambda _command: None)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "get_sampling_rate", lambda: 1.0e9)
    monkeypatch.setattr(scope, "_configure_waveform_transfer", lambda *_args: None)
    monkeypatch.setattr(
        scope,
        "_read_preamble",
        lambda: Preamble(
            format="1",
            type="1",
            points=2,
            xinc=1.0e-9,
            xorg=0.0,
            xref=0.0,
            yinc=1.0,
            yorg=0.0,
            yref=0.0,
        ),
    )
    monkeypatch.setattr(
        scope,
        "_read_wave_data",
        lambda *_args, **_kwargs: np.array([-1.0, 1.0]),
    )

    result = scope.read_channels(1)
    waveform = result.quantity(1)

    assert isinstance(waveform, QuantityArray)
    assert waveform.u[0] > 0.0
    assert waveform.u[1] > 0.0
    assert result.envelope["waveform_uncertainty"]["1"]["accuracy_spec"].source == (
        "Keysight HD304MSO specifications"
    )


def test_edu33212a_profile_declares_awg_accuracy_on_schema_supported_ranges() -> None:
    awg = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)

    channel = awg.config.channels[0]
    assert channel.amplitude_range.accuracy.reading_percent == 2.0
    assert channel.frequency_range.accuracy.reading_ppm == 1.0
    assert channel.amplitude_range.accuracy.source == "Keysight EDU33212A specifications"
