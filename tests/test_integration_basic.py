"""
Basic end-to-end integration test.

Starts a real :class:`ServerApp` in a background thread, connects two fake
TCP clients, plays one fast round, and asserts a ``game_over`` message is
received. Round delays are patched short so the test runs in a few seconds.
"""

import socket
import threading
import time

import pytest

from reaction_rush import constants as C
from reaction_rush.config import ServerConfig
from reaction_rush.protocol import make_message, receive_messages, send_message
from reaction_rush.server_app import ServerApp


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def fast_rounds(monkeypatch):
    """Shorten the random red-screen delay so the game runs quickly."""
    monkeypatch.setattr(C, "MIN_DELAY_SEC", 0.05)
    monkeypatch.setattr(C, "MAX_DELAY_SEC", 0.12)
    yield


@pytest.fixture()
def server(fast_rounds):
    port = _free_port()
    config = ServerConfig(
        host="127.0.0.1", port=port, access_code="RED123",
        min_players=2, rounds=1, persistence_enabled=False)
    app = ServerApp(config, db=None)
    thread = threading.Thread(target=app.start, daemon=True)
    thread.start()
    time.sleep(0.4)   # let it bind
    yield port, app
    app.shutdown()
    thread.join(timeout=2.0)


def _run_client(port: int, name: str, out: dict) -> None:
    """Connect, join, ready, click on GO, and record the game_over message."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    s.connect(("127.0.0.1", port))
    send_message(s, make_message(
        C.MSG_JOIN_REQUEST, player_name=name, access_code="RED123"))

    buf = ""
    deadline = time.time() + 20
    joined = ready_sent = False
    while time.time() < deadline:
        msgs, buf = receive_messages(s, buf)
        if msgs is None:
            break
        for m in msgs:
            t = m.get("type")
            if t == C.MSG_JOIN_RESPONSE and m.get("success"):
                joined = True
            elif t == C.MSG_LOBBY_UPDATE and joined and not ready_sent:
                send_message(s, make_message(C.MSG_READY))
                ready_sent = True
            elif t == C.MSG_ROUND_GO:
                # React quickly after the green signal.
                send_message(s, make_message(
                    C.MSG_CLICK, early=False,
                    round_number=m.get("round_number")))
            elif t == C.MSG_PING:
                send_message(s, make_message(
                    C.MSG_PONG, server_time=m.get("server_time")))
            elif t == C.MSG_GAME_OVER:
                out[name] = m
                s.close()
                return
    s.close()


def test_full_game_flow(server):
    port, _app = server
    results: dict = {}
    t1 = threading.Thread(target=_run_client, args=(port, "Alice", results))
    t2 = threading.Thread(target=_run_client, args=(port, "Bob", results))
    t1.start(); t2.start()
    t1.join(timeout=25); t2.join(timeout=25)

    assert "Alice" in results, "Alice never received game_over"
    assert "Bob" in results, "Bob never received game_over"
    go = results["Alice"]
    assert go["type"] == C.MSG_GAME_OVER
    assert "final_leaderboard" in go
    assert go["winner"] in ("Alice", "Bob")


def test_bad_access_code_rejected(server):
    port, _app = server
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(("127.0.0.1", port))
    send_message(s, make_message(
        C.MSG_JOIN_REQUEST, player_name="Eve", access_code="WRONG"))
    buf = ""
    msg = None
    deadline = time.time() + 5
    while time.time() < deadline and msg is None:
        msgs, buf = receive_messages(s, buf)
        if msgs is None:
            break
        for m in msgs:
            if m.get("type") == C.MSG_JOIN_RESPONSE:
                msg = m
                break
    s.close()
    assert msg is not None
    assert msg["success"] is False


def test_create_and_join_room(server):
    port, _app = server
    # Host creates a room.
    host = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    host.settimeout(3.0)
    host.connect(("127.0.0.1", port))
    send_message(host, make_message(
        C.MSG_CREATE_ROOM, player_name="Host", settings={"mode": "classic"}))

    buf = ""
    room_code = None
    deadline = time.time() + 5
    while time.time() < deadline and room_code is None:
        msgs, buf = receive_messages(host, buf)
        if msgs is None:
            break
        for m in msgs:
            if m.get("type") == C.MSG_ROOM_CREATED:
                room_code = m.get("room_code")
    assert room_code, "did not receive room_created"

    # Another player joins by code.
    guest = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    guest.settimeout(3.0)
    guest.connect(("127.0.0.1", port))
    send_message(guest, make_message(
        C.MSG_JOIN_ROOM, room_code=room_code, player_name="Guest"))

    gbuf = ""
    ok = False
    deadline = time.time() + 5
    while time.time() < deadline and not ok:
        msgs, gbuf = receive_messages(guest, gbuf)
        if msgs is None:
            break
        for m in msgs:
            if m.get("type") == C.MSG_JOIN_RESPONSE and m.get("success"):
                ok = True
    host.close(); guest.close()
    assert ok, "guest could not join the created room"
