from __future__ import annotations
import pytest
import logging
import os
from pytestlab import set_log_level # Assuming this is exposed from pytestlab/__init__.py
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
    set_log_level("INVALID_LEVEL")
    # The set_log_level function should ideally log a warning for invalid levels
    assert "Invalid log level: INVALID_LEVEL" in caplog.text # Check for the warning
    # Level should remain unchanged
    assert logging.getLogger("pytestlab").getEffectiveLevel() == initial_level


def test_pytestlab_log_env_variable(caplog, monkeypatch):
    """Test PYTESTLAB_LOG environment variable."""
    monkeypatch.setenv("PYTESTLAB_LOG", "INFO")
    
    # Need to re-trigger logger initialization if it caches on first call.
    # A simple way is to get a new logger instance after env var is set.
    # However, basicConfig might have already run.
    # This test is more robust if get_logger re-evaluates env var or if
    # logging is configured per-test-session.
    # For now, let's assume get_logger will pick it up if called "freshly".
    # A more direct test would be to check the handler's level if possible,
    # or the root logger's level *before* any pytestlab logger is fetched.
    
    # To make this test more reliable, we might need to unload and reload the _log module
    # or have a way to reset the logging system.
    # A simpler check:
    logger = get_logger("test_env_log")
    logger.info("Info message for env var test.")
    logger.debug("Debug message for env var test (should not appear).")

    assert logging.getLogger("pytestlab").getEffectiveLevel() <= logging.INFO # Check effective level
    assert "Info message for env var test." in caplog.text
    assert "Debug message for env var test (should not appear)." not in caplog.text
    
    monkeypatch.delenv("PYTESTLAB_LOG", raising=False)
    set_log_level("WARNING") # Reset for other tests