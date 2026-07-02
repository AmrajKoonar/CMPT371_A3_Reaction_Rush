"""
models.py — Dataclasses that model players, sessions, and results.

These are deliberately plain data containers (no networking, no game rules)
so they are trivial to construct in tests and to serialise for the wire or
the database.
"""

from __future__ import annotations

import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================================
# Player session (a connected human OR a server-side bot)
# ============================================================================

@dataclass
class PlayerSession:
    """
    Everything the server needs to know about one participant in a room.

    Bots reuse this same class with ``is_bot=True`` and ``sock=None`` so the
    rest of the game code treats humans and bots uniformly.
    """

    player_id: str
    name: str
    room_code: str = ""
    sock: Optional[socket.socket] = None
    address: Optional[tuple] = None

    ready: bool = False
    connected: bool = True
    is_host: bool = False

    # Bots
    is_bot: bool = False
    bot_level: str = ""

    # Latency / heartbeat
    last_pong: float = field(default_factory=time.monotonic)
    latency_ms: float = 0.0

    # Rematch voting
    rematch_ready: bool = False

    # Reconnect
    session_token: str = field(default_factory=lambda: uuid.uuid4().hex)

    # Elimination bookkeeping
    eliminated: bool = False

    def public_view(self) -> Dict[str, Any]:
        """Return a dict safe to broadcast to all clients (no socket)."""
        return {
            "player_id": self.player_id,
            "name": self.name,
            "ready": self.ready,
            "connected": self.connected,
            "is_host": self.is_host,
            "is_bot": self.is_bot,
            "bot_level": self.bot_level,
            "latency_ms": round(self.latency_ms, 1),
            "eliminated": self.eliminated,
        }


# ============================================================================
# Round + match results
# ============================================================================

@dataclass
class PlayerRoundResult:
    """One player's outcome for a single round."""

    player_name: str
    reaction_time_ms: float          # raw, server-measured. <0 = invalid
    adjusted_reaction_ms: float      # latency-compensated (or same as raw)
    score: int
    false_start: bool = False
    timed_out: bool = False
    eliminated: bool = False
    suspicious: bool = False         # implausible timing flagged for review

    def to_dict(self) -> Dict[str, Any]:
        return {
            "player_name": self.player_name,
            "reaction_time_ms": self.reaction_time_ms,
            "adjusted_reaction_ms": self.adjusted_reaction_ms,
            "score": self.score,
            "false_start": self.false_start,
            "timed_out": self.timed_out,
            "eliminated": self.eliminated,
            "suspicious": self.suspicious,
        }


@dataclass
class PlayerStanding:
    """Aggregate standing used to build the leaderboard."""

    player_name: str
    total_score: int
    total_reaction_time_ms: float
    average_reaction_ms: float = -1.0
    fastest_reaction_ms: float = -1.0
    false_starts: int = 0
    rounds_won: int = 0
    consistency: float = -1.0
    eliminated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "player_name": self.player_name,
            "total_score": self.total_score,
            "total_reaction_time_ms": self.total_reaction_time_ms,
            "average_reaction_ms": self.average_reaction_ms,
            "fastest_reaction_ms": self.fastest_reaction_ms,
            "false_starts": self.false_starts,
            "rounds_won": self.rounds_won,
            "consistency": self.consistency,
            "eliminated": self.eliminated,
        }


@dataclass
class PracticeResult:
    """A single local practice attempt (client-side)."""

    reaction_ms: float
    false_start: bool
    created_at: str = ""
