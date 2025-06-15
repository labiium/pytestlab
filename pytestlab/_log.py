from __future__ import annotations
import logging
import sys
import os

_root_logger = logging.getLogger("pytestlab")

def setup_logging():
    """
    Set up logging for pytestlab.
    This function is called automatically when the first logger is requested.
    It can also be called manually to reconfigure logging.
    """
    level_name = os.getenv("PYTESTLAB_LOG_LEVEL", os.getenv("PYTESTLAB_LOG", "WARNING")).upper()
    log_level = getattr(logging, level_name, logging.WARNING)
    log_file = os.getenv("PYTESTLAB_LOG_FILE")

    # Remove all handlers from our logger to reconfigure
    for handler in _root_logger.handlers[:]:
        _root_logger.removeHandler(handler)

    if log_file:
        handler: logging.Handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stderr)

    formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s – %(message)s")
    handler.setFormatter(formatter)
    _root_logger.addHandler(handler)
    _root_logger.setLevel(log_level)
    _root_logger.propagate = False

def set_log_level(level: int | str):
    """
    Sets the logging level for the pytestlab logger.
    :param level: The logging level, e.g., "DEBUG", "INFO", logging.DEBUG, logging.INFO.
    """
    if isinstance(level, str):
        level = level.upper()
    _root_logger.setLevel(level)

def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance, configuring the root logger on first call.
    """
    if not _root_logger.handlers:
        setup_logging()
    return _root_logger.getChild(name)

# Initial setup when module is loaded.
setup_logging()