from __future__ import annotations

from typing import cast

import pytest

from pytestlab.common.enums import OutputPolarity
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.instruments.WaveformGenerator import WaveformGenerator


def _awg() -> WaveformGenerator:
    return cast(WaveformGenerator, AutoInstrument.from_config("keysight/EDU33212A", simulate=True))


def test_waveform_generator_write_checks_error_queue_once(monkeypatch):
    awg = _awg()
    checks = 0
    original_check = awg._error_check

    def count_check() -> None:
        nonlocal checks
        checks += 1
        original_check()

    monkeypatch.setattr(awg, "_error_check", count_check)

    awg.set_output_polarity(1, OutputPolarity.NORMAL)

    assert checks == 1


def test_waveform_generator_write_preserves_error_propagation(monkeypatch):
    awg = _awg()
    error = InstrumentCommunicationError(
        instrument=awg.config.model,
        command="OUTPut1:POLarity NORM",
        message="simulated instrument error",
    )
    monkeypatch.setattr(awg, "_error_check", lambda: (_ for _ in ()).throw(error))

    with pytest.raises(InstrumentCommunicationError, match="simulated instrument error"):
        awg.set_output_polarity(1, OutputPolarity.NORMAL)
