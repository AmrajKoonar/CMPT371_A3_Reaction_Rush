"""
utils.py

Small shared helpers used in multiple files.

Right now this file mainly handles:
- safe socket closing
- timestamp formatting for server logs
- reaction time formatting for the UI
"""

import socket
import time
from typing import Optional


def safe_close(sock: Optional[socket.socket]) -> None:
    """Close a socket safely even if it is already broken"""
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
    """Return the current time for server log output"""
    return time.strftime("%H:%M:%S")


def format_ms(ms: float) -> str:
    """Format a reaction time for display in the UI"""
    if ms < 0:
        return "N/A"
    return f"{ms:.0f} ms"
