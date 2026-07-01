"""
utils.py — Backward-compatibility shim.

The canonical implementation now lives in ``reaction_rush.utils``. This module
re-exports it so any legacy import keeps working unchanged.
"""

from reaction_rush.utils import *  # noqa: F401,F403
from reaction_rush.utils import (  # noqa: F401
    safe_close, timestamp, format_ms, clamp, valid_player_name,
)
