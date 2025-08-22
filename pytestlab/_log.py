from __future__ import annotations

import logging
import os
import sys

_root_logger: logging.Logger = logging.getLogger("pytestlab")


def setup_logging() -> None:
    """
    Set up logging for pytestlab.
    This function is called automatically when the first logger is requested.
    It can also be called manually to reconfigure logging.
    """
    level_name = os.getenv("PYTESTLAB_LOG_LEVEL", os.getenv("PYTESTLAB_LOG", "WARNING")).upper()
    log_level = getattr(logging, level_name, logging.WARNING)
    log_file = os.getenv("PYTESTLAB_LOG_FILE")

    # Remove all handlers from our logger to reconfigure
    for h in _root_logger.handlers[:]:
        _root_logger.removeHandler(h)

    if log_file:
        handler_obj: logging.Handler = logging.FileHandler(log_file)
    else:
        handler_obj = logging.StreamHandler(sys.stderr)

    formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s – %(message)s")
    handler_obj.setFormatter(formatter)
    _root_logger.addHandler(handler_obj)
    _root_logger.setLevel(log_level)
    # Enable propagation so pytest caplog can capture logs
    _root_logger.propagate = True


def reinitialize_logging() -> None:
    """
    Reinitialize logging configuration, useful for tests that modify environment variables.
    """
    setup_logging()


def set_log_level(level: int | str) -> None:
    """
    Sets the logging level for the pytestlab logger.
    :param level: The logging level, e.g., "DEBUG", "INFO", logging.DEBUG, logging.INFO.
    """
    try:
        if isinstance(level, str):
            level = level.upper()
        _root_logger.setLevel(level)
    except ValueError:
        # Log the warning and keep the current level
        _root_logger.warning(f"Invalid log level: {level}")


def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance, configuring the root logger on first call.
    """
    if not _root_logger.handlers:
        setup_logging()
    return _root_logger.getChild(name)


# Initial setup when module is loaded.
setup_logging()
