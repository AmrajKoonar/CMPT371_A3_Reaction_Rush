"""
logging_config.py — Structured logging setup for the server.

Uses the Python standard-library ``logging`` module. Logs always go to the
console; an optional file handler can be added via ``--log-file``. A single
``get_logger`` helper keeps logger naming consistent across modules.
"""

import logging
import sys
from typing import Optional

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_configured = False


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """
    Configure root logging once.

    Parameters
    ----------
    level : str
        One of DEBUG / INFO / WARNING / ERROR / CRITICAL.
    log_file : str, optional
        If provided, logs are also appended to this file.
    """
    global _configured

    numeric_level = getattr(logging, str(level).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove pre-existing handlers so repeated setup (e.g. in tests) is clean
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            # A bad log-file path should not stop the server from running
            root.warning("Could not open log file '%s'", log_file)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring defaults if needed."""
    if not _configured:
        setup_logging()
    return logging.getLogger(name)
