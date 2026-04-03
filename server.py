"""TCP server for the Reaction Rush game.

Run with:
    python server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2

The server accepts player connections, manages the lobby, runs the rounds,
and sends results back to every client.
"""

import argparse
import socket
import threading
import time
import traceback
from typing import Dict, Optional, Set

from protocol import (
    MSG_JOIN_REQUEST, MSG_JOIN_RESPONSE, MSG_LOBBY_UPDATE,
    MSG_READY, MSG_GAME_START, MSG_ROUND_PREPARE, MSG_ROUND_GO,
    MSG_CLICK, MSG_PENALTY, MSG_ROUND_RESULT, MSG_GAME_OVER,
    MSG_ERROR, MSG_DISCONNECT, MSG_PLAYER_LEFT,
    make_message, send_message, receive_messages,
)
from game_logic import (
    TOTAL_ROUNDS, CLICK_TIMEOUT_MS,
    generate_round_delay, calculate_round_scores,
    calculate_leaderboard, determine_winner,
)
from utils import safe_close, timestamp


# ============================================================================
# Player record
# ============================================================================

class Player:
    """Server-side representation of a single connected client."""

    def __init__(self, pid: int, sock: socket.socket, addr: tuple) -> None:
        self.id: int = pid
        self.socket: socket.socket = sock
        self.address: tuple = addr
        self.name: str = ""           # set after a valid join_request
        self.joined: bool = False     # True once access code accepted
        self.ready: bool = False      # True once the player clicks Ready
        self.connected: bool = True   # False after disconnect


# ============================================================================
# Game server
# ============================================================================

