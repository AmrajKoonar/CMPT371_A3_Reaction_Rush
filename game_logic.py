"""
game_logic.py — Core game rules for Reaction Rush.

All scoring, leaderboard, and round-generation logic lives here so that
server.py stays focused on networking and client.py on the GUI.

Scoring model (per round)
-------------------------
1. Valid reaction times are sorted fastest → slowest.
2. 1st place  → 100 pts
   2nd place  → 75 pts
   3rd place  → 50 pts
   4th+ place → 25 pts
3. False starts and timeouts receive 0 pts.

Final winner
------------
Highest cumulative score.  Ties broken by lowest total reaction time.
"""

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Tuning constants (importable by server.py)
# ---------------------------------------------------------------------------
TOTAL_ROUNDS: int = 5            # number of rounds per game
MIN_DELAY_SEC: float = 2.0       # shortest red-screen wait (seconds)
MAX_DELAY_SEC: float = 5.0       # longest  red-screen wait (seconds)
CLICK_TIMEOUT_MS: int = 3000     # time allowed after GO before timeout (ms)

# Points awarded by placement within a round
PLACEMENT_SCORES: List[int] = [100, 75, 50, 25]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class PlayerRoundResult:
    """One player's outcome for a single round."""
    player_name: str
    reaction_time_ms: float     # negative means invalid (false start / timeout)
    score: int
    false_start: bool
    timed_out: bool


@dataclass
class PlayerStanding:
    """Aggregate standing used to build the leaderboard."""
    player_name: str
    total_score: int
    total_reaction_time_ms: float


# ---------------------------------------------------------------------------
# Pure functions — no side effects, easy to unit-test
# ---------------------------------------------------------------------------

def generate_round_delay() -> float:
    """Return a random red-screen duration in **seconds**."""
    return random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)


def calculate_round_scores(
    reactions: Dict[str, Optional[float]],
    false_starts: Set[str],
    timed_out: Set[str],
) -> List[PlayerRoundResult]:
    """
    Compute scores for a single round.

    Parameters
    ----------
    reactions : dict
        ``{player_name: reaction_ms}``  (``None`` when no valid click).
    false_starts : set
        Names of players who clicked before green.
    timed_out : set
        Names of players who never clicked in time.

    Returns
    -------
    list[PlayerRoundResult]
        One entry per player, order is fastest-valid first, then
        false-starts, then timeouts.
    """
    results: List[PlayerRoundResult] = []
    valid: Dict[str, float] = {}

    for name in reactions:
        if name in false_starts:
            results.append(PlayerRoundResult(name, -1, 0, True, False))
        elif name in timed_out:
            results.append(PlayerRoundResult(name, -1, 0, False, True))
        elif reactions[name] is not None and reactions[name] >= 0:
            valid[name] = reactions[name]
        else:
            # Safety net — treat unknown state as timeout
            results.append(PlayerRoundResult(name, -1, 0, False, True))

    # Rank valid players from fastest to slowest
    for rank, (name, rt) in enumerate(sorted(valid.items(), key=lambda x: x[1])):
        score = (
            PLACEMENT_SCORES[rank]
            if rank < len(PLACEMENT_SCORES)
            else PLACEMENT_SCORES[-1]
        )
        results.append(PlayerRoundResult(name, rt, score, False, False))

    return results


def calculate_leaderboard(
    all_results: Dict[str, List[PlayerRoundResult]],
) -> List[PlayerStanding]:
    """
    Build the leaderboard from accumulated round results.

    Sorted by **total score descending**, then **total reaction time
    ascending** as a tie-breaker (lower cumulative time wins).
    """
    standings: List[PlayerStanding] = []
    for name, rounds in all_results.items():
        total_score = sum(r.score for r in rounds)
        # Only sum positive (valid) reaction times for the tie-breaker
        total_time = sum(r.reaction_time_ms for r in rounds if r.reaction_time_ms > 0)
        standings.append(PlayerStanding(name, total_score, total_time))

    standings.sort(key=lambda s: (-s.total_score, s.total_reaction_time_ms))
    return standings


def determine_winner(standings: List[PlayerStanding]) -> Optional[str]:
    """Return the name of the first-place player, or ``None``."""
    return standings[0].player_name if standings else None
