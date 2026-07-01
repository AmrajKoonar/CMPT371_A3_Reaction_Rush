"""
game_session.py — Per-room game state machine and round bookkeeping.

A :class:`GameSession` holds the mutable state for one room's current match:
which state we're in, the round number, and every player's clicks/false
starts for the in-flight round. It exposes a small, explicit state machine so
invalid transitions are ignored safely.

The session performs **no networking and no locking of its own** — the owning
:class:`~reaction_rush.room_manager.Room` holds the lock and drives it. This
keeps the concurrency story in one place (the Room).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from . import constants as C
from .models import PlayerRoundResult


# Allowed transitions for the explicit state machine. Any transition not
# listed here is rejected by ``can_transition`` and ignored by the caller.
_ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    C.STATE_LOBBY:          {C.STATE_COUNTDOWN, C.STATE_LOBBY},
    C.STATE_COUNTDOWN:      {C.STATE_WAITING_FOR_GO, C.STATE_GAME_OVER, C.STATE_LOBBY},
    C.STATE_WAITING_FOR_GO: {C.STATE_ACTIVE_ROUND, C.STATE_SCORING, C.STATE_GAME_OVER},
    C.STATE_ACTIVE_ROUND:   {C.STATE_SCORING, C.STATE_GAME_OVER},
    C.STATE_SCORING:        {C.STATE_WAITING_FOR_GO, C.STATE_GAME_OVER, C.STATE_COUNTDOWN},
    C.STATE_GAME_OVER:      {C.STATE_REMATCH, C.STATE_LOBBY, C.STATE_COUNTDOWN},
    C.STATE_REMATCH:        {C.STATE_COUNTDOWN, C.STATE_LOBBY, C.STATE_GAME_OVER},
}


class GameSession:
    """Mutable state for one room's active/most-recent match."""

    def __init__(self, mode: str, total_rounds: int) -> None:
        self.mode: str = mode
        self.total_rounds: int = total_rounds

        self.state: str = C.STATE_LOBBY
        self.round_number: int = 0

        # Monotonic timestamp when the green ("GO") signal was sent.
        self.go_time: float = 0.0

        # Per-round data (keyed by player_id).
        self.round_clicks: Dict[str, float] = {}      # raw reaction ms
        self.round_adjusted: Dict[str, float] = {}    # latency-adjusted ms
        self.round_false_starts: Set[str] = set()
        self.round_responses: Set[str] = set()        # everyone who acted
        self.round_suspicious: Set[str] = set()

        # Accumulated results across the match (player_id -> results list).
        self.all_round_results: Dict[str, List[PlayerRoundResult]] = {}

        # Elimination-mode bookkeeping.
        self.eliminated: Set[str] = set()

        # Persistence handle for the current match (set by the room).
        self.match_id: Optional[str] = None

    # -----------------------------------------------------------------------
    # State machine
    # -----------------------------------------------------------------------

    def can_transition(self, to_state: str) -> bool:
        """Return True if moving from the current state to *to_state* is legal."""
        return to_state in _ALLOWED_TRANSITIONS.get(self.state, set())

    def transition(self, to_state: str) -> bool:
        """
        Attempt a state transition.

        Returns True and updates ``state`` if the transition is allowed;
        otherwise leaves the state unchanged and returns False.
        """
        if self.can_transition(to_state):
            self.state = to_state
            return True
        return False

    def force_state(self, to_state: str) -> None:
        """Unconditionally set the state (used for shutdown / abort paths)."""
        self.state = to_state

    # -----------------------------------------------------------------------
    # Round / match resets
    # -----------------------------------------------------------------------

    def reset_round(self) -> None:
        """Clear all per-round data before starting a new round."""
        self.round_clicks.clear()
        self.round_adjusted.clear()
        self.round_false_starts.clear()
        self.round_responses.clear()
        self.round_suspicious.clear()

    def reset_for_new_match(self, mode: str, total_rounds: int) -> None:
        """Reset everything for a fresh match (rematch flow)."""
        self.mode = mode
        self.total_rounds = total_rounds
        self.round_number = 0
        self.go_time = 0.0
        self.reset_round()
        self.all_round_results.clear()
        self.eliminated.clear()
        self.match_id = None
        self.state = C.STATE_LOBBY

    # -----------------------------------------------------------------------
    # Convenience
    # -----------------------------------------------------------------------

    def ensure_result_bucket(self, player_id: str) -> None:
        """Make sure a results list exists for *player_id*."""
        self.all_round_results.setdefault(player_id, [])

    def is_active_state(self) -> bool:
        """True while a round is in progress (red or green)."""
        return self.state in (C.STATE_WAITING_FOR_GO, C.STATE_ACTIVE_ROUND)
