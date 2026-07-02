"""
persistence.py — Optional SQLite persistence (standard library only).

Uses ``sqlite3`` from the Python standard library. The database is opened
with ``check_same_thread=False`` and every write is guarded by a lock,
because the server touches it from multiple threads (client handlers, room
game threads).

Persistence is optional: if disabled, the server simply never constructs a
``Database``. The client uses the same class for local practice stats.

Tables
------
players, matches, match_participants, round_results, practice_results,
personal_bests. See ``_SCHEMA`` below for the exact DDL.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from .logging_config import get_logger

log = get_logger("persistence")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id                TEXT PRIMARY KEY,
    room_code         TEXT NOT NULL,
    mode              TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    winner_player_id  TEXT
);

CREATE TABLE IF NOT EXISTS match_participants (
    id           TEXT PRIMARY KEY,
    match_id     TEXT NOT NULL,
    player_id    TEXT NOT NULL,
    player_name  TEXT NOT NULL,
    total_score  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS round_results (
    id                    TEXT PRIMARY KEY,
    match_id              TEXT NOT NULL,
    round_number          INTEGER NOT NULL,
    player_id             TEXT NOT NULL,
    player_name           TEXT NOT NULL,
    raw_reaction_ms       REAL,
    adjusted_reaction_ms  REAL,
    false_start           INTEGER NOT NULL DEFAULT 0,
    score_delta           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS practice_results (
    id           TEXT PRIMARY KEY,
    player_name  TEXT NOT NULL,
    reaction_ms  REAL,
    false_start  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personal_bests (
    player_name    TEXT PRIMARY KEY,
    best_reaction  REAL NOT NULL,
    updated_at     TEXT NOT NULL
);
"""


def _now() -> str:
    """ISO-8601 UTC timestamp string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _uid() -> str:
    return uuid.uuid4().hex


class Database:
    """Thread-safe wrapper around a SQLite connection."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        # check_same_thread=False because the server uses this from several
        # threads; the lock below serialises all access.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        log.info("SQLite persistence ready at %s", os.path.abspath(path))

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---------------------------------------------------------------- players
    def upsert_player(self, name: str, player_id: Optional[str] = None) -> str:
        """Insert a player if new; return their id."""
        pid = player_id or _uid()
        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM players WHERE name = ?", (name,))
            row = cur.fetchone()
            if row:
                return row["id"]
            self._conn.execute(
                "INSERT INTO players (id, name, created_at) VALUES (?, ?, ?)",
                (pid, name, _now()))
            self._conn.commit()
        return pid

    # ---------------------------------------------------------------- matches
    def start_match(self, room_code: str, mode: str) -> str:
        """Create a match row and return its id."""
        mid = _uid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO matches (id, room_code, mode, started_at) "
                "VALUES (?, ?, ?, ?)",
                (mid, room_code, mode, _now()))
            self._conn.commit()
        return mid

    def finish_match(self, match_id: str, winner_player_id: Optional[str],
                     participants: List[Dict[str, Any]]) -> None:
        """Mark a match finished and store participant totals."""
        with self._lock:
            self._conn.execute(
                "UPDATE matches SET ended_at = ?, winner_player_id = ? "
                "WHERE id = ?",
                (_now(), winner_player_id, match_id))
            for p in participants:
                self._conn.execute(
                    "INSERT INTO match_participants "
                    "(id, match_id, player_id, player_name, total_score) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (_uid(), match_id, p.get("player_id", ""),
                     p.get("player_name", ""), int(p.get("total_score", 0))))
            self._conn.commit()

    def save_round_result(self, match_id: str, round_number: int,
                          player_id: str, player_name: str,
                          raw_reaction_ms: Optional[float],
                          adjusted_reaction_ms: Optional[float],
                          false_start: bool, score_delta: int) -> None:
        """Persist one player's result for one round."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO round_results (id, match_id, round_number, "
                "player_id, player_name, raw_reaction_ms, adjusted_reaction_ms, "
                "false_start, score_delta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_uid(), match_id, round_number, player_id, player_name,
                 raw_reaction_ms, adjusted_reaction_ms,
                 1 if false_start else 0, score_delta))
            self._conn.commit()

    # --------------------------------------------------------------- practice
    def save_practice_result(self, player_name: str,
                             reaction_ms: Optional[float],
                             false_start: bool) -> None:
        """Persist a single local practice attempt."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO practice_results (id, player_name, reaction_ms, "
                "false_start, created_at) VALUES (?, ?, ?, ?, ?)",
                (_uid(), player_name, reaction_ms,
                 1 if false_start else 0, _now()))
            # Update personal best for valid attempts
            if not false_start and reaction_ms is not None and reaction_ms > 0:
                cur = self._conn.execute(
                    "SELECT best_reaction FROM personal_bests WHERE player_name = ?",
                    (player_name,))
                row = cur.fetchone()
                if row is None:
                    self._conn.execute(
                        "INSERT INTO personal_bests (player_name, best_reaction, "
                        "updated_at) VALUES (?, ?, ?)",
                        (player_name, reaction_ms, _now()))
                elif reaction_ms < row["best_reaction"]:
                    self._conn.execute(
                        "UPDATE personal_bests SET best_reaction = ?, "
                        "updated_at = ? WHERE player_name = ?",
                        (reaction_ms, _now(), player_name))
            self._conn.commit()

    def get_practice_results(self, player_name: str) -> List[Dict[str, Any]]:
        """Return all practice attempts for a player (most recent first)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT reaction_ms, false_start, created_at FROM practice_results "
                "WHERE player_name = ? ORDER BY created_at DESC",
                (player_name,))
            return [
                {
                    "reaction_ms": r["reaction_ms"],
                    "false_start": bool(r["false_start"]),
                    "created_at": r["created_at"],
                }
                for r in cur.fetchall()
            ]

    def get_personal_best(self, player_name: str) -> Optional[float]:
        """Return the best (lowest) practice reaction time for a player."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT best_reaction FROM personal_bests WHERE player_name = ?",
                (player_name,))
            row = cur.fetchone()
            return row["best_reaction"] if row else None

    def reset_practice_results(self, player_name: str) -> None:
        """Delete all practice attempts and the personal best for a player."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM practice_results WHERE player_name = ?",
                (player_name,))
            self._conn.execute(
                "DELETE FROM personal_bests WHERE player_name = ?",
                (player_name,))
            self._conn.commit()

    # ------------------------------------------------------------------ stats
    def get_player_match_count(self, player_name: str) -> int:
        """Return how many matches a player has participated in."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) AS c FROM match_participants WHERE player_name = ?",
                (player_name,))
            return int(cur.fetchone()["c"])

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
