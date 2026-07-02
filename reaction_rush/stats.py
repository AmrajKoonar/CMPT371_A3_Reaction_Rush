"""
stats.py — Aggregate per-player statistics from round results.

Small helpers that turn a list of :class:`PlayerRoundResult` for a single
player into a friendly summary dict for the game-over screen and for
persistence. Pure functions, easy to test.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .game_logic import average_reaction, consistency_score, fastest_reaction
from .models import PlayerRoundResult


def summarize_player(
    player_name: str,
    rounds: List[PlayerRoundResult],
) -> Dict[str, Any]:
    """
    Build a per-player summary from their round results.

    Returns keys: player_name, total_score, average_reaction_ms,
    fastest_reaction_ms, slowest_reaction_ms, false_starts, valid_rounds,
    consistency.
    """
    valid_times = [r.adjusted_reaction_ms for r in rounds
                   if r.adjusted_reaction_ms > 0]
    false_starts = sum(1 for r in rounds if r.false_start)
    total_score = sum(r.score for r in rounds)

    return {
        "player_name": player_name,
        "total_score": total_score,
        "average_reaction_ms": round(average_reaction(valid_times), 1),
        "fastest_reaction_ms": round(fastest_reaction(valid_times), 1),
        "slowest_reaction_ms": round(max(valid_times), 1) if valid_times else -1.0,
        "false_starts": false_starts,
        "valid_rounds": len(valid_times),
        "consistency": consistency_score(valid_times),
    }


def summarize_practice(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarise local practice attempts.

    *attempts* is a list of dicts with keys ``reaction_ms`` and
    ``false_start`` (matching the practice_results table). Returns totals,
    fastest/slowest/average, false-start count, and a consistency score.
    """
    valid = [a["reaction_ms"] for a in attempts
             if not a.get("false_start") and a.get("reaction_ms", -1) > 0]
    false_starts = sum(1 for a in attempts if a.get("false_start"))

    return {
        "attempts": len(attempts),
        "valid_attempts": len(valid),
        "false_starts": false_starts,
        "fastest_ms": round(min(valid), 1) if valid else -1.0,
        "slowest_ms": round(max(valid), 1) if valid else -1.0,
        "average_ms": round(sum(valid) / len(valid), 1) if valid else -1.0,
        "consistency": consistency_score(valid),
    }
