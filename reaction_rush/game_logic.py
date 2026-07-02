"""
game_logic.py — Pure scoring and round logic for every game mode.

This module contains **no networking and no threading** — only deterministic
functions over plain data. That keeps it fully unit-testable and lets the
room code stay focused on orchestration.

Scoring overview
----------------
* Classic / Chaos : placement points (1st=100, 2nd=75, 3rd=50, 4th+=25).
* Sudden Death    : single round, fastest valid click wins.
* Elimination     : slowest valid player eliminated each round.
* Consistency     : ranked by best average valid reaction time.

False starts and timeouts always score 0 points for the round.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Dict, List, Optional, Set

from . import constants as C
from .models import PlayerRoundResult, PlayerStanding


# ============================================================================
# Round timing
# ============================================================================

def generate_round_delay() -> float:
    """Return a random red-screen duration in seconds (server-controlled)."""
    return random.uniform(C.MIN_DELAY_SEC, C.MAX_DELAY_SEC)


def generate_fake_signal_delays(pre_green_delay: float) -> List[float]:
    """
    For Chaos mode: produce 0-2 decoy-signal offsets (seconds from prepare)
    that all occur strictly before the real green at ``pre_green_delay``.

    Clicking during a decoy is a false start (the server is still in the
    WAITING_FOR_GO phase), so no unsafe rapid flashing is required.
    """
    if pre_green_delay < 1.2:
        return []
    count = random.choice([0, 1, 1, 2])
    delays: List[float] = []
    for _ in range(count):
        # Keep decoys within the wait window, leaving a margin before green.
        offset = random.uniform(0.4, max(0.5, pre_green_delay - 0.4))
        delays.append(offset)
    return sorted(delays)


# ============================================================================
# Basic statistics helpers
# ============================================================================

def average_reaction(times: List[float]) -> float:
    """Mean of valid (>0) reaction times, or -1 if there are none."""
    valid = [t for t in times if t is not None and t > 0]
    return sum(valid) / len(valid) if valid else -1.0


def fastest_reaction(times: List[float]) -> float:
    """Fastest valid reaction time, or -1 if there are none."""
    valid = [t for t in times if t is not None and t > 0]
    return min(valid) if valid else -1.0


def consistency_score(times: List[float]) -> float:
    """
    Consistency metric based on the population standard deviation of valid
    reaction times. Lower is better (more consistent). Returns -1 when there
    are fewer than two valid samples.
    """
    valid = [t for t in times if t is not None and t > 0]
    if len(valid) < 2:
        return -1.0
    return round(statistics.pstdev(valid), 1)


# ============================================================================
# Per-round scoring
# ============================================================================

def calculate_round_scores(
    reactions: Dict[str, Optional[float]],
    false_starts: Set[str],
    timed_out: Set[str],
) -> List[PlayerRoundResult]:
    """
    Classic placement scoring (v1-compatible entry point).

    Kept with its original signature so existing callers/tests continue to
    work. Internally delegates to :func:`compute_round_results`.
    """
    players_data: Dict[str, dict] = {}
    for name, rt in reactions.items():
        players_data[name] = {
            "reaction": rt,
            "adjusted": rt,
            "false_start": name in false_starts,
            "timed_out": name in timed_out,
            "suspicious": False,
        }
    return compute_round_results(players_data, C.MODE_CLASSIC,
                                 C.DEFAULT_FALSE_START_PENALTY_MS)


def compute_round_results(
    players_data: Dict[str, dict],
    mode: str,
    penalty_ms: int,
) -> List[PlayerRoundResult]:
    """
    Compute per-round results for any mode.

    Parameters
    ----------
    players_data : dict
        ``name -> {"reaction", "adjusted", "false_start", "timed_out",
        "suspicious"}``. ``reaction``/``adjusted`` may be None for invalid.
    mode : str
        One of the ``MODE_*`` constants.
    penalty_ms : int
        False-start penalty (used by consistency mode averaging).

    Returns
    -------
    list[PlayerRoundResult]
        Valid players first (fastest → slowest), then invalid players.
    """
    results: List[PlayerRoundResult] = []
    valid: Dict[str, float] = {}       # name -> adjusted time used for ranking

    for name, d in players_data.items():
        fs = bool(d.get("false_start"))
        to = bool(d.get("timed_out"))
        raw = d.get("reaction")
        adj = d.get("adjusted", raw)
        suspicious = bool(d.get("suspicious"))

        if fs:
            results.append(PlayerRoundResult(
                name, -1.0, -1.0, 0, false_start=True, suspicious=suspicious))
        elif to:
            results.append(PlayerRoundResult(
                name, -1.0, -1.0, 0, timed_out=True))
        elif raw is not None and raw >= 0:
            valid[name] = adj if (adj is not None and adj >= 0) else raw
        else:
            results.append(PlayerRoundResult(name, -1.0, -1.0, 0, timed_out=True))

    ranked = sorted(valid.items(), key=lambda kv: kv[1])

    for rank, (name, adj) in enumerate(ranked):
        raw = players_data[name].get("reaction")
        suspicious = bool(players_data[name].get("suspicious"))
        score = _placement_score(rank, mode, len(ranked))
        results.append(PlayerRoundResult(
            name,
            float(raw if raw is not None else adj),
            float(adj),
            score,
            suspicious=suspicious,
        ))

    return results


def _placement_score(rank: int, mode: str, num_valid: int) -> int:
    """Return the point value for a given placement under *mode*."""
    if mode == C.MODE_SUDDEN_DEATH:
        # Only the fastest valid player scores in sudden death.
        return 100 if rank == 0 else 0
    if rank < len(C.PLACEMENT_SCORES):
        return C.PLACEMENT_SCORES[rank]
    return C.PLACEMENT_SCORES[-1]


# ============================================================================
# Elimination helper
# ============================================================================

def choose_eliminations(
    round_results: List[PlayerRoundResult],
    active_names: Set[str],
    eliminate_false_starts: bool = True,
) -> List[str]:
    """
    Decide who is eliminated this round (elimination mode).

    Rules
    -----
    * Players who false-started or timed out are "at risk".
    * If any at-risk players exist, they are eliminated.
    * Otherwise the single slowest valid player is eliminated.
    * A guard in the caller prevents eliminating the entire remaining field.
    """
    at_risk: List[str] = []
    valid: List[PlayerRoundResult] = []

    for r in round_results:
        if r.player_name not in active_names:
            continue
        if r.false_start:
            if eliminate_false_starts:
                at_risk.append(r.player_name)
        elif r.timed_out:
            at_risk.append(r.player_name)
        else:
            valid.append(r)

    if at_risk:
        return at_risk

    if valid:
        slowest = max(valid, key=lambda r: r.adjusted_reaction_ms)
        return [slowest.player_name]

    return []


# ============================================================================
# Leaderboard
# ============================================================================

def calculate_leaderboard(
    all_results: Dict[str, List[PlayerRoundResult]],
) -> List[PlayerStanding]:
    """Classic leaderboard (v1-compatible). Sorts by score, then total time."""
    return build_leaderboard(all_results, C.MODE_CLASSIC, set())


def build_leaderboard(
    all_results: Dict[str, List[PlayerRoundResult]],
    mode: str,
    eliminated: Set[str],
) -> List[PlayerStanding]:
    """
    Build a leaderboard for any mode.

    Parameters
    ----------
    all_results : dict
        ``name -> [PlayerRoundResult, ...]`` accumulated across rounds.
    mode : str
        Game mode (affects sort order).
    eliminated : set
        Names of eliminated players (elimination mode).
    """
    standings: List[PlayerStanding] = []

    for name, rounds in all_results.items():
        valid_times = [r.adjusted_reaction_ms for r in rounds
                       if r.adjusted_reaction_ms > 0]
        total_score = sum(r.score for r in rounds)
        total_time = sum(valid_times)
        false_starts = sum(1 for r in rounds if r.false_start)

        # A "round won" = best (positive) score that round among nobody else...
        # We approximate rounds_won as rounds where this player scored the max
        # placement (100). This is informational only.
        rounds_won = sum(1 for r in rounds if r.score == C.PLACEMENT_SCORES[0])

        standings.append(PlayerStanding(
            player_name=name,
            total_score=total_score,
            total_reaction_time_ms=total_time,
            average_reaction_ms=average_reaction(valid_times),
            fastest_reaction_ms=fastest_reaction(valid_times),
            false_starts=false_starts,
            rounds_won=rounds_won,
            consistency=consistency_score(valid_times),
            eliminated=name in eliminated,
        ))

    _sort_standings(standings, mode)
    return standings


def _sort_standings(standings: List[PlayerStanding], mode: str) -> None:
    """Sort *standings* in place according to *mode*."""
    if mode == C.MODE_CONSISTENCY:
        # Best average valid reaction time wins. Players with no valid time
        # (average -1) go last. False starts already hurt the average via the
        # room feeding penalty-inflated times.
        def key(s: PlayerStanding):
            avg = s.average_reaction_ms if s.average_reaction_ms > 0 else math.inf
            return (avg, s.false_starts, -s.total_score)
        standings.sort(key=key)
    elif mode == C.MODE_ELIMINATION:
        # Survivors first, then by score, then by lower total reaction time.
        standings.sort(key=lambda s: (
            s.eliminated, -s.total_score, s.total_reaction_time_ms))
    else:
        # Classic / sudden death / chaos: highest score, then lowest total time.
        standings.sort(key=lambda s: (
            -s.total_score, s.total_reaction_time_ms))


def determine_winner(standings: List[PlayerStanding]) -> Optional[str]:
    """Return the first-place player's name, or None."""
    for s in standings:
        if not s.eliminated:
            return s.player_name
    return standings[0].player_name if standings else None


# ============================================================================
# Latency compensation
# ============================================================================

def adjust_reaction_for_latency(
    raw_ms: float,
    one_way_latency_ms: float,
    enabled: bool,
) -> float:
    """
    Compensate a raw server-measured reaction time for a player's latency.

    The server remains authoritative: the raw time is what the server
    actually measured (GO-sent → click-received). We subtract one round of
    latency to approximate the player's true reaction, bounded so nobody can
    reach an impossible sub-``MIN_ADJUSTED_REACTION_MS`` time.

    When *enabled* is False the raw value is returned unchanged.
    """
    if not enabled or raw_ms < 0:
        return raw_ms
    adjusted = raw_ms - max(0.0, one_way_latency_ms)
    return max(C.MIN_ADJUSTED_REACTION_MS, adjusted)


def is_suspicious(raw_ms: float) -> bool:
    """
    Flag implausibly fast reactions (< 80 ms) as suspicious. Human simple
    reaction time is almost never below ~100 ms, so anything faster is
    marked for review rather than blindly trusted.
    """
    return 0 <= raw_ms < 80.0
