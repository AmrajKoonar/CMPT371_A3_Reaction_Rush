"""Tests for rooms, the room manager, sessions, and the state machine."""

import uuid

from reaction_rush import constants as C
from reaction_rush.config import RoomSettings, ServerConfig
from reaction_rush.game_session import GameSession
from reaction_rush.models import PlayerSession
from reaction_rush.room_manager import Room, RoomManager


def _human(name: str) -> PlayerSession:
    """A human session with no real socket (broadcasts become no-ops)."""
    return PlayerSession(
        player_id="p-" + uuid.uuid4().hex[:8], name=name,
        sock=None, connected=True)


def _config() -> ServerConfig:
    return ServerConfig(access_code="RED123", min_players=2, max_players=4)


# ---------------------------------------------------------------------------
# RoomManager
# ---------------------------------------------------------------------------

def test_default_room_exists():
    mgr = RoomManager(_config())
    assert mgr.get_room("RED123") is not None
    assert mgr.get_default_room().code == "RED123"


def test_create_room_unique_codes():
    mgr = RoomManager(_config())
    r1 = mgr.create_room(RoomSettings())
    r2 = mgr.create_room(RoomSettings())
    assert r1.code != r2.code
    assert len(r1.code) == 6


def test_join_and_leave_room():
    mgr = RoomManager(_config())
    room = mgr.create_room(RoomSettings())
    alice = _human("Alice")
    room.add_player(alice)
    assert room.player_count() == 1
    assert room.has_name("alice") is True    # case-insensitive
    room.remove_player(alice.player_id, notify=False)
    assert room.player_count() == 0


def test_rooms_are_isolated():
    mgr = RoomManager(_config())
    r1 = mgr.create_room(RoomSettings())
    r2 = mgr.create_room(RoomSettings())
    r1.add_player(_human("Alice"))
    r2.add_player(_human("Bob"))
    assert r1.player_count() == 1
    assert r2.player_count() == 1
    assert r1.has_name("Bob") is False


def test_empty_non_default_room_cleaned_up():
    mgr = RoomManager(_config())
    room = mgr.create_room(RoomSettings())
    code = room.code
    alice = _human("Alice")
    room.add_player(alice)
    room.remove_player(alice.player_id, notify=False)
    # on_empty callback should have removed the room from the manager.
    assert mgr.get_room(code) is None


def test_host_assignment_and_reassignment():
    room = Room("ABC123", RoomSettings())
    a, b = _human("Alice"), _human("Bob")
    room.add_player(a)
    room.add_player(b)
    assert room.host_id == a.player_id
    room.remove_player(a.player_id, notify=False)
    assert room.host_id == b.player_id


def test_reconnect_requires_matching_token():
    room = Room("ABC123", RoomSettings())
    alice = _human("Alice")
    room.add_player(alice)
    # Simulate a mid-game disconnect (kept in room).
    alice.connected = False

    good = PlayerSession(player_id=alice.player_id, name="Alice",
                         sock=None, session_token=alice.session_token)
    restored = room.reconnect_player(good)
    assert restored is alice
    assert restored.connected is True

    alice.connected = False
    bad = PlayerSession(player_id=alice.player_id, name="Alice",
                        sock=None, session_token="wrong-token")
    assert room.reconnect_player(bad) is None


def test_add_bot_requires_host():
    room = Room("ABC123", RoomSettings(allow_bots=True))
    host = _human("Host")
    other = _human("Other")
    room.add_player(host)
    room.add_player(other)
    # Non-host cannot add a bot.
    room._on_add_bot(other.player_id, C.BOT_AVERAGE)
    assert sum(1 for p in room.players.values() if p.is_bot) == 0
    # Host can.
    room._on_add_bot(host.player_id, C.BOT_AVERAGE)
    assert sum(1 for p in room.players.values() if p.is_bot) == 1


# ---------------------------------------------------------------------------
# GameSession state machine
# ---------------------------------------------------------------------------

def test_state_machine_valid_transitions():
    gs = GameSession(C.MODE_CLASSIC, 5)
    assert gs.state == C.STATE_LOBBY
    assert gs.transition(C.STATE_COUNTDOWN) is True
    assert gs.transition(C.STATE_WAITING_FOR_GO) is True
    assert gs.transition(C.STATE_ACTIVE_ROUND) is True
    assert gs.transition(C.STATE_SCORING) is True


def test_state_machine_rejects_invalid_transition():
    gs = GameSession(C.MODE_CLASSIC, 5)
    # LOBBY -> ACTIVE_ROUND is not allowed.
    assert gs.transition(C.STATE_ACTIVE_ROUND) is False
    assert gs.state == C.STATE_LOBBY


def test_reset_for_new_match_clears_state():
    gs = GameSession(C.MODE_CLASSIC, 5)
    gs.round_number = 3
    gs.eliminated.add("x")
    gs.all_round_results["p"] = ["something"]
    gs.reset_for_new_match(C.MODE_CLASSIC, 5)
    assert gs.round_number == 0
    assert gs.eliminated == set()
    assert gs.all_round_results == {}
    assert gs.state == C.STATE_LOBBY


def test_settings_sanitized():
    s = RoomSettings(mode="nonsense", rounds=999, max_players=999,
                     min_players=0).sanitized()
    assert s.mode == C.MODE_CLASSIC
    assert 1 <= s.rounds <= 20
    assert s.max_players <= 12
    assert s.min_players >= 1


def test_sudden_death_forces_one_round():
    s = RoomSettings(mode=C.MODE_SUDDEN_DEATH, rounds=5).sanitized()
    assert s.rounds == 1
