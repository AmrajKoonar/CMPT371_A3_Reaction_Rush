"""
constants.py — Shared constants for Reaction Rush v2.

Keeping every magic string in one place avoids typos across the client,
server, protocol, and tests. All values here are intentionally simple
strings/ints so they serialise cleanly over JSON.
"""

# ============================================================================
# Protocol
# ============================================================================
PROTOCOL_VERSION: int = 2          # bumped from the implicit v1 flat messages
MAX_MESSAGE_SIZE: int = 64 * 1024  # reject frames larger than 64 KiB

# ============================================================================
# Message types
# ============================================================================
# --- v1 messages (kept for backward compatibility) -------------------------
# Client -> Server
MSG_JOIN_REQUEST  = "join_request"
MSG_READY         = "ready"
MSG_CLICK         = "click"
MSG_DISCONNECT    = "disconnect"

# Server -> Client
MSG_JOIN_RESPONSE = "join_response"
MSG_LOBBY_UPDATE  = "lobby_update"
MSG_GAME_START    = "game_start"
MSG_ROUND_PREPARE = "round_prepare"
MSG_ROUND_GO      = "round_go"
MSG_PENALTY       = "penalty"
MSG_ROUND_RESULT  = "round_result"
MSG_GAME_OVER     = "game_over"
MSG_ERROR         = "error"
MSG_PLAYER_LEFT   = "player_left"

# --- v2 messages (new) -----------------------------------------------------
# Rooms (Client -> Server)
MSG_CREATE_ROOM   = "create_room"
MSG_JOIN_ROOM     = "join_room"
MSG_LEAVE_ROOM    = "leave_room"
# Rooms (Server -> Client)
MSG_ROOM_CREATED  = "room_created"
MSG_ROOM_ERROR    = "room_error"

# Rematch
MSG_REMATCH_READY   = "rematch_ready"
MSG_REMATCH_CANCEL  = "rematch_cancel"
MSG_REMATCH_UPDATE  = "rematch_update"
MSG_NEW_MATCH       = "new_match_starting"

# Bots
MSG_ADD_BOT       = "add_bot"
MSG_REMOVE_BOT    = "remove_bot"
MSG_BOT_ADDED     = "bot_added"
MSG_BOT_REMOVED   = "bot_removed"

# Latency / heartbeat
MSG_PING          = "ping"
MSG_PONG          = "pong"
MSG_LATENCY       = "latency_update"

# Reconnect
MSG_RECONNECT          = "reconnect"
MSG_RECONNECT_RESPONSE = "reconnect_response"
MSG_PLAYER_DISCONNECTED = "player_disconnected"
MSG_PLAYER_RECONNECTED  = "player_reconnected"

# Chaos-mode decoy signal
MSG_FAKE_SIGNAL   = "fake_signal"

# Internal-only client message (never sent over the wire)
MSG_INTERNAL_DISCONNECTED = "_disconnected"

# ============================================================================
# Room error codes
# ============================================================================
ERR_ROOM_NOT_FOUND   = "ROOM_NOT_FOUND"
ERR_ROOM_FULL        = "ROOM_FULL"
ERR_NAME_TAKEN       = "NAME_TAKEN"
ERR_INVALID_NAME     = "INVALID_NAME"
ERR_BAD_ACCESS_CODE  = "BAD_ACCESS_CODE"
ERR_GAME_IN_PROGRESS = "GAME_IN_PROGRESS"
ERR_INVALID_TOKEN    = "INVALID_TOKEN"
ERR_NOT_HOST         = "NOT_HOST"

# ============================================================================
# Game state machine
# ============================================================================
STATE_LOBBY          = "LOBBY"
STATE_COUNTDOWN      = "COUNTDOWN"
STATE_WAITING_FOR_GO = "WAITING_FOR_GO"   # red screen
STATE_ACTIVE_ROUND   = "ACTIVE_ROUND"     # green screen
STATE_SCORING        = "SCORING"
STATE_GAME_OVER      = "GAME_OVER"
STATE_REMATCH        = "REMATCH"

# ============================================================================
# Game modes
# ============================================================================
MODE_CLASSIC     = "classic"
MODE_SUDDEN_DEATH = "sudden_death"
MODE_ELIMINATION = "elimination"
MODE_CONSISTENCY = "consistency"
MODE_CHAOS       = "chaos"

ALL_MODES = [
    MODE_CLASSIC,
    MODE_SUDDEN_DEATH,
    MODE_ELIMINATION,
    MODE_CONSISTENCY,
    MODE_CHAOS,
]

# ============================================================================
# Gameplay defaults / bounds
# ============================================================================
DEFAULT_ROUNDS: int = 5
DEFAULT_MIN_PLAYERS: int = 2
DEFAULT_MAX_PLAYERS: int = 8
DEFAULT_FALSE_START_PENALTY_MS: int = 250

MIN_DELAY_SEC: float = 2.0        # shortest red-screen wait
MAX_DELAY_SEC: float = 5.0        # longest red-screen wait
CLICK_TIMEOUT_MS: int = 3000      # time allowed after GO before timeout

# Placement points for valid clicks (classic mode)
PLACEMENT_SCORES = [100, 75, 50, 25]

# Fairness safeguard: adjusted reaction time can never drop below this
MIN_ADJUSTED_REACTION_MS: float = 50.0

# ============================================================================
# Heartbeat / networking
# ============================================================================
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_ACCESS_CODE = "RED123"

PING_INTERVAL_SEC: float = 4.0      # server pings every N seconds
HEARTBEAT_TIMEOUT_SEC: float = 15.0 # mark disconnected after no pong

# ============================================================================
# Persistence
# ============================================================================
DEFAULT_DB_PATH = "reaction_rush.db"
PRACTICE_DB_PATH = "reaction_rush_practice.db"

# ============================================================================
# Bots
# ============================================================================
BOT_BEGINNER = "beginner"
BOT_AVERAGE  = "average"
BOT_PRO      = "pro"
BOT_RISKY    = "risky"

ALL_BOT_LEVELS = [BOT_BEGINNER, BOT_AVERAGE, BOT_PRO, BOT_RISKY]
