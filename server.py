"""
server.py

Main TCP server for Reaction Rush.

This file handles:
- accepting client connections
- validating lobby joins
- starting the game when everyone is ready
- running each round
- calculating and sending round/final results
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


class Player:
    """Stores the server-side state for one player"""

    def __init__(self, pid: int, sock: socket.socket, addr: tuple) -> None:
        self.id: int = pid
        self.socket: socket.socket = sock
        self.address: tuple = addr
        self.name: str = ""           # set after a successful join
        self.joined: bool = False
        self.ready: bool = False
        self.connected: bool = True

class GameServer:
    """Handles connections, lobby state, and the game rounds"""

    def __init__(
        self, host: str, port: int, access_code: str, min_players: int,
    ) -> None:
        self.host = host
        self.port = port
        self.access_code = access_code
        self.min_players = max(2, min_players)

        # Main server socket
        self.server_socket: Optional[socket.socket] = None
        self.running: bool = False
        self.game_started: bool = False

        # Shared player state
        self.players: Dict[int, Player] = {}
        self._next_id: int = 0
        self.lock = threading.Lock()

        # Shared round state
        self.round_number: int = 0
        self.round_phase: str = "lobby"   # lobby, prepare, go, scoring, done
        self.round_go_time: float = 0.0
        self.round_clicks: Dict[int, float] = {}
        self.round_false_starts: Set[int] = set()
        self.round_responses: Set[int] = set()

        # Round history for each player
        self.all_round_results: Dict[int, list] = {}
        self.all_responded = threading.Event()

    # Server setup / shutdown
    def start(self) -> None:
        """Start listening for clients and enter the accept loop"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Lets us restart the server without waiting for the port to clear
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
        """Shut down the server and close any open sockets"""
        self._log("Shutting down …")
        self.running = False
        self.round_phase = "done"
        self.all_responded.set()

        self._broadcast(make_message(MSG_DISCONNECT, message="Server shutting down."))

        with self.lock:
            for p in self.players.values():
                safe_close(p.socket)

        safe_close(self.server_socket)
        self._log("Server stopped.")

    # Connection handling
    def _accept_loop(self) -> None:
        """Accept new client connections while the server is running"""
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with self.lock:
                pid = self._next_id
                self._next_id += 1
                self.players[pid] = Player(pid, client_sock, addr)

            self._log(f"New connection from {addr}")

            threading.Thread(
                target=self._client_handler,
                args=(pid,),
                daemon=True,
            ).start()

    def _client_handler(self, pid: int) -> None:
        """Handle incoming messages for one client until it disconnects"""
        player = self.players[pid]
        buf = ""
        player.socket.settimeout(1.0)

        while self.running and player.connected:
            msgs, buf = receive_messages(player.socket, buf)

            if msgs is None:
                break

            for m in msgs:
                try:
                    self._handle_msg(pid, m)
                except Exception:
                    traceback.print_exc()

        self._handle_disconnect(pid)

    # Incoming message routing
    def _handle_msg(self, pid: int, msg: dict) -> None:
        """Send each incoming message to the matching handler"""
        t = msg.get("type", "")
        if t == MSG_JOIN_REQUEST:
            self._on_join(pid, msg)
        elif t == MSG_READY:
            self._on_ready(pid)
        elif t == MSG_CLICK:
            self._on_click(pid, msg)
        elif t == MSG_DISCONNECT:
            self._handle_disconnect(pid)

    # Join / ready / click handlers
    def _on_join(self, pid: int, msg: dict) -> None:
        """Validate join data, then add the player to the lobby if valid"""
        code = msg.get("access_code", "")
        name = msg.get("player_name", "").strip()

        with self.lock:
            p = self.players.get(pid)
            if p is None:
                return

            if self.game_started:
                send_message(p.socket, make_message(
                    MSG_JOIN_RESPONSE, success=False,
                    message="Game already in progress."))
                return

            if code != self.access_code:
                send_message(p.socket, make_message(
                    MSG_JOIN_RESPONSE, success=False,
                    message="Invalid access code."))
                self._log(f"Rejected {p.address}: bad access code")
                return

            if not name or len(name) > 20:
                send_message(p.socket, make_message(
                    MSG_JOIN_RESPONSE, success=False,
                    message="Invalid name (must be 1–20 characters)."))
                return

            for other in self.players.values():
                if (other.joined and other.connected
                        and other.id != pid
                        and other.name.lower() == name.lower()):
                    send_message(p.socket, make_message(
                        MSG_JOIN_RESPONSE, success=False,
                        message="That name is already taken."))
                    return

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
        """Mark one player as ready, then see if the game can start"""
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
        """Handle one player's click for the current round"""
        arrival = time.monotonic()
        early = msg.get("early", False)

        with self.lock:
            p = self.players.get(pid)
            if p is None or not p.joined:
                return

            # Ignore extra clicks from the same player in the same round
            if pid in self.round_responses:
                return

            if self.round_phase == "prepare" or early:
                # Either the click came during red, or the client already
                # flagged it as an early click because of timing
                self.round_false_starts.add(pid)
                self.round_responses.add(pid)
                send_message(p.socket, make_message(
                    MSG_PENALTY, round_number=self.round_number,
                    message="Too soon! False start."))
                self._log(
                    f"Player '{p.name}' false-started (round {self.round_number})")

            elif self.round_phase == "go":
                # Valid click after GO, measured on the server side
                reaction_ms = (arrival - self.round_go_time) * 1000
                self.round_clicks[pid] = reaction_ms
                self.round_responses.add(pid)
                self._log(
                    f"Player '{p.name}' reacted in {reaction_ms:.0f} ms "
                    f"(round {self.round_number})")

            else:
                # Ignore clicks outside an active round
                return

            # Once everyone responded, the round thread can continue
            if self._all_active_responded():
                self.all_responded.set()

    # -- disconnect ---------------------------------------------------------

    def _handle_disconnect(self, pid: int) -> None:
        """Clean up state after a player disconnects"""
        end_game = False

        with self.lock:
            p = self.players.get(pid)
            if p is None or not p.connected:
                return

            p.connected = False
            safe_close(p.socket)
            name = p.name or f"#{pid}"
            self._log(f"Player '{name}' disconnected")

            # If a player leaves mid-round, count them as done so the
            # round thread does not wait forever
            if self.round_phase in ("prepare", "go"):
                self.round_responses.add(pid)
                if self._all_active_responded():
                    self.all_responded.set()

        self._broadcast(make_message(
            MSG_PLAYER_LEFT, player_name=name,
            message=f"{name} has disconnected."))
        self._send_lobby_update()

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

        if not self.game_started:
            self._check_start()

    # Lobby helpers
    def _send_lobby_update(self) -> None:
        """Broadcast the current lobby list and ready states"""
        with self.lock:
            plist = [
                {"name": p.name, "ready": p.ready}
                for p in self.players.values()
                if p.joined and p.connected
            ]
        self._broadcast(make_message(MSG_LOBBY_UPDATE, players=plist))

    def _check_start(self) -> None:
        """Start the game once enough players joined and all are ready"""
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

        threading.Thread(target=self._run_game, daemon=True).start()

    # Game flow
    def _run_game(self) -> None:
        """Run the full game flow from start screen to final result"""
        # Small delay so clients can switch from lobby UI into game UI
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

        # Give clients a moment to show the game-start splash
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
            # Leave a short gap so players can read the round results
            time.sleep(3.0)

        self._send_game_over()

    def _run_round(self, rnd: int) -> None:
        """Run one full round, then calculate and send the results"""
        delay = generate_round_delay()

        # Reset all per-round state before this round starts
        with self.lock:
            self.round_number = rnd
            self.round_phase = "prepare"
            self.round_clicks.clear()
            self.round_false_starts.clear()
            self.round_responses.clear()
            self.all_responded.clear()

        self._log(f"--- Round {rnd}/{TOTAL_ROUNDS}  (delay {delay:.2f} s) ---")

        # First tell clients to show the red waiting screen
        self._broadcast(make_message(
            MSG_ROUND_PREPARE, round_number=rnd, total_rounds=TOTAL_ROUNDS))

        # If everyone already reacted early, there is no reason to wait
        # for the full delay before scoring the round
        all_reacted_early = self.all_responded.wait(timeout=delay)

        if not all_reacted_early:
            with self.lock:
                if self.round_phase == "done":
                    return
                # Start the actual reaction window
                self.round_phase = "go"
                self.round_go_time = time.monotonic()

            self._broadcast(make_message(MSG_ROUND_GO, round_number=rnd))
            self._log(f"GO!  (round {rnd})")

            # Wait until everyone clicks, or stop after the timeout
            self.all_responded.wait(timeout=CLICK_TIMEOUT_MS / 1000)

        with self.lock:
            if self.round_phase == "done":
                return
            self.round_phase = "scoring"

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
                    reactions[name] = None
                    to.add(name)

            results = calculate_round_scores(reactions, fs, to)

            for r in results:
                for pid, p in self.players.items():
                    if p.name == r.player_name and pid in self.all_round_results:
                        self.all_round_results[pid].append(r)

            name_map: Dict[str, list] = {}
            for pid, p in self.players.items():
                if p.joined and pid in self.all_round_results:
                    name_map[p.name] = self.all_round_results[pid]
            lb = calculate_leaderboard(name_map)

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

        self._broadcast(make_message(
            MSG_ROUND_RESULT, round_number=rnd, total_rounds=TOTAL_ROUNDS,
            results=res_data, leaderboard=lb_data))

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

    def _send_game_over(self) -> None:
        """Send the final leaderboard and winner to all clients"""
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

    # Internal helpers
    def _broadcast(
        self, message: dict, exclude: Optional[int] = None,
    ) -> None:
        """Send one message to all active players"""
        with self.lock:
            targets = [
                p for p in self.players.values()
                if p.joined and p.connected and p.id != exclude
            ]
        for p in targets:
            send_message(p.socket, message)

    def _all_active_responded(self) -> bool:
        """Check whether every active player responded in this round"""
        active = {
            pid for pid, p in self.players.items()
            if p.joined and p.connected
        }
        return active <= self.round_responses

    @staticmethod
    def _log(text: str) -> None:
        """Print one server log line with a timestamp"""
        print(f"[{timestamp()}] {text}")

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
