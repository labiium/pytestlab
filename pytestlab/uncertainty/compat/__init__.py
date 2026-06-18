"""Compatibility aliases for users migrating from :mod:`uncertainties`."""

from __future__ import annotations

from ..quick import correlated_values
from ..quick import correlated_values_norm
from ..quick import correlation_matrix
from ..quick import covariance_matrix
from ..quick import nominal_value
from ..quick import nominal_values
from ..quick import std_dev
from ..quick import std_devs
from ..quick import ufloat
from ..quick import ufloat_fromstr
from . import umath

__all__ = [
    "ufloat",
    "ufloat_fromstr",
    "nominal_value",
    "std_dev",
    "nominal_values",
    "std_devs",
    "covariance_matrix",
    "correlation_matrix",
    "correlated_values",
    "correlated_values_norm",
    "umath",
]
