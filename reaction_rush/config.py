"""
config.py — Configuration dataclasses and defaults for Reaction Rush v2.

Two config objects live here:

    ServerConfig  — process-wide settings coming from the CLI / env.
    RoomSettings  — per-room game settings chosen by the room host.

Both are plain dataclasses so they serialise easily and are simple to test.
Environment variables (see ``.env.example``) provide optional overrides for
the server defaults; a tiny hand-rolled ``.env`` reader avoids adding the
``python-dotenv`` dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict

from . import constants as C


# ============================================================================
# .env loading (optional, no third-party dependency)
# ============================================================================

def load_env_file(path: str = ".env") -> None:
    """
    Load simple ``KEY=VALUE`` pairs from a .env file into ``os.environ``.

    Existing environment variables are never overwritten. Lines that are
    blank or start with ``#`` are ignored. This is intentionally minimal —
    we only need it for local convenience.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        # A broken .env file must never crash the server
        pass


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ============================================================================
# Server configuration
# ============================================================================

@dataclass
class ServerConfig:
    """Process-wide server configuration (from CLI flags / environment)."""

    host: str = C.DEFAULT_HOST
    port: int = C.DEFAULT_PORT
    access_code: str = C.DEFAULT_ACCESS_CODE
    min_players: int = C.DEFAULT_MIN_PLAYERS
    max_players: int = C.DEFAULT_MAX_PLAYERS
    rounds: int = C.DEFAULT_ROUNDS
    mode: str = C.MODE_CLASSIC

    db_path: str = C.DEFAULT_DB_PATH
    persistence_enabled: bool = True
    latency_compensation: bool = True

    log_level: str = "INFO"
    log_file: str = ""

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Build a config from environment variables (with defaults)."""
        load_env_file()
        return cls(
            host=_env("RR_HOST", C.DEFAULT_HOST),
            port=_env_int("RR_PORT", C.DEFAULT_PORT),
            access_code=_env("RR_ACCESS_CODE", C.DEFAULT_ACCESS_CODE),
            min_players=_env_int("RR_MIN_PLAYERS", C.DEFAULT_MIN_PLAYERS),
            max_players=_env_int("RR_MAX_PLAYERS", C.DEFAULT_MAX_PLAYERS),
            rounds=_env_int("RR_ROUNDS", C.DEFAULT_ROUNDS),
            mode=_env("RR_MODE", C.MODE_CLASSIC),
            db_path=_env("RR_DB_PATH", C.DEFAULT_DB_PATH),
            persistence_enabled=_env_bool("RR_PERSISTENCE", True),
            latency_compensation=_env_bool("RR_LATENCY_COMP", True),
            log_level=_env("RR_LOG_LEVEL", "INFO"),
            log_file=_env("RR_LOG_FILE", ""),
        )


# ============================================================================
# Per-room game settings
# ============================================================================

@dataclass
class RoomSettings:
    """Per-room game settings chosen by the host when creating a room."""

    mode: str = C.MODE_CLASSIC
    rounds: int = C.DEFAULT_ROUNDS
    min_players: int = C.DEFAULT_MIN_PLAYERS
    max_players: int = C.DEFAULT_MAX_PLAYERS
    false_start_penalty: int = C.DEFAULT_FALSE_START_PENALTY_MS
    allow_bots: bool = True
    latency_compensation: bool = True

    def sanitized(self) -> "RoomSettings":
        """Return a copy with all values clamped to safe ranges."""
        mode = self.mode if self.mode in C.ALL_MODES else C.MODE_CLASSIC
        rounds = max(1, min(int(self.rounds), 20))
        max_players = max(2, min(int(self.max_players), 12))
        min_players = max(1, min(int(self.min_players), max_players))
        penalty = max(0, min(int(self.false_start_penalty), 5000))
        # Sudden death is always a single round
        if mode == C.MODE_SUDDEN_DEATH:
            rounds = 1
        return RoomSettings(
            mode=mode,
            rounds=rounds,
            min_players=min_players,
            max_players=max_players,
            false_start_penalty=penalty,
            allow_bots=bool(self.allow_bots),
            latency_compensation=bool(self.latency_compensation),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoomSettings":
        """Build settings from a (possibly partial/untrusted) dict."""
        base = cls()
        if not isinstance(data, dict):
            return base
        return cls(
            mode=str(data.get("mode", base.mode)),
            rounds=int(data.get("rounds", base.rounds)),
            min_players=int(data.get("min_players", base.min_players)),
            max_players=int(data.get("max_players", base.max_players)),
            false_start_penalty=int(
                data.get("false_start_penalty", base.false_start_penalty)),
            allow_bots=bool(data.get("allow_bots", base.allow_bots)),
            latency_compensation=bool(
                data.get("latency_compensation", base.latency_compensation)),
        ).sanitized()


@dataclass
class ClientSettings:
    """Locally-saved client preferences (theme, sound, defaults)."""

    theme: str = "dark"            # dark | light
    sound_enabled: bool = True
    volume: float = 0.7            # 0.0 – 1.0
    default_host: str = C.DEFAULT_HOST
    default_port: int = C.DEFAULT_PORT
    player_name: str = ""
    debug_mode: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClientSettings":
        base = cls()
        if not isinstance(data, dict):
            return base
        return cls(
            theme=str(data.get("theme", base.theme)),
            sound_enabled=bool(data.get("sound_enabled", base.sound_enabled)),
            volume=float(data.get("volume", base.volume)),
            default_host=str(data.get("default_host", base.default_host)),
            default_port=int(data.get("default_port", base.default_port)),
            player_name=str(data.get("player_name", base.player_name)),
            debug_mode=bool(data.get("debug_mode", base.debug_mode)),
        )
