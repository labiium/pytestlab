"""
tests.instruments.sim package initializer.

Purpose:
- Make this directory a package so static analyzers (e.g., ty) assign a fully
  qualified module name to nested files like 'conftest.py', preventing
  duplicate-module mapping errors.

Runtime:
- No runtime behavior; does not affect pytest discovery.
"""

__all__: list[str] = []
