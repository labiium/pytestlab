"""SCPI waveform decoding helpers shared by scopes, LAMB checks, and replay."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

import numpy as np

from .scpi_binary import BinaryBlockParseError
from .scpi_binary import definite_length_block_to_array

WaveformEncoding = Literal[
    "auto",
    "ascii_volts",
    "binblock_uint8",
    "binblock_int8",
    "binblock_uint16_le",
    "binblock_int16_le",
    "binblock_uint16_be",
    "binblock_int16_be",
]


@dataclass(frozen=True)
class WaveformPreamble:
    format_code: int | None
    waveform_type: int | None
    points: int
    count: int | None
    xinc: float
    xorg: float
    xref: float
    yinc: float
    yorg: float
    yref: float
    raw: str

    @classmethod
    def parse(cls, preamble: str) -> WaveformPreamble:
        fields = [part.strip().strip('"') for part in preamble.split(",")]
        if len(fields) < 10:
            raise WaveformDecodeError("waveform preamble must contain at least 10 CSV fields")
        return cls(
            format_code=_safe_int(fields[0]),
            waveform_type=_safe_int(fields[1]),
            points=int(float(fields[2])),
            count=_safe_int(fields[3]),
            xinc=float(fields[4]),
            xorg=float(fields[5]),
            xref=float(fields[6]),
            yinc=float(fields[7]),
            yorg=float(fields[8]),
            yref=float(fields[9]),
            raw=preamble,
        )

    def to_dict(self) -> dict[str, float | int | str | None]:
        return {
            "format_code": self.format_code,
            "waveform_type": self.waveform_type,
            "points": self.points,
            "count": self.count,
            "xinc": self.xinc,
            "xorg": self.xorg,
            "xref": self.xref,
            "yinc": self.yinc,
            "yorg": self.yorg,
            "yref": self.yref,
            "raw": self.raw,
        }


@dataclass(frozen=True)
class DecodedWaveform:
    values: np.ndarray
    preamble: WaveformPreamble
    encoding: str
    raw_sha256: str
    preamble_sha256: str

    @property
    def point_count(self) -> int:
        return int(self.values.size)

    @property
    def time_axis(self) -> np.ndarray:
        return (
            np.arange(self.point_count, dtype=float) - self.preamble.xref
        ) * self.preamble.xinc + self.preamble.xorg

    def metadata(self) -> dict[str, object]:
        return {
            "encoding": self.encoding,
            "point_count": self.point_count,
            "raw_sha256": self.raw_sha256,
            "preamble_sha256": self.preamble_sha256,
            "preamble": self.preamble.to_dict(),
        }


class WaveformDecodeError(ValueError):
    """Raised when a SCPI waveform payload cannot be decoded safely."""


def decode_waveform(
    raw_response: bytes,
    preamble: str,
    *,
    encoding: WaveformEncoding = "auto",
) -> DecodedWaveform:
    """Decode a SCPI waveform response into scaled engineering-unit samples."""

    parsed = WaveformPreamble.parse(preamble)
    raw_sha = hashlib.sha256(raw_response).hexdigest()
    pre_sha = hashlib.sha256(preamble.encode("utf-8")).hexdigest()
    if encoding == "auto":
        encoding = _infer_encoding(raw_response, parsed)
    if encoding == "ascii_volts":
        values = _decode_ascii_volts(raw_response)
    else:
        values = _decode_binblock(raw_response, parsed, encoding)
    if values.size != parsed.points:
        raise WaveformDecodeError(
            f"waveform point count mismatch: raw={values.size}, preamble={parsed.points}"
        )
    return DecodedWaveform(values.astype(float, copy=False), parsed, encoding, raw_sha, pre_sha)


def _infer_encoding(raw: bytes, preamble: WaveformPreamble) -> WaveformEncoding:
    if raw.startswith(b"#"):
        if preamble.format_code == 1:
            return "binblock_int16_be"
        return "binblock_uint8"
    return "ascii_volts"


def _decode_ascii_volts(raw: bytes) -> np.ndarray:
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise WaveformDecodeError("waveform response is neither binblock nor ASCII CSV") from exc
    values = np.fromstring(text, sep=",", dtype=float)
    if values.size == 0:
        raise WaveformDecodeError("ASCII waveform response contained no numeric samples")
    return values


def _decode_binblock(raw: bytes, preamble: WaveformPreamble, encoding: str) -> np.ndarray:
    dtype_map = {
        "binblock_uint8": np.uint8,
        "binblock_int8": np.int8,
        "binblock_uint16_le": "<u2",
        "binblock_int16_le": "<i2",
        "binblock_uint16_be": ">u2",
        "binblock_int16_be": ">i2",
    }
    dtype = dtype_map.get(encoding)
    if dtype is None:
        raise WaveformDecodeError(f"unsupported waveform encoding: {encoding}")
    try:
        raw_values = definite_length_block_to_array(raw, dtype=np.dtype(dtype)).astype(float)
    except BinaryBlockParseError as exc:
        raise WaveformDecodeError(str(exc)) from exc
    return (raw_values - preamble.yref) * preamble.yinc + preamble.yorg


def _safe_int(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None
