"""
examples_ci package.

Purpose:
- Make this directory a proper Python package so static type checkers (e.g., mypy)
  assign a fully qualified module name like 'examples_ci.conftest'.
- This disambiguates it from other similarly named modules elsewhere in the repo
  (e.g., tests/conftest.py), avoiding duplicate-module mapping errors.

This file intentionally contains no runtime logic.
"""

__all__: list[str] = []
