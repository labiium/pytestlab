from __future__ import annotations

import numpy as np
import pytest

from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.errors import InstrumentDataError
from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.instruments.instrument import Instrument


@pytest.fixture
def instrument():
    return AutoInstrument.from_config("keysight/EDU34450A", simulate=True)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"#14\x01\x02\x03\x04", np.array([1, 2, 3, 4], dtype=np.uint8)),
        (b"#210abcdefghij", np.frombuffer(b"abcdefghij", dtype=np.uint8)),
        (b"#10", np.array([], dtype=np.uint8)),
        (b"#14\x01\x02\x03\x04\n", np.array([1, 2, 3, 4], dtype=np.uint8)),
    ],
)
def test_read_to_np_parses_definite_length_binary_blocks(instrument, payload, expected):
    result = instrument._read_to_np(payload)

    np.testing.assert_array_equal(result, expected)


@pytest.mark.parametrize(
    "payload",
    [
        b"0123456789corrupt",
        b"#",
        b"#A5hello",
        b"#05hello",
        b"#210short",
    ],
)
def test_read_to_np_rejects_malformed_binary_blocks(instrument, payload):
    with pytest.raises(InstrumentDataError):
        instrument._read_to_np(payload)


def test_instrument_from_config_points_to_supported_factory_path():
    config = AutoInstrument.from_config("keysight/EDU34450A", simulate=True).config

    with pytest.raises(NotImplementedError, match="AutoInstrument.from_config"):
        Instrument.from_config(config)


def test_instrument_from_config_still_validates_config_type():
    with pytest.raises(Exception, match="InstrumentConfig"):
        Instrument.from_config({"model": "not-a-config"})  # type: ignore[arg-type]


def test_autoinstrument_remains_supported_factory_path():
    device = AutoInstrument.from_config("keysight/EDU34450A", simulate=True)

    assert isinstance(device.config, InstrumentConfig)
