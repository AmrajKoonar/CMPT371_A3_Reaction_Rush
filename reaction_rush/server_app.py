"""
server_app.py — TCP server application for Reaction Rush v2.

Responsibilities
----------------
* Own the listening socket and the accept loop.
* Spawn one receiver thread per connection.
* Route messages: room lifecycle (join/create/reconnect) is handled here;
  in-room messages (ready/click/rematch/bots) are forwarded to the player's
  :class:`~reaction_rush.room_manager.Room`.
* Run a heartbeat thread (ping/pong) to measure latency and detect silent
  disconnects.
* Shut down cleanly on Ctrl+C.

Backward compatibility
-----------------------
The original ``join_request`` + ``access_code`` flow still works and places
the player into the **default room** (bound to the server access code), so
the v1 client and the documented run commands behave exactly as before.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from typing import Dict, Optional

from . import constants as C
from .config import RoomSettings, ServerConfig
from .logging_config import get_logger, setup_logging
from .models import PlayerSession
from .protocol import make_message, receive_messages, send_message
from .room_manager import Room, RoomManager
from .utils import safe_close

log = get_logger("server")


class _Connection:
    """Tracks the live session bound to one socket (mutable across reconnect)."""

    def __init__(self, session: PlayerSession) -> None:
        self.session = session      # current PlayerSession for this socket


class ServerApp:
    """The Reaction Rush TCP server."""

    def __init__(self, config: ServerConfig, db=None) -> None:
        self.config = config
        self.db = db
        self.rooms = RoomManager(config, db=db)

        self.server_socket: Optional[socket.socket] = None
        self.running = False

        # All currently-connected sessions, keyed by player_id (for heartbeat).
        self._sessions: Dict[str, PlayerSession] = {}
        self._sessions_lock = threading.Lock()
        self._next_conn = 0

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Bind, listen, start the heartbeat, and enter the accept loop."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)
        self.server_socket.bind((self.config.host, self.config.port))
        self.server_socket.listen(16)
        self.running = True

        log.info("Reaction Rush v2 server listening on %s:%d",
                 self.config.host, self.config.port)
        log.info("Default room access code: %s", self.config.access_code)
        log.info("Mode=%s  rounds=%d  min_players=%d  max_players=%d",
                 self.config.mode, self.config.rounds,
                 self.config.min_players, self.config.max_players)
        log.info("Persistence: %s | Latency compensation: %s",
                 "on" if self.db else "off",
                 "on" if self.config.latency_compensation else "off")

        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        self._accept_loop()

    def shutdown(self) -> None:
        """Notify clients, close rooms and sockets, and stop."""
        log.info("Shutting down …")
        self.running = False
        self.rooms.close_all()

        with self._sessions_lock:
            sessions = list(self._sessions.values())
        for s in sessions:
            if s.sock is not None:
                send_message(s.sock, make_message(
                    C.MSG_DISCONNECT, message="Server shutting down."))
                safe_close(s.sock)

        safe_close(self.server_socket)
        if self.db is not None:
            self.db.close()
        log.info("Server stopped.")

    # -----------------------------------------------------------------------
    # Accept loop
    # -----------------------------------------------------------------------

    def _accept_loop(self) -> None:
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            log.info("New connection from %s", addr)
            threading.Thread(
                target=self._handle_connection,
                args=(client_sock, addr),
                daemon=True,
            ).start()

    # -----------------------------------------------------------------------
    # Per-connection handler
    # -----------------------------------------------------------------------

    def _handle_connection(self, sock: socket.socket, addr: tuple) -> None:
        """Receive-loop for one socket until it disconnects."""
        sock.settimeout(1.0)
        with self._sessions_lock:
            self._next_conn += 1
        session = PlayerSession(
            player_id="p-" + str(self._next_conn) + "-" + str(int(time.time() * 1000) % 100000),
            name="",
            sock=sock,
            address=addr,
        )
        conn = _Connection(session)
        with self._sessions_lock:
            self._sessions[session.player_id] = session

        buf = ""
        while self.running:
            msgs, buf = receive_messages(sock, buf)
            if msgs is None:
                break
            for m in msgs:
                try:
                    self._route(conn, m)
                except Exception:  # pragma: no cover - defensive
                    log.exception("Error handling message %r", m.get("type"))

        self._cleanup_connection(conn)

    def _cleanup_connection(self, conn: _Connection) -> None:
        """Handle a dropped socket: remove from its room and session table."""
        session = conn.session
        with self._sessions_lock:
            self._sessions.pop(session.player_id, None)
        if session.room_code:
            room = self.rooms.get_room(session.room_code)
            if room is not None:
                room.remove_player(session.player_id, notify=True)
        safe_close(session.sock)

    # -----------------------------------------------------------------------
    # Routing
    # -----------------------------------------------------------------------

    def _route(self, conn: _Connection, msg: dict) -> None:
        """Route one message from a connection to the right handler."""
        t = msg.get("type", "")
        session = conn.session

        if t == C.MSG_JOIN_REQUEST:
            self._on_join_request(conn, msg)
        elif t == C.MSG_CREATE_ROOM:
            self._on_create_room(conn, msg)
        elif t == C.MSG_JOIN_ROOM:
            self._on_join_room(conn, msg)
        elif t == C.MSG_RECONNECT:
            self._on_reconnect(conn, msg)
        elif t == C.MSG_PONG:
            self._on_pong(session, msg)
        elif t == C.MSG_DISCONNECT:
            # Client asked to leave; the loop will end after this.
            self._cleanup_connection(conn)
        else:
            # In-room message — forward to the player's room.
            if session.room_code:
                room = self.rooms.get_room(session.room_code)
                if room is not None:
                    room.handle_message(session.player_id, msg)

    # -- join (default room / backward compatible) --------------------------

    def _on_join_request(self, conn: _Connection, msg: dict) -> None:
        session = conn.session
        code = msg.get("access_code", "")
        name = str(msg.get("player_name", "")).strip()

        if code != self.config.access_code:
            send_message(session.sock, make_message(
                C.MSG_JOIN_RESPONSE, success=False,
                message="Invalid access code."))
            log.info("Rejected %s: bad access code", session.address)
            return

        room = self.rooms.get_default_room()
        err = self._validate_admission(room, name)
        if err is not None:
            send_message(session.sock, make_message(
                C.MSG_JOIN_RESPONSE, success=False, message=err))
            return

        session.name = name
        room.add_player(session)
        session.room_code = room.code
        send_message(session.sock, make_message(
            C.MSG_JOIN_RESPONSE, success=True, message=f"Welcome, {name}!",
            player_id=session.player_id, session_token=session.session_token,
            room_code=room.code, settings=room.settings.to_dict()))
        log.info("Player '%s' joined default room %s", name, room.code)

    # -- create room --------------------------------------------------------

    def _on_create_room(self, conn: _Connection, msg: dict) -> None:
        session = conn.session
        name = str(msg.get("player_name", "")).strip()
        settings = RoomSettings.from_dict(msg.get("settings", {}))

        if not name or len(name) > 20:
            send_message(session.sock, make_message(
                C.MSG_ROOM_ERROR, code=C.ERR_INVALID_NAME,
                message="Invalid name (1–20 characters)."))
            return

        room = self.rooms.create_room(settings)
        session.name = name
        room.add_player(session)
        session.room_code = room.code
        send_message(session.sock, make_message(
            C.MSG_ROOM_CREATED, success=True, room_code=room.code,
            player_id=session.player_id, session_token=session.session_token,
            settings=room.settings.to_dict()))
        log.info("Player '%s' created and joined room %s", name, room.code)

    # -- join by code -------------------------------------------------------

    def _on_join_room(self, conn: _Connection, msg: dict) -> None:
        session = conn.session
        name = str(msg.get("player_name", "")).strip()
        room_code = str(msg.get("room_code", "")).strip().upper()

        room = self.rooms.get_room(room_code)
        if room is None:
            send_message(session.sock, make_message(
                C.MSG_ROOM_ERROR, code=C.ERR_ROOM_NOT_FOUND,
                message="Room not found."))
            return

        err = self._validate_admission(room, name)
        if err is not None:
            send_message(session.sock, make_message(
                C.MSG_ROOM_ERROR, code=C.ERR_NAME_TAKEN, message=err))
            return

        session.name = name
        room.add_player(session)
        session.room_code = room.code
        send_message(session.sock, make_message(
            C.MSG_JOIN_RESPONSE, success=True, message=f"Welcome, {name}!",
            player_id=session.player_id, session_token=session.session_token,
            room_code=room.code, settings=room.settings.to_dict()))
        log.info("Player '%s' joined room %s", name, room.code)

    # -- reconnect ----------------------------------------------------------

    def _on_reconnect(self, conn: _Connection, msg: dict) -> None:
        session = conn.session
        old_pid = str(msg.get("player_id", ""))
        token = str(msg.get("session_token", ""))
        room_code = str(msg.get("room_code", "")).strip()

        room = self.rooms.get_room(room_code)
        if room is None:
            send_message(session.sock, make_message(
                C.MSG_RECONNECT_RESPONSE, success=False,
                message="Room no longer exists."))
            return

        # Build a temp session carrying the OLD identity + the NEW socket.
        temp = PlayerSession(
            player_id=old_pid, name="", sock=session.sock,
            address=session.address, session_token=token)
        restored = room.reconnect_player(temp)
        if restored is None:
            send_message(session.sock, make_message(
                C.MSG_RECONNECT_RESPONSE, success=False,
                message="Could not restore your session."))
            return

        # Rebind this connection to the restored (old) session.
        with self._sessions_lock:
            self._sessions.pop(session.player_id, None)
            self._sessions[restored.player_id] = restored
        conn.session = restored
        restored.room_code = room.code

        send_message(restored.sock, make_message(
            C.MSG_RECONNECT_RESPONSE, success=True,
            player_id=restored.player_id, room_code=room.code,
            state={"game_state": room.session.state}))
        room.broadcast(make_message(
            C.MSG_PLAYER_RECONNECTED, player_id=restored.player_id,
            player_name=restored.name))
        room.broadcast_lobby()
        log.info("Player '%s' reconnected to room %s", restored.name, room.code)

    # -- pong ---------------------------------------------------------------

    def _on_pong(self, session: PlayerSession, msg: dict) -> None:
        """Update latency from a pong and echo a latency_update to the client."""
        sent = msg.get("server_time")
        now = time.monotonic()
        session.last_pong = now
        if isinstance(sent, (int, float)):
            rtt_ms = max(0.0, (now - float(sent)) * 1000.0)
            # Smooth latency a little to avoid jitter.
            session.latency_ms = (
                rtt_ms if session.latency_ms <= 0
                else 0.7 * session.latency_ms + 0.3 * rtt_ms)
            if session.sock is not None:
                send_message(session.sock, make_message(
                    C.MSG_LATENCY, latency_ms=round(session.latency_ms, 1)))

    # -----------------------------------------------------------------------
    # Heartbeat
    # -----------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """Periodically ping clients and drop silent ones."""
        while self.running:
            time.sleep(C.PING_INTERVAL_SEC)
            now = time.monotonic()
            with self._sessions_lock:
                sessions = list(self._sessions.values())
            for s in sessions:
                if s.is_bot or s.sock is None or not s.connected:
                    continue
                # Timeout: no pong within the allowed window → drop.
                if now - s.last_pong > C.HEARTBEAT_TIMEOUT_SEC:
                    log.info("Heartbeat timeout for '%s' — closing socket",
                             s.name or s.player_id)
                    safe_close(s.sock)
                    continue
                send_message(s.sock, make_message(
                    C.MSG_PING, server_time=now))

    # -----------------------------------------------------------------------
    # Admission validation
    # -----------------------------------------------------------------------

    def _validate_admission(self, room: Room, name: str) -> Optional[str]:
        """Return an error string if *name* cannot join *room*, else None."""
        if not name or len(name) > 20:
            return "Invalid name (must be 1–20 characters)."
        if room.session.state != C.STATE_LOBBY:
            return "Game already in progress in that room."
        if room.is_full():
            return "Room is full."
        if room.has_name(name):
            return "That name is already taken."
        return None


# ============================================================================
# CLI entry point
# ============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the server CLI parser (also used in tests)."""
    ap = argparse.ArgumentParser(
        description="Reaction Rush v2 — TCP Multiplayer Game Server")
    ap.add_argument("--host", default=C.DEFAULT_HOST,
                    help=f"Interface to bind (default: {C.DEFAULT_HOST})")
    ap.add_argument("--port", type=int, default=C.DEFAULT_PORT,
                    help=f"TCP port (default: {C.DEFAULT_PORT})")
    ap.add_argument("--access-code", default=C.DEFAULT_ACCESS_CODE,
                    help="Default-room access code (default: RED123)")
    ap.add_argument("--min-players", type=int, default=C.DEFAULT_MIN_PLAYERS,
                    help="Minimum players to start (default: 2)")
    ap.add_argument("--max-players", type=int, default=C.DEFAULT_MAX_PLAYERS,
                    help="Maximum players per room (default: 8)")
    ap.add_argument("--rounds", type=int, default=C.DEFAULT_ROUNDS,
                    help="Rounds per match (default: 5)")
    ap.add_argument("--mode", default=C.MODE_CLASSIC, choices=C.ALL_MODES,
                    help="Default game mode (default: classic)")
    ap.add_argument("--db", default=C.DEFAULT_DB_PATH,
                    help="SQLite database path (default: reaction_rush.db)")
    ap.add_argument("--log-level", default="INFO",
                    help="Logging level: DEBUG/INFO/WARNING/ERROR")
    ap.add_argument("--log-file", default="",
                    help="Optional log file path")
    ap.add_argument("--disable-persistence", action="store_true",
                    help="Do not use the SQLite database")
    ap.add_argument("--disable-latency-compensation", action="store_true",
                    help="Disable latency compensation for scoring")
    return ap


def main(argv=None) -> None:
    """Parse CLI args, build the server, and run it."""
    args = build_arg_parser().parse_args(argv)

    setup_logging(args.log_level, args.log_file or None)

    config = ServerConfig(
        host=args.host,
        port=args.port,
        access_code=args.access_code,
        min_players=args.min_players,
        max_players=args.max_players,
        rounds=args.rounds,
        mode=args.mode,
        db_path=args.db,
        persistence_enabled=not args.disable_persistence,
        latency_compensation=not args.disable_latency_compensation,
        log_level=args.log_level,
        log_file=args.log_file,
    )

    db = None
    if config.persistence_enabled:
        # Imported lazily so a missing/locked DB never blocks a --disable run.
        from .persistence import Database
        try:
            db = Database(config.db_path)
        except Exception:
            log.exception("Could not open database; continuing without it")
            db = None

    app = ServerApp(config, db=db)
    try:
        app.start()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
