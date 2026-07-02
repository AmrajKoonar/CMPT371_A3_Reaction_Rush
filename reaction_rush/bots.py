"""
bots.py — Server-side bot players.

Bots are ordinary :class:`PlayerSession` objects with ``is_bot=True`` and no
socket. The room game loop asks a bot for its behaviour each round:

* whether it false-starts (clicks during the red screen), and
* how fast it reacts once the green screen appears.

Because bots live entirely on the server, they behave exactly like humans
from the game state's point of view — they appear in the lobby, ready up,
participate in rounds, and show up on the leaderboard, all without a network
connection.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from typing import Dict, Tuple

from . import constants as C
from .models import PlayerSession


@dataclass(frozen=True)
class BotProfile:
    """Behavioural profile for a bot skill level."""

    level: str
    display_name: str
    reaction_min_ms: float
    reaction_max_ms: float
    false_start_chance: float   # probability of a false start in a round


# Tuning table for each bot level (see the assignment spec).
BOT_PROFILES: Dict[str, BotProfile] = {
    C.BOT_BEGINNER: BotProfile(C.BOT_BEGINNER, "Beginner Bot", 450, 700, 0.03),
    C.BOT_AVERAGE:  BotProfile(C.BOT_AVERAGE,  "Average Bot",  250, 400, 0.08),
    C.BOT_PRO:      BotProfile(C.BOT_PRO,      "Pro Bot",      160, 240, 0.02),
    C.BOT_RISKY:    BotProfile(C.BOT_RISKY,    "Risky Bot",    120, 220, 0.20),
}

# Fun names so multiple bots of the same level are distinguishable.
_BOT_NAMES = [
    "Blitz", "Volt", "Nova", "Echo", "Pixel", "Turbo", "Zephyr",
    "Dash", "Comet", "Rocket", "Flash", "Bolt", "Rapid", "Swift",
]


def make_bot(level: str, existing_names: set) -> PlayerSession:
    """
    Create a new bot :class:`PlayerSession` for the given level.

    A readable, unique display name is chosen (e.g. "Blitz-Bot"). Falls back
    to the average profile if an unknown level is passed.
    """
    profile = BOT_PROFILES.get(level, BOT_PROFILES[C.BOT_AVERAGE])
    name = _unique_bot_name(existing_names)
    return PlayerSession(
        player_id="bot-" + uuid.uuid4().hex[:8],
        name=name,
        sock=None,
        address=None,
        ready=True,            # bots are always ready
        connected=True,
        is_bot=True,
        bot_level=profile.level,
    )


def _unique_bot_name(existing_names: set) -> str:
    """Pick a bot name not already used in the room."""
    random.shuffle(_BOT_NAMES)
    for base in _BOT_NAMES:
        candidate = f"{base}-Bot"
        if candidate.lower() not in {n.lower() for n in existing_names}:
            return candidate
    # Fallback: guarantee uniqueness with a numeric suffix.
    return f"Bot-{random.randint(1000, 9999)}"


def decide_bot_round(level: str) -> Tuple[bool, float]:
    """
    Decide a bot's behaviour for one round.

    Returns
    -------
    (false_start, reaction_ms)
        * ``false_start`` — True if the bot clicks during the red screen.
        * ``reaction_ms`` — reaction time after green (ignored on false start).
    """
    profile = BOT_PROFILES.get(level, BOT_PROFILES[C.BOT_AVERAGE])
    if random.random() < profile.false_start_chance:
        return True, -1.0
    reaction = random.uniform(profile.reaction_min_ms, profile.reaction_max_ms)
    return False, reaction


def bot_false_start_delay(pre_green_delay: float) -> float:
    """
    When a bot false-starts, choose *when* during the red window it clicks.

    Returned as seconds from the start of the prepare phase, always strictly
    before the real green signal.
    """
    if pre_green_delay <= 0.5:
        return max(0.1, pre_green_delay * 0.5)
    return random.uniform(0.3, pre_green_delay - 0.2)
