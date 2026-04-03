"""
game_logic.py

Core game rules for Reaction Rush.

This file keeps the pure game logic separate from networking:
- random round delay
- round scoring
- leaderboard building
- final winner selection
"""

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

TOTAL_ROUNDS: int = 5
MIN_DELAY_SEC: float = 2.0
MAX_DELAY_SEC: float = 5.0
CLICK_TIMEOUT_MS: int = 3000

# Points by placement for valid clicks
PLACEMENT_SCORES: List[int] = [100, 75, 50, 25]

@dataclass
class PlayerRoundResult:
    """Stores one player's result for a single round"""
    player_name: str
    reaction_time_ms: float     # negative value means no valid reaction
    score: int
    false_start: bool
    timed_out: bool


@dataclass
class PlayerStanding:
    """Stores the overall score and total reaction time"""
    player_name: str
    total_score: int
    total_reaction_time_ms: float

def generate_round_delay() -> float:
    """Pick a random delay before the screen turns green"""
    return random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)


def calculate_round_scores(
    reactions: Dict[str, Optional[float]],
    false_starts: Set[str],
    timed_out: Set[str],
) -> List[PlayerRoundResult]:
    """Calculate the round results from clicks, false starts, and timeouts"""
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
            # If something unexpected slips through, treat it like a miss
            results.append(PlayerRoundResult(name, -1, 0, False, True))

    # Valid clicks are sorted from fastest to slowest, then scored by place
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
    """Build the current leaderboard from all saved round results"""
    standings: List[PlayerStanding] = []
    for name, rounds in all_results.items():
        total_score = sum(r.score for r in rounds)
        # Only valid reaction times count for the tie-break
        total_time = sum(r.reaction_time_ms for r in rounds if r.reaction_time_ms > 0)
        standings.append(PlayerStanding(name, total_score, total_time))

    standings.sort(key=lambda s: (-s.total_score, s.total_reaction_time_ms))
    return standings


def determine_winner(standings: List[PlayerStanding]) -> Optional[str]:
    """Return the winner's name if there is one"""
    return standings[0].player_name if standings else None
