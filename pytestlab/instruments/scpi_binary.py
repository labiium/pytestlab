from __future__ import annotations

import numpy as np


class BinaryBlockParseError(ValueError):
    """Raised when a SCPI definite-length binary block is malformed."""


def strip_definite_length_block(data: bytes) -> bytes:
    """Return the payload from a SCPI definite-length binary block.

    Supports IEEE 488.2 definite-length blocks of the form
    ``#<N><length><payload>``. A trailing newline after the payload is allowed,
    but missing headers, indefinite-length blocks, non-numeric lengths, and
    truncated payloads are rejected instead of guessed.
    """
    if not data.startswith(b"#"):
        raise BinaryBlockParseError("SCPI binary block must start with '#'.")
    if len(data) < 2:
        raise BinaryBlockParseError("SCPI binary block is missing the length digit count.")

    length_digit_text = data[1:2].decode("ascii", errors="strict")
    if not length_digit_text.isdigit():
        raise BinaryBlockParseError(
            f"SCPI binary block length digit count is not numeric: {length_digit_text!r}."
        )

    length_digit_count = int(length_digit_text)
    if length_digit_count == 0:
        raise BinaryBlockParseError("Indefinite-length SCPI binary blocks are not supported.")

    length_start = 2
    length_end = length_start + length_digit_count
    if len(data) < length_end:
        raise BinaryBlockParseError("SCPI binary block is missing the payload length field.")

    length_text = data[length_start:length_end].decode("ascii", errors="strict")
    if not length_text.isdigit():
        raise BinaryBlockParseError(
            f"SCPI binary block payload length is not numeric: {length_text!r}."
        )

    payload_length = int(length_text)
    payload_start = length_end
    payload_end = payload_start + payload_length
    if len(data) < payload_end:
        raise BinaryBlockParseError(
            f"SCPI binary block payload is truncated: expected {payload_length} bytes, "
            f"got {max(len(data) - payload_start, 0)}."
        )

    return data[payload_start:payload_end]


def definite_length_block_to_array(data: bytes, dtype: np.dtype | type = np.uint8) -> np.ndarray:
    """Parse a SCPI definite-length binary block into a NumPy array."""
    payload = strip_definite_length_block(data)
    np_dtype = np.dtype(dtype)
    if len(payload) % np_dtype.itemsize != 0:
        raise BinaryBlockParseError(
            f"SCPI binary block payload length {len(payload)} is not divisible by "
            f"dtype item size {np_dtype.itemsize}."
        )
    return np.frombuffer(payload, dtype=np_dtype)
