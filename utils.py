"""
utils.py — Small shared helpers for Reaction Rush.

Keeps protocol.py, server.py, and client.py free of repeated boilerplate
like safe socket teardown and human-readable formatting.
"""

import socket
import time
from typing import Optional


def safe_close(sock: Optional[socket.socket]) -> None:
    """
    Shut down and close *sock*, swallowing any OS-level errors.

    Calling ``shutdown`` first signals the remote peer that we are done;
    ``close`` releases the file descriptor.  Either call may raise
    ``OSError`` if the socket is already dead — we ignore that.
    """
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def timestamp() -> str:
    """Return the current wall-clock time as ``HH:MM:SS`` for log lines."""
    return time.strftime("%H:%M:%S")


def format_ms(ms: float) -> str:
    """
    Format a millisecond value for display.

    Negative values (used for false starts / timeouts) render as ``"N/A"``.
    """
    if ms < 0:
        return "N/A"
    return f"{ms:.0f} ms"
