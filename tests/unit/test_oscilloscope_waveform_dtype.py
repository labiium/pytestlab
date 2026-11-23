import numpy as np
import pytest

from pytestlab.errors import InstrumentDataError
from pytestlab.instruments.Oscilloscope import Oscilloscope


def test_byte_waveforms_use_signed_codes_from_zero_reference() -> None:
    assert Oscilloscope._waveform_byte_dtype(y_reference=0.0) == np.dtype(np.int8)


def test_byte_waveforms_use_unsigned_codes_from_midcode_reference() -> None:
    assert Oscilloscope._waveform_byte_dtype(y_reference=127.5) == np.dtype(np.uint8)


def test_word_waveforms_use_preamble_signedness_and_reported_byteorder() -> None:
    assert Oscilloscope._waveform_word_dtype(y_reference=0.0, byteorder="little") == np.dtype("<i2")
    assert Oscilloscope._waveform_word_dtype(y_reference=32767.5, byteorder="little") == np.dtype(
        "<u2"
    )


def test_word_waveforms_reject_unknown_byteorder() -> None:
    with pytest.raises(InstrumentDataError, match="Unsupported waveform byte order"):
        Oscilloscope._waveform_word_dtype(y_reference=0.0, byteorder="native")
