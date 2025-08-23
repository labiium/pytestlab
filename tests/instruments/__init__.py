"""
tests.instruments package initializer.

Purpose:
- Ensure proper package hierarchy for nested 'conftest.py' files
  (e.g., tests/instruments/sim/conftest.py), so static type checkers
  like mypy assign distinct qualified module names and avoid duplicate
  module mapping errors.

Runtime:
- No runtime behavior. Does not affect pytest discovery.
"""

__all__: list[str] = []
