from __future__ import annotations

import numpy as np

from ..spice import _parse_complex_wrdata
from ..spice import _parse_real_wrdata


def parse_real_wrdata(data: np.ndarray, vector_count: int):
    return _parse_real_wrdata(data, vector_count)


def parse_complex_wrdata(data: np.ndarray, vector_count: int):
    return _parse_complex_wrdata(data, vector_count)
