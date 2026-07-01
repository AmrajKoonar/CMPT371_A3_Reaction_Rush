"""
game_logic.py — Backward-compatibility shim.

The canonical implementation now lives in ``reaction_rush.game_logic``. The
per-round timing constants moved to ``reaction_rush.constants``; they are
re-exported here (with their original names) so legacy imports still work.
"""

from reaction_rush.game_logic import *  # noqa: F401,F403
from reaction_rush.game_logic import (  # noqa: F401
    generate_round_delay, calculate_round_scores,
    calculate_leaderboard, determine_winner,
)
from reaction_rush.models import PlayerRoundResult, PlayerStanding  # noqa: F401
from reaction_rush import constants as _C

# The original v1 module exposed these names directly; re-map them so any
# legacy import (e.g. ``from game_logic import TOTAL_ROUNDS``) keeps working.
TOTAL_ROUNDS = _C.DEFAULT_ROUNDS
MIN_DELAY_SEC = _C.MIN_DELAY_SEC
MAX_DELAY_SEC = _C.MAX_DELAY_SEC
CLICK_TIMEOUT_MS = _C.CLICK_TIMEOUT_MS
PLACEMENT_SCORES = _C.PLACEMENT_SCORES
