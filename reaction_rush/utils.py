"""
utils.py — Small shared helpers used across the package.

Kept dependency-free and side-effect-free so any module can import it.
"""

from __future__ import annotations

import socket
import time
from typing import Optional


def safe_close(sock: Optional[socket.socket]) -> None:
    """
    Shut down and close *sock*, swallowing any OS-level errors.

    ``shutdown`` signals the peer we're done; ``close`` frees the fd. Either
    may raise if the socket is already dead — we ignore that.
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

    Negative values (false starts / timeouts) render as ``"N/A"``.
    """
    if ms is None or ms < 0:
        return "N/A"
    return f"{ms:.0f} ms"


def clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* to the inclusive range [low, high]."""
    return max(low, min(high, value))


def valid_player_name(name: str) -> bool:
    """Return True if *name* is a usable player name (1–20 chars, non-blank)."""
    return bool(name) and 0 < len(name.strip()) <= 20
