"""
tests package initializer.

Purpose:
- Make this directory a proper Python package so static type checkers (e.g., ty)
  assign fully qualified module names like 'tests.conftest' instead of treating
  multiple 'conftest.py' files across the repo as the same top-level module.
- This disambiguation avoids duplicate-module mapping errors during type checking.

Runtime:
- This file intentionally contains no runtime logic and imposes no test discovery changes.
"""

__all__: list[str] = []
