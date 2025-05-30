"""
Shared pytest fixtures for the measurement/database test-suite.
"""
from __future__ import annotations

import builtins
import types
from pathlib import Path

import numpy as np
import pytest

import pytestlab.measurements.session as msession


class _DummyInstrument:
    """Tiny mock that records the last command but does nothing."""
    def __init__(self):  # noqa: D401
        self._closed = False

    def close(self):  # noqa: D401
        self._closed = True

    # generic fall-back: any attr access returns a lambda that swallows args
    def __getattr__(self, item):
        return lambda *a, **k: None


@pytest.fixture(autouse=True)
def _patch_autoinstrument(monkeypatch):
    """
    Auto-Instrument stub – always returns a dummy to avoid VISA calls.
    """
    monkeypatch.setattr(msession, "AutoInstrument", types.SimpleNamespace(from_config=lambda *a, **k: _DummyInstrument()))
    yield


@pytest.fixture()
def tmp_db_file(tmp_path: Path) -> Path:
    return tmp_path / "test_db.db"


@pytest.fixture()
def simple_experiment():
    from pytestlab.experiments import Experiment

    exp = Experiment("TestExp", "desc")
    exp.add_parameter("x", "-", "")
    exp.add_trial({"x": [1, 2, 3], "y": [4, 5, 6]})
    return exp
