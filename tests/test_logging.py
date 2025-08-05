from __future__ import annotations
import pytest
import logging
import os
from pytestlab import set_log_level, reinitialize_logging # Assuming this is exposed from pytestlab/__init__.py
from pytestlab._log import get_logger # For direct logger checking

def test_set_log_level_valid(caplog):
    """Test setting a valid log level."""
    set_log_level("DEBUG")
    logger = get_logger("test_log_valid")

    # Check if the 'pytestlab' root logger's level is set
    pytestlab_root_logger = logging.getLogger("pytestlab")
    assert pytestlab_root_logger.getEffectiveLevel() == logging.DEBUG

    # Check if a child logger also gets the effective level
    assert logger.getEffectiveLevel() == logging.DEBUG

    logger.debug("This is a debug message for test_set_log_level_valid.")
    assert "This is a debug message for test_set_log_level_valid." in caplog.text

    # Reset to default for other tests (e.g., WARNING)
    set_log_level("WARNING")
    assert pytestlab_root_logger.getEffectiveLevel() == logging.WARNING


def test_set_log_level_invalid(caplog):
    """Test setting an invalid log level."""
    initial_level = logging.getLogger("pytestlab").getEffectiveLevel()
    # Set log level to WARNING first to ensure we can see the warning message
    set_log_level("WARNING")
    set_log_level("INVALID_LEVEL")
    # The set_log_level function should ideally log a warning for invalid levels
    assert "Invalid log level: INVALID_LEVEL" in caplog.text # Check for the warning
    # Level should remain unchanged from WARNING
    assert logging.getLogger("pytestlab").getEffectiveLevel() == logging.WARNING


def test_pytestlab_log_env_variable(caplog, monkeypatch):
    """Test PYTESTLAB_LOG environment variable."""
    monkeypatch.setenv("PYTESTLAB_LOG", "INFO")

    # Reinitialize logging to pick up the new environment variable
    reinitialize_logging()

    logger = get_logger("test_env_log")
    logger.info("Info message for env var test.")
    logger.debug("Debug message for env var test (should not appear).")

    assert logging.getLogger("pytestlab").getEffectiveLevel() <= logging.INFO # Check effective level
    assert "Info message for env var test." in caplog.text
    assert "Debug message for env var test (should not appear)." not in caplog.text

    monkeypatch.delenv("PYTESTLAB_LOG", raising=False)
    set_log_level("WARNING") # Reset for other tests