class GameServer:
    """
    Manages TCP connections, the lobby, and the 5-round reaction game.

    Thread safety
    -------------
    ``self.lock`` protects *all* mutable shared state: player dicts,
    round-phase flags, click data, and result accumulators.  Every
    public helper acquires the lock for the minimum necessary window,
    releases it before any blocking I/O (``send_message``,
    ``time.sleep``, ``Event.wait``).
    """

    def __init__(
        self, host: str, port: int, access_code: str, min_players: int,
    ) -> None:
        self.host = host
        self.port = port
        self.access_code = access_code
        self.min_players = max(2, min_players)

        # Server socket
        self.server_socket: Optional[socket.socket] = None
        self.running: bool = False       # controls accept + recv loops
        self.game_started: bool = False  # True once game thread launches

        # -- Player management (protected by self.lock) ---------------------
        self.players: Dict[int, Player] = {}
        self._next_id: int = 0
        self.lock = threading.Lock()

        # -- Per-round state (protected by self.lock) -----------------------
        self.round_number: int = 0
        self.round_phase: str = "lobby"   # lobby|prepare|go|scoring|done
        self.round_go_time: float = 0.0   # monotonic timestamp of GO
        self.round_clicks: Dict[int, float] = {}   # pid → reaction ms
        self.round_false_starts: Set[int] = set()   # pids that clicked early
        self.round_responses: Set[int] = set()       # pids that responded

        # Cumulative results: pid → [PlayerRoundResult, …]
        self.all_round_results: Dict[int, list] = {}

        # Signalled when every active player has responded in a round
        self.all_responded = threading.Event()

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Bind, listen, and enter the accept loop (blocks)."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR lets us restart quickly after a crash
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 1-second timeout so the accept loop can check self.running
        self.server_socket.settimeout(1.0)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True

        self._log(f"Reaction Rush server listening on {self.host}:{self.port}")
        self._log(f"Access code  : {self.access_code}")
        self._log(f"Min players  : {self.min_players}")
        self._log("Waiting for players to connect …")

        self._accept_loop()

    def shutdown(self) -> None:
        """Gracefully shut down: notify clients, close all sockets."""
        self._log("Shutting down …")
        self.running = False
        self.round_phase = "done"
        self.all_responded.set()  # unblock game thread if waiting

        # Best-effort goodbye to every client
        self._broadcast(make_message(MSG_DISCONNECT, message="Server shutting down."))

        with self.lock:
            for p in self.players.values():
                safe_close(p.socket)

        safe_close(self.server_socket)
        self._log("Server stopped.")

    # -----------------------------------------------------------------------
    # Connection handling
    # -----------------------------------------------------------------------

    def _accept_loop(self) -> None:
        """Block in a loop, accepting new TCP connections."""
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
            except socket.timeout:
                continue       # check self.running, then try again
            except OSError:
                break          # socket closed during shutdown

            # Register the new player
            with self.lock:
                pid = self._next_id
                self._next_id += 1
                self.players[pid] = Player(pid, client_sock, addr)

            self._log(f"New connection from {addr}")

            # Spawn a dedicated receiver thread for this client
            threading.Thread(
                target=self._client_handler,
                args=(pid,),
                daemon=True,
            ).start()

    def _client_handler(self, pid: int) -> None:
        """
        Receive loop for a single client.

        Runs on its own thread.  Reads newline-delimited JSON messages,
        dispatching each to ``_handle_msg``.  Exits when the connection
        drops or the server is shutting down.
        """
        player = self.players[pid]
        buf = ""
        player.socket.settimeout(1.0)  # allow periodic self.running check

        while self.running and player.connected:
            msgs, buf = receive_messages(player.socket, buf)

            if msgs is None:
                # Connection lost
                break

            for m in msgs:
                try:
                    self._handle_msg(pid, m)
                except Exception:
                    traceback.print_exc()

        self._handle_disconnect(pid)

    # -----------------------------------------------------------------------
    # Message dispatch
    # -----------------------------------------------------------------------

    def _handle_msg(self, pid: int, msg: dict) -> None:
        """Route an incoming message to the correct handler."""
        t = msg.get("type", "")
        if t == MSG_JOIN_REQUEST:
            self._on_join(pid, msg)
        elif t == MSG_READY:
            self._on_ready(pid)
        elif t == MSG_CLICK:
            self._on_click(pid, msg)
        elif t == MSG_DISCONNECT:
            self._handle_disconnect(pid)

    # -- join ---------------------------------------------------------------

    def _on_join(self, pid: int, msg: dict) -> None:
        """Validate access code and player name, then admit or reject."""
        code = msg.get("access_code", "")
        name = msg.get("player_name", "").strip()

        with self.lock:
            p = self.players.get(pid)
            if p is None:
                return

            # Reject if a game is already running
            if self.game_started:
                send_message(p.socket, make_message(
                    MSG_JOIN_RESPONSE, success=False,
                    message="Game already in progress."))
                return

            # Validate the lobby access code
            if code != self.access_code:
                send_message(p.socket, make_message(
                    MSG_JOIN_RESPONSE, success=False,
                    message="Invalid access code."))
                self._log(f"Rejected {p.address}: bad access code")
                return

            # Validate player name length
            if not name or len(name) > 20:
                send_message(p.socket, make_message(
                    MSG_JOIN_RESPONSE, success=False,
                    message="Invalid name (must be 1–20 characters)."))
                return

            # Reject duplicate names (case-insensitive)
            for other in self.players.values():
                if (other.joined and other.connected
                        and other.id != pid
                        and other.name.lower() == name.lower()):
                    send_message(p.socket, make_message(
                        MSG_JOIN_RESPONSE, success=False,
                        message="That name is already taken."))
                    return

            # All checks passed — admit the player
            p.name = name
            p.joined = True

            send_message(p.socket, make_message(
                MSG_JOIN_RESPONSE, success=True,
                message=f"Welcome, {name}!", player_id=pid))
            self._log(f"Player '{name}' joined from {p.address}")

        # Let everyone see the updated lobby
        self._send_lobby_update()

    # -- ready --------------------------------------------------------------

    def _on_ready(self, pid: int) -> None:
        """Mark a player as ready and check if the game should start."""
        with self.lock:
            p = self.players.get(pid)
            if p is None or not p.joined:
                return
            p.ready = True
            self._log(f"Player '{p.name}' is ready")

        self._send_lobby_update()
        self._check_start()

    # -- click --------------------------------------------------------------

    def _on_click(self, pid: int, msg: dict) -> None:
        """
        Record a player's click event during a round.

        False-start detection is **dual-source**:
        * If the server is still in the "prepare" phase (red screen), any
          incoming click is a false start.
        * If the *client* reports ``early=True`` (player clicked before
          receiving round_go due to network latency), it is also treated
          as a false start.

        The reaction time for valid clicks is measured entirely with
        server-side ``time.monotonic()`` — the difference between the
        moment GO was sent and the moment the click message arrived.
        """
        arrival = time.monotonic()
        early = msg.get("early", False)

        with self.lock:
            p = self.players.get(pid)
            if p is None or not p.joined:
                return

            # Ignore duplicate clicks within the same round
            if pid in self.round_responses:
                return

            if self.round_phase == "prepare" or early:
                # --- False start ---
                self.round_false_starts.add(pid)
                self.round_responses.add(pid)
                send_message(p.socket, make_message(
                    MSG_PENALTY, round_number=self.round_number,
                    message="Too soon! False start."))
                self._log(
                    f"Player '{p.name}' false-started (round {self.round_number})")

            elif self.round_phase == "go":
                # --- Valid click ---
                reaction_ms = (arrival - self.round_go_time) * 1000
                self.round_clicks[pid] = reaction_ms
                self.round_responses.add(pid)
                self._log(
                    f"Player '{p.name}' reacted in {reaction_ms:.0f} ms "
                    f"(round {self.round_number})")

            else:
                # Click outside an active round phase — ignore
                return

            # Check whether every active player has now responded
            if self._all_active_responded():
                self.all_responded.set()

    # -- disconnect ---------------------------------------------------------

    def _handle_disconnect(self, pid: int) -> None:
        """
        Clean up after a client disconnects (voluntary or crash).

        If a round is in progress the player is automatically marked as
        having responded so the game thread is not left waiting forever.
        If fewer than 2 players remain mid-game, the match ends.
        """
        end_game = False

        with self.lock:
            p = self.players.get(pid)
            if p is None or not p.connected:
                return

            p.connected = False
            safe_close(p.socket)
            name = p.name or f"#{pid}"
            self._log(f"Player '{name}' disconnected")

            # Unblock the game thread if it is waiting for this player
            if self.round_phase in ("prepare", "go"):
                self.round_responses.add(pid)
                if self._all_active_responded():
                    self.all_responded.set()

        # Notify remaining clients
        self._broadcast(make_message(
            MSG_PLAYER_LEFT, player_name=name,
            message=f"{name} has disconnected."))
        self._send_lobby_update()

        # End the game if too few players remain
        with self.lock:
            active = sum(
                1 for p in self.players.values()
                if p.joined and p.connected
            )
            if self.game_started and active < 2:
                self.round_phase = "done"
                self.all_responded.set()
                end_game = True

        if end_game:
            self._broadcast(make_message(
                MSG_ERROR,
                message="Not enough players remaining. Game ending."))

        # A non-ready player leaving may satisfy the start condition
        if not self.game_started:
            self._check_start()

    # -----------------------------------------------------------------------
    # Lobby helpers
    # -----------------------------------------------------------------------

    def _send_lobby_update(self) -> None:
        """Broadcast the current player list and ready flags."""
        with self.lock:
            plist = [
                {"name": p.name, "ready": p.ready}
                for p in self.players.values()
                if p.joined and p.connected
            ]
        self._broadcast(make_message(MSG_LOBBY_UPDATE, players=plist))

    def _check_start(self) -> None:
        """Start the game when all connected players are ready (≥ min)."""
        with self.lock:
            if self.game_started:
                return
            joined = [
                p for p in self.players.values()
                if p.joined and p.connected
            ]
            if len(joined) < self.min_players:
                return
            if not all(p.ready for p in joined):
                return
            self.game_started = True
            self._log(f"All {len(joined)} player(s) ready — starting game!")

        # Launch the game controller on a dedicated thread
        threading.Thread(target=self._run_game, daemon=True).start()

    # -----------------------------------------------------------------------
    # Game loop
    # -----------------------------------------------------------------------

    def _run_game(self) -> None:
        """
        Top-level game controller.

        Sends a ``game_start`` announcement, runs 5 rounds, then sends
        ``game_over`` with the final leaderboard and winner.
        """
        # Brief pause so clients can prepare the UI
        time.sleep(1.0)

        with self.lock:
            names = [
                p.name for p in self.players.values()
                if p.joined and p.connected
            ]
            for pid, p in self.players.items():
                if p.joined and p.connected:
                    self.all_round_results[pid] = []

        self._broadcast(make_message(
            MSG_GAME_START, total_rounds=TOTAL_ROUNDS, players=names))

        # Give clients a moment to show the "Game starting" splash
        time.sleep(1.5)

        for rnd in range(1, TOTAL_ROUNDS + 1):
            with self.lock:
                if self.round_phase == "done":
                    break
                active = sum(
                    1 for p in self.players.values()
                    if p.joined and p.connected
                )
                if active < 2:
                    break

            self._run_round(rnd)
            # Pause between rounds so players can read the scoreboard
            time.sleep(3.0)

        self._send_game_over()

    # -----------------------------------------------------------------------
    # Single-round execution
    # -----------------------------------------------------------------------

    def _run_round(self, rnd: int) -> None:
        """
        Execute one complete round:
        1. Broadcast ``round_prepare`` (clients show the red screen).
        2. Sleep for a random server-determined delay.
        3. Broadcast ``round_go`` (clients switch to green).
        4. Wait for all clicks or a 3-second timeout.
        5. Score the round and broadcast results + leaderboard.
        """
        delay = generate_round_delay()

        # Reset round state
        with self.lock:
            self.round_number = rnd
            self.round_phase = "prepare"
            self.round_clicks.clear()
            self.round_false_starts.clear()
            self.round_responses.clear()
            self.all_responded.clear()

        self._log(f"--- Round {rnd}/{TOTAL_ROUNDS}  (delay {delay:.2f} s) ---")

        # Phase 1 — RED screen
        self._broadcast(make_message(
            MSG_ROUND_PREPARE, round_number=rnd, total_rounds=TOTAL_ROUNDS))

        # Server-controlled delay; clicks arriving here → false starts.
        # If everyone already responded during the red phase, skip GO and
        # score immediately instead of waiting out the whole delay.
        all_reacted_early = self.all_responded.wait(timeout=delay)

        if not all_reacted_early:
            with self.lock:
                if self.round_phase == "done":
                    return
                # Phase 2 — GREEN screen
                self.round_phase = "go"
                self.round_go_time = time.monotonic()

            self._broadcast(make_message(MSG_ROUND_GO, round_number=rnd))
            self._log(f"GO!  (round {rnd})")

            # Wait for every player to click, or 3 s timeout
            self.all_responded.wait(timeout=CLICK_TIMEOUT_MS / 1000)

        # Phase 3 — Scoring
        with self.lock:
            if self.round_phase == "done":
                return
            self.round_phase = "scoring"

            # Identify active players
            active_ids = {
                pid for pid, p in self.players.items()
                if p.joined and p.connected
            }

            reactions: Dict[str, Optional[float]] = {}
            fs: Set[str] = set()
            to: Set[str] = set()

            for pid in active_ids:
                name = self.players[pid].name
                if pid in self.round_false_starts:
                    reactions[name] = None
                    fs.add(name)
                elif pid in self.round_clicks:
                    reactions[name] = self.round_clicks[pid]
                else:
                    # No response within timeout
                    reactions[name] = None
                    to.add(name)

            # Compute per-round scores
            results = calculate_round_scores(reactions, fs, to)

            # Accumulate into all_round_results for the leaderboard
            for r in results:
                for pid, p in self.players.items():
                    if p.name == r.player_name and pid in self.all_round_results:
                        self.all_round_results[pid].append(r)

            # Build leaderboard from all rounds so far
            name_map: Dict[str, list] = {}
            for pid, p in self.players.items():
                if p.joined and pid in self.all_round_results:
                    name_map[p.name] = self.all_round_results[pid]
            lb = calculate_leaderboard(name_map)

            # Serialise for the wire
            res_data = [
                {
                    "player_name": r.player_name,
                    "reaction_time_ms": r.reaction_time_ms,
                    "score": r.score,
                    "false_start": r.false_start,
                    "timed_out": r.timed_out,
                }
                for r in results
            ]
            lb_data = [
                {
                    "player_name": s.player_name,
                    "total_score": s.total_score,
                    "total_reaction_time_ms": s.total_reaction_time_ms,
                }
                for s in lb
            ]

        # Broadcast round results
        self._broadcast(make_message(
            MSG_ROUND_RESULT, round_number=rnd, total_rounds=TOTAL_ROUNDS,
            results=res_data, leaderboard=lb_data))

        # Server-side log
        self._log(f"Round {rnd} results:")
        for r in res_data:
            if r["false_start"]:
                self._log(f"  {r['player_name']:>15s} : FALSE START       0 pts")
            elif r["timed_out"]:
                self._log(f"  {r['player_name']:>15s} : TIMED OUT         0 pts")
            else:
                self._log(
                    f"  {r['player_name']:>15s} : "
                    f"{r['reaction_time_ms']:>6.0f} ms  {r['score']:>3d} pts"
                )

    # -----------------------------------------------------------------------
    # Game over
    # -----------------------------------------------------------------------

    def _send_game_over(self) -> None:
        """Compute and broadcast the final leaderboard and winner."""
        with self.lock:
            name_map: Dict[str, list] = {}
            for pid, p in self.players.items():
                if p.joined and pid in self.all_round_results:
                    name_map[p.name] = self.all_round_results[pid]

            lb = calculate_leaderboard(name_map)
            winner = determine_winner(lb)

            lb_data = [
                {
                    "rank": i,
                    "player_name": s.player_name,
                    "total_score": s.total_score,
                    "total_reaction_time_ms": s.total_reaction_time_ms,
                }
                for i, s in enumerate(lb, 1)
            ]

        self._broadcast(make_message(
            MSG_GAME_OVER, winner=winner or "Nobody",
            final_leaderboard=lb_data))

        self._log("=" * 44)
        self._log(f"GAME OVER  —  Winner: {winner}")
        for e in lb_data:
            self._log(
                f"  #{e['rank']} {e['player_name']}: "
                f"{e['total_score']} pts  ({e['total_reaction_time_ms']:.0f} ms)")
        self._log("=" * 44)

    # -----------------------------------------------------------------------
    # Broadcast / internal helpers
    # -----------------------------------------------------------------------

    def _broadcast(
        self, message: dict, exclude: Optional[int] = None,
    ) -> None:
        """Send *message* to every joined, connected player."""
        with self.lock:
            targets = [
                p for p in self.players.values()
                if p.joined and p.connected and p.id != exclude
            ]
        for p in targets:
            send_message(p.socket, message)

    def _all_active_responded(self) -> bool:
        """True when every active player has an entry in round_responses."""
        active = {
            pid for pid, p in self.players.items()
            if p.joined and p.connected
        }
        return active <= self.round_responses

    @staticmethod
    def _log(text: str) -> None:
        """Print a timestamped server log line to stdout."""
        print(f"[{timestamp()}] {text}")


# ============================================================================
# Entry point
# ============================================================================

def main() -> None:
    """Parse CLI arguments and run the server."""
    ap = argparse.ArgumentParser(
        description="Reaction Rush — TCP Multiplayer Game Server",
    )
    ap.add_argument("--host", default="127.0.0.1",
                    help="Interface to bind to (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=5000,
                    help="TCP port (default: 5000)")
    ap.add_argument("--access-code", default="RED123",
                    help="Lobby access code (default: RED123)")
    ap.add_argument("--min-players", type=int, default=2,
                    help="Minimum players to start (default: 2)")
    args = ap.parse_args()

    server = GameServer(
        args.host, args.port, args.access_code, args.min_players,
    )

    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
