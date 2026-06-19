from __future__ import annotations

import numpy as np
import pytest

from pytestlab.instruments.waveform_decode import WaveformDecodeError
from pytestlab.instruments.waveform_decode import decode_waveform


def test_decode_ascii_volts_waveform() -> None:
    decoded = decode_waveform(b"-0.1,0.0,0.1", "4,0,3,1,1e-9,0,0,1,0,0")

    assert decoded.encoding == "ascii_volts"
    assert decoded.values.tolist() == pytest.approx([-0.1, 0.0, 0.1])
    assert decoded.time_axis.tolist() == pytest.approx([0.0, 1e-9, 2e-9])
    assert decoded.metadata()["point_count"] == 3


def test_decode_byte_binblock_waveform() -> None:
    decoded = decode_waveform(b"#13" + bytes([127, 128, 129]), "0,0,3,1,1e-9,0,0,0.01,0,128")

    assert decoded.encoding == "binblock_uint8"
    assert decoded.values.tolist() == pytest.approx([-0.01, 0.0, 0.01])


def test_decode_word_big_endian_binblock_waveform() -> None:
    payload = np.array([127, 128, 129], dtype=">i2").tobytes()
    decoded = decode_waveform(b"#16" + payload, "1,0,3,1,1e-9,0,0,0.01,0,128")

    assert decoded.encoding == "binblock_int16_be"
    assert decoded.values.tolist() == pytest.approx([-0.01, 0.0, 0.01])


def test_decode_rejects_point_count_mismatch() -> None:
    with pytest.raises(WaveformDecodeError, match="point count mismatch"):
        decode_waveform(b"0.0,1.0", "4,0,3,1,1e-9,0,0,1,0,0")
