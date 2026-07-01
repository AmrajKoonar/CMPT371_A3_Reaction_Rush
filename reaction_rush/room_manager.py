"""
room_manager.py — Rooms and the manager that routes players to them.

This module contains two classes:

* :class:`Room` — one game room. Owns its players (humans and bots), its
  settings, its :class:`~reaction_rush.game_session.GameSession`, and the
  background thread that runs a match. All shared room state is guarded by a
  single ``threading.Lock``; blocking I/O (socket sends, sleeps, event waits)
  always happens **outside** the locked region.

* :class:`RoomManager` — creates/looks up rooms, handles the join/create/
  reconnect entry points, keeps a backward-compatible **default room** bound
  to the server access code, and cleans up empty rooms.

The design keeps all concurrency reasoning inside these two classes so the
rest of the codebase stays simple.
"""

from __future__ import annotations

import random
import string
import threading
import time
from typing import Callable, Dict, List, Optional, Set

from . import constants as C
from . import game_logic as GL
from .bots import bot_false_start_delay, decide_bot_round, make_bot
from .config import RoomSettings, ServerConfig
from .game_session import GameSession
from .logging_config import get_logger
from .models import PlayerRoundResult, PlayerSession
from .protocol import make_message, send_message
from .stats import summarize_player

log = get_logger("room")


# ============================================================================
# Room
# ============================================================================

class Room:
    """A single game room with its own players, settings, and game loop."""

    def __init__(
        self,
        code: str,
        settings: RoomSettings,
        db=None,
        on_empty: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.code = code
        self.settings = settings.sanitized()
        self.db = db
        self._on_empty = on_empty

        # player_id -> PlayerSession (humans + bots)
        self.players: Dict[str, PlayerSession] = {}
        self.host_id: Optional[str] = None

        self.session = GameSession(self.settings.mode, self.settings.rounds)
        self.lock = threading.Lock()

        # Signalled when every active player has responded in a round.
        self._all_responded = threading.Event()
        # Timers used to drive bot behaviour; cancelled on reset/abort.
        self._round_timers: List[threading.Timer] = []
        self._game_thread: Optional[threading.Thread] = None
        self._closing = False

    # -----------------------------------------------------------------------
    # Membership
    # -----------------------------------------------------------------------

    def add_player(self, session: PlayerSession) -> None:
        """Add a player (human or bot) to the room."""
        with self.lock:
            session.room_code = self.code
            self.players[session.player_id] = session
            # First human to join becomes the host.
            if self.host_id is None and not session.is_bot:
                self.host_id = session.player_id
                session.is_host = True
        self.broadcast_lobby()

    def has_name(self, name: str) -> bool:
        """Return True if a connected player already uses *name*."""
        with self.lock:
            return any(
                p.name.lower() == name.lower() and p.connected
                for p in self.players.values()
            )

    def player_count(self, humans_only: bool = False) -> int:
        with self.lock:
            return self._count(humans_only)

    def _count(self, humans_only: bool = False) -> int:
        """(lock held) Count connected players, optionally humans only."""
        total = 0
        for p in self.players.values():
            if humans_only and p.is_bot:
                continue
            if p.connected or p.is_bot:
                total += 1
        return total

    def is_empty(self) -> bool:
        """True when there are no connected humans left."""
        with self.lock:
            return not any(
                p.connected and not p.is_bot for p in self.players.values()
            )

    def is_full(self) -> bool:
        with self.lock:
            return self._count() >= self.settings.max_players

    # -----------------------------------------------------------------------
    # Message routing (called by the server for in-room messages)
    # -----------------------------------------------------------------------

    def handle_message(self, player_id: str, msg: dict) -> None:
        """Dispatch an in-room message from *player_id*."""
        t = msg.get("type", "")
        if t == C.MSG_READY:
            self._on_ready(player_id)
        elif t == C.MSG_CLICK:
            self.handle_click(
                player_id,
                early=bool(msg.get("early", False)),
                arrival=time.monotonic(),
            )
        elif t == C.MSG_REMATCH_READY:
            self._on_rematch(player_id, ready=True)
        elif t == C.MSG_REMATCH_CANCEL:
            self._on_rematch(player_id, ready=False)
        elif t == C.MSG_ADD_BOT:
            self._on_add_bot(player_id, msg.get("bot_level", C.BOT_AVERAGE))
        elif t == C.MSG_REMOVE_BOT:
            self._on_remove_bot(player_id, msg.get("bot_id", ""))
        elif t == C.MSG_LEAVE_ROOM:
            self.remove_player(player_id, notify=True)

    # -----------------------------------------------------------------------
    # Ready / start
    # -----------------------------------------------------------------------

    def _on_ready(self, player_id: str) -> None:
        with self.lock:
            p = self.players.get(player_id)
            if p is None:
                return
            p.ready = True
            log.info("[%s] %s is ready", self.code, p.name)
        self.broadcast_lobby()
        self._maybe_start()

    def _maybe_start(self) -> None:
        """Start the game when enough players are all ready."""
        with self.lock:
            if self.session.state != C.STATE_LOBBY:
                return
            participants = [
                p for p in self.players.values()
                if p.connected or p.is_bot
            ]
            if len(participants) < self.settings.min_players:
                return
            if not all(p.ready for p in participants):
                return
            self.session.transition(C.STATE_COUNTDOWN)
            log.info("[%s] all %d players ready — starting match",
                     self.code, len(participants))

        self._game_thread = threading.Thread(target=self._run_game, daemon=True)
        self._game_thread.start()

    # -----------------------------------------------------------------------
    # Bots
    # -----------------------------------------------------------------------

    def _on_add_bot(self, requester_id: str, level: str) -> None:
        with self.lock:
            if requester_id != self.host_id:
                self._send_to(requester_id, make_message(
                    C.MSG_ROOM_ERROR, code=C.ERR_NOT_HOST,
                    message="Only the host can add bots."))
                return
            if not self.settings.allow_bots:
                self._send_to(requester_id, make_message(
                    C.MSG_ROOM_ERROR, code="BOTS_DISABLED",
                    message="Bots are disabled in this room."))
                return
            if self.session.state != C.STATE_LOBBY:
                return
            if self._count() >= self.settings.max_players:
                self._send_to(requester_id, make_message(
                    C.MSG_ROOM_ERROR, code=C.ERR_ROOM_FULL,
                    message="Room is full."))
                return
            existing = {p.name for p in self.players.values()}
            bot = make_bot(level, existing)
            bot.room_code = self.code
            self.players[bot.player_id] = bot
            log.info("[%s] bot added: %s (%s)", self.code, bot.name, level)
        self.broadcast(make_message(C.MSG_BOT_ADDED, bot=bot.public_view()))
        self.broadcast_lobby()

    def _on_remove_bot(self, requester_id: str, bot_id: str) -> None:
        with self.lock:
            if requester_id != self.host_id:
                return
            bot = self.players.get(bot_id)
            if bot is None or not bot.is_bot:
                return
            if self.session.state != C.STATE_LOBBY:
                return
            del self.players[bot_id]
            log.info("[%s] bot removed: %s", self.code, bot.name)
        self.broadcast(make_message(C.MSG_BOT_REMOVED, bot_id=bot_id))
        self.broadcast_lobby()

    # -----------------------------------------------------------------------
    # Clicks (humans and bots share this path)
    # -----------------------------------------------------------------------

    def handle_click(
        self,
        player_id: str,
        early: bool,
        arrival: Optional[float] = None,
        reaction_override: Optional[float] = None,
    ) -> None:
        """
        Record a click for *player_id*.

        Parameters
        ----------
        early : bool
            Client-reported early click (latency race). Combined with the
            server phase to detect false starts.
        arrival : float, optional
            Monotonic arrival time (humans). Used to measure reaction.
        reaction_override : float, optional
            Pre-decided reaction time (bots), used directly instead of the
            wall clock so bot timing is exact and fair.
        """
        with self.lock:
            p = self.players.get(player_id)
            if p is None or p.eliminated:
                return
            if not p.is_bot and not p.connected:
                return
            if player_id in self.session.round_responses:
                return  # one click per round

            state = self.session.state

            if state == C.STATE_WAITING_FOR_GO or early:
                # False start: clicked during the red screen (or client raced).
                self.session.round_false_starts.add(player_id)
                self.session.round_responses.add(player_id)
                if not p.is_bot:
                    self._send_to(player_id, make_message(
                        C.MSG_PENALTY, round_number=self.session.round_number,
                        message="Too soon! False start."))
                log.info("[%s] %s false-started (round %d)",
                         self.code, p.name, self.session.round_number)

            elif state == C.STATE_ACTIVE_ROUND:
                if reaction_override is not None:
                    raw = float(reaction_override)
                elif arrival is not None:
                    raw = (arrival - self.session.go_time) * 1000.0
                else:
                    raw = (time.monotonic() - self.session.go_time) * 1000.0

                one_way = max(0.0, p.latency_ms) / 2.0
                adj = GL.adjust_reaction_for_latency(
                    raw, one_way, self.settings.latency_compensation)
                if GL.is_suspicious(raw):
                    self.session.round_suspicious.add(player_id)

                self.session.round_clicks[player_id] = raw
                self.session.round_adjusted[player_id] = adj
                self.session.round_responses.add(player_id)
                log.info("[%s] %s reacted in %.0f ms (adj %.0f) round %d",
                         self.code, p.name, raw, adj, self.session.round_number)
            else:
                return

            if self._all_active_responded():
                self._all_responded.set()

    def _all_active_responded(self) -> bool:
        """(lock held) True when every active player has responded."""
        active = self._active_ids()
        return bool(active) and active <= self.session.round_responses

    def _active_ids(self) -> Set[str]:
        """(lock held) IDs of players still in play this match."""
        return {
            pid for pid, p in self.players.items()
            if (p.connected or p.is_bot) and not p.eliminated
        }

    # -----------------------------------------------------------------------
    # Game loop
    # -----------------------------------------------------------------------

    def _run_game(self) -> None:
        """Top-level match controller (runs on its own thread)."""
        try:
            self._play_match()
        except Exception:  # pragma: no cover - defensive
            log.exception("[%s] game loop crashed", self.code)

    def _play_match(self) -> None:
        time.sleep(0.8)  # let clients switch from lobby to game UI

        with self.lock:
            mode = self.settings.mode
            self.session.reset_for_new_match(mode, self.settings.rounds)
            self.session.transition(C.STATE_COUNTDOWN)
            participants = [p for p in self.players.values()
                            if p.connected or p.is_bot]
            for p in participants:
                p.eliminated = False
                self.session.ensure_result_bucket(p.player_id)
            names = [p.name for p in participants]
            # Persistence: open a match row.
            if self.db is not None:
                try:
                    self.session.match_id = self.db.start_match(self.code, mode)
                except Exception:
                    log.exception("[%s] failed to start match record", self.code)

        self.broadcast(make_message(
            C.MSG_GAME_START, total_rounds=self.settings.rounds,
            players=names, mode=mode, room_code=self.code))
        log.info("[%s] match started (mode=%s, players=%d)",
                 self.code, mode, len(participants))
        time.sleep(1.4)

        rnd = 0
        # Elimination can run more rounds than the nominal count; cap for safety.
        hard_cap = max(self.settings.rounds, len(participants)) + 2

        while True:
            with self.lock:
                if self.session.state == C.STATE_GAME_OVER or self._closing:
                    break
                if not self._can_continue():
                    break
            rnd += 1
            self._run_round(rnd)

            with self.lock:
                mode = self.settings.mode
                remaining = len(self._non_eliminated())
                done = False
                if self.session.state == C.STATE_GAME_OVER:
                    done = True
                elif mode == C.MODE_ELIMINATION:
                    if remaining <= 1 or rnd >= hard_cap:
                        done = True
                else:
                    if rnd >= self.settings.rounds:
                        done = True
            if done:
                break
            time.sleep(3.5)  # give players time to read the scoreboard

        self._send_game_over()

    def _can_continue(self) -> bool:
        """(lock held) True if the match can keep going."""
        humans = sum(1 for p in self.players.values()
                     if p.connected and not p.is_bot)
        total = self._count()
        # Need at least one human watching and at least two participants.
        return humans >= 1 and total >= 2

    def _non_eliminated(self) -> List[PlayerSession]:
        """(lock held) Participants not yet eliminated."""
        return [p for p in self.players.values()
                if (p.connected or p.is_bot) and not p.eliminated]

    # -----------------------------------------------------------------------
    # One round
    # -----------------------------------------------------------------------

    def _run_round(self, rnd: int) -> None:
        delay = GL.generate_round_delay()
        fake_delays: List[float] = []

        with self.lock:
            if self.session.state == C.STATE_GAME_OVER:
                return
            self.session.round_number = rnd
            self.session.reset_round()
            self.session.transition(C.STATE_WAITING_FOR_GO)
            self._all_responded.clear()
            self._cancel_timers()

            mode = self.settings.mode
            if mode == C.MODE_CHAOS:
                fake_delays = GL.generate_fake_signal_delays(delay)

            # Pre-decide bot behaviour for this round.
            bot_plan: Dict[str, float] = {}   # bot_id -> reaction (valid bots)
            for p in self._non_eliminated():
                if not p.is_bot:
                    continue
                fs, reaction = decide_bot_round(p.bot_level)
                if fs:
                    when = bot_false_start_delay(delay)
                    self._schedule(when, self._bot_click_early, p.player_id)
                else:
                    bot_plan[p.player_id] = reaction

        log.info("[%s] round %d/%d (delay %.2fs, mode %s)",
                 self.code, rnd, self.settings.rounds, delay, self.settings.mode)

        self.broadcast(make_message(
            C.MSG_ROUND_PREPARE, round_number=rnd,
            total_rounds=self.settings.rounds, mode=self.settings.mode))

        # Chaos decoys: schedule fake-signal broadcasts during the red window.
        for fd in fake_delays:
            self._schedule(fd, self._broadcast_fake_signal, rnd)

        # Wait out the red delay, but finish early if everyone already reacted
        # (e.g. all false-started).
        all_early = self._all_responded.wait(timeout=delay)

        if not all_early:
            with self.lock:
                if self.session.state == C.STATE_GAME_OVER:
                    return
                self.session.transition(C.STATE_ACTIVE_ROUND)
                self.session.go_time = time.monotonic()
                # Schedule valid bot clicks now that GO has fired.
                for bot_id, reaction in bot_plan.items():
                    self._schedule(reaction / 1000.0, self._bot_click_valid,
                                   bot_id, reaction)

            self.broadcast(make_message(C.MSG_ROUND_GO, round_number=rnd))
            log.debug("[%s] GO round %d", self.code, rnd)

            self._all_responded.wait(timeout=C.CLICK_TIMEOUT_MS / 1000.0)

        self._score_round(rnd)

    def _broadcast_fake_signal(self, rnd: int) -> None:
        """Chaos mode: tell clients to briefly show a decoy (still 'wait')."""
        with self.lock:
            if (self.session.round_number != rnd
                    or self.session.state != C.STATE_WAITING_FOR_GO):
                return
        self.broadcast(make_message(C.MSG_FAKE_SIGNAL, round_number=rnd))

    def _bot_click_early(self, bot_id: str) -> None:
        self.handle_click(bot_id, early=True)

    def _bot_click_valid(self, bot_id: str, reaction: float) -> None:
        self.handle_click(bot_id, early=False, reaction_override=reaction)

    # -----------------------------------------------------------------------
    # Scoring
    # -----------------------------------------------------------------------

    def _score_round(self, rnd: int) -> None:
        with self.lock:
            if self.session.state == C.STATE_GAME_OVER:
                return
            self.session.transition(C.STATE_SCORING)
            self._cancel_timers()

            active = self._non_eliminated()
            name_to_id = {p.name: p.player_id for p in self.players.values()}

            players_data: Dict[str, dict] = {}
            for p in active:
                pid = p.player_id
                players_data[p.name] = {
                    "reaction": self.session.round_clicks.get(pid),
                    "adjusted": self.session.round_adjusted.get(pid),
                    "false_start": pid in self.session.round_false_starts,
                    "timed_out": (
                        pid not in self.session.round_clicks
                        and pid not in self.session.round_false_starts),
                    "suspicious": pid in self.session.round_suspicious,
                }

            results = GL.compute_round_results(
                players_data, self.settings.mode,
                self.settings.false_start_penalty)

            # Persist + accumulate.
            for r in results:
                pid = name_to_id.get(r.player_name)
                if pid is None:
                    continue
                self.session.all_round_results.setdefault(pid, []).append(r)
                if self.db is not None and self.session.match_id:
                    try:
                        self.db.save_round_result(
                            self.session.match_id, rnd, pid, r.player_name,
                            r.reaction_time_ms if r.reaction_time_ms >= 0 else None,
                            r.adjusted_reaction_ms if r.adjusted_reaction_ms >= 0 else None,
                            r.false_start, r.score)
                    except Exception:
                        log.exception("[%s] failed to persist round result",
                                      self.code)

            # Elimination handling (mutates player + session state).
            newly_eliminated: List[str] = []
            if self.settings.mode == C.MODE_ELIMINATION:
                active_names = {p.name for p in active}
                to_elim = GL.choose_eliminations(results, active_names)
                # Guard: never eliminate the entire remaining field.
                if len(to_elim) >= len(active) and active:
                    # Keep the fastest valid player (or first) alive.
                    keep = self._pick_survivor(results, active_names)
                    to_elim = [n for n in to_elim if n != keep]
                for name in to_elim:
                    pid = name_to_id.get(name)
                    if pid:
                        self.players[pid].eliminated = True
                        self.session.eliminated.add(pid)
                        newly_eliminated.append(name)
                for r in results:
                    if r.player_name in newly_eliminated:
                        r.eliminated = True

            leaderboard = GL.build_leaderboard(
                self._results_by_name(), self.settings.mode,
                self._eliminated_names())

            res_data = [r.to_dict() for r in results]
            lb_data = [s.to_dict() for s in leaderboard]

        self.broadcast(make_message(
            C.MSG_ROUND_RESULT, round_number=rnd,
            total_rounds=self.settings.rounds, mode=self.settings.mode,
            results=res_data, leaderboard=lb_data,
            eliminated=newly_eliminated))

    def _pick_survivor(self, results: List[PlayerRoundResult],
                       active_names: Set[str]) -> Optional[str]:
        """Choose who to keep alive when a round would eliminate everyone."""
        valid = [r for r in results
                 if r.player_name in active_names
                 and not r.false_start and not r.timed_out]
        if valid:
            return min(valid, key=lambda r: r.adjusted_reaction_ms).player_name
        return next(iter(active_names), None)

    def _results_by_name(self) -> Dict[str, List[PlayerRoundResult]]:
        """(lock held) Map player name -> accumulated results."""
        id_to_name = {pid: p.name for pid, p in self.players.items()}
        out: Dict[str, List[PlayerRoundResult]] = {}
        for pid, rounds in self.session.all_round_results.items():
            name = id_to_name.get(pid)
            if name:
                out[name] = rounds
        return out

    def _eliminated_names(self) -> Set[str]:
        """(lock held) Names of eliminated players."""
        return {p.name for p in self.players.values() if p.eliminated}

    # -----------------------------------------------------------------------
    # Game over + rematch
    # -----------------------------------------------------------------------

    def _send_game_over(self) -> None:
        with self.lock:
            self.session.force_state(C.STATE_GAME_OVER)
            self._cancel_timers()
            leaderboard = GL.build_leaderboard(
                self._results_by_name(), self.settings.mode,
                self._eliminated_names())
            winner = GL.determine_winner(leaderboard)

            lb_data = []
            for i, s in enumerate(leaderboard, 1):
                d = s.to_dict()
                d["rank"] = i
                lb_data.append(d)

            # Per-player personal stats for the game-over screen.
            personal = {}
            for name, rounds in self._results_by_name().items():
                personal[name] = summarize_player(name, rounds)

            # Reset rematch votes for the post-game screen.
            for p in self.players.values():
                p.rematch_ready = False

            # Persistence: finish the match.
            if self.db is not None and self.session.match_id:
                try:
                    name_to_id = {p.name: p.player_id
                                  for p in self.players.values()}
                    winner_id = name_to_id.get(winner)
                    participants = [
                        {"player_id": name_to_id.get(s.player_name, ""),
                         "player_name": s.player_name,
                         "total_score": s.total_score}
                        for s in leaderboard
                    ]
                    self.db.finish_match(
                        self.session.match_id, winner_id, participants)
                except Exception:
                    log.exception("[%s] failed to finish match record",
                                  self.code)

        self.broadcast(make_message(
            C.MSG_GAME_OVER, winner=winner or "Nobody",
            final_leaderboard=lb_data, personal_stats=personal,
            mode=self.settings.mode))
        log.info("[%s] game over — winner: %s", self.code, winner)

    def _on_rematch(self, player_id: str, ready: bool) -> None:
        with self.lock:
            p = self.players.get(player_id)
            if p is None:
                return
            if self.session.state not in (C.STATE_GAME_OVER, C.STATE_REMATCH):
                return
            p.rematch_ready = ready
            self.session.transition(C.STATE_REMATCH)
            log.info("[%s] %s rematch=%s", self.code, p.name, ready)

            voters = [
                {"player_id": pl.player_id, "name": pl.name,
                 "rematch_ready": pl.rematch_ready}
                for pl in self.players.values()
                if pl.connected and not pl.is_bot
            ]
            humans = [pl for pl in self.players.values()
                      if pl.connected and not pl.is_bot]
            everyone_ready = bool(humans) and all(
                pl.rematch_ready for pl in humans)
            enough = self._count() >= self.settings.min_players

        self.broadcast(make_message(C.MSG_REMATCH_UPDATE, players=voters))

        if everyone_ready and enough:
            self._start_rematch()

    def _start_rematch(self) -> None:
        """Reset the room to a fresh match and start it."""
        with self.lock:
            if self.session.state not in (C.STATE_REMATCH, C.STATE_GAME_OVER):
                return
            for p in self.players.values():
                p.eliminated = False
                p.ready = True if (p.rematch_ready or p.is_bot) else p.ready
                p.rematch_ready = False
            self.session.reset_for_new_match(
                self.settings.mode, self.settings.rounds)
            self.session.transition(C.STATE_COUNTDOWN)

        self.broadcast(make_message(
            C.MSG_NEW_MATCH, settings=self.settings.to_dict()))
        log.info("[%s] rematch starting", self.code)
        self._game_thread = threading.Thread(target=self._run_game, daemon=True)
        self._game_thread.start()

    # -----------------------------------------------------------------------
    # Disconnect / removal
    # -----------------------------------------------------------------------

    def remove_player(self, player_id: str, notify: bool = True) -> None:
        """
        Mark a player disconnected (or fully remove them in the lobby).

        During an active match the session is kept so scoring/leaderboards
        stay stable and the player can reconnect; in the lobby the player is
        removed outright.
        """
        name = ""
        became_empty = False
        with self.lock:
            p = self.players.get(player_id)
            if p is None:
                return
            name = p.name
            p.connected = False

            in_lobby = self.session.state in (
                C.STATE_LOBBY, C.STATE_GAME_OVER, C.STATE_REMATCH)
            if in_lobby:
                self.players.pop(player_id, None)
                if player_id == self.host_id:
                    self._reassign_host()
            # If mid-round, count them as responded so the round can finish.
            if self.session.is_active_state():
                self.session.round_responses.add(player_id)
                if self._all_active_responded():
                    self._all_responded.set()

            became_empty = not any(
                pl.connected and not pl.is_bot for pl in self.players.values())

        if notify:
            self.broadcast(make_message(
                C.MSG_PLAYER_LEFT, player_name=name,
                message=f"{name} has disconnected."))
            self.broadcast(make_message(
                C.MSG_PLAYER_DISCONNECTED, player_id=player_id,
                player_name=name))
        self.broadcast_lobby()

        # End the match if it can no longer continue.
        with self.lock:
            active_state = self.session.is_active_state() or \
                self.session.state in (C.STATE_COUNTDOWN, C.STATE_SCORING)
            cannot_continue = active_state and not self._can_continue()
        if cannot_continue:
            self.broadcast(make_message(
                C.MSG_ERROR, message="Not enough players remaining. "
                                     "Match ending."))
            with self.lock:
                self.session.force_state(C.STATE_GAME_OVER)
                self._all_responded.set()

        if became_empty and self._on_empty is not None:
            self._on_empty(self.code)

    def _reassign_host(self) -> None:
        """(lock held) Give host to the next connected human, if any."""
        self.host_id = None
        for pid, p in self.players.items():
            if p.connected and not p.is_bot:
                self.host_id = pid
                p.is_host = True
                break

    def reconnect_player(self, session: PlayerSession) -> Optional[PlayerSession]:
        """
        Restore a previously-disconnected session by player id + token.

        Returns the (updated) existing session on success, or None if the
        token/id do not match a known player.
        """
        with self.lock:
            existing = self.players.get(session.player_id)
            if existing is None:
                return None
            if existing.session_token != session.session_token:
                return None
            existing.sock = session.sock
            existing.address = session.address
            existing.connected = True
            existing.last_pong = time.monotonic()
            return existing

    # -----------------------------------------------------------------------
    # Broadcasting
    # -----------------------------------------------------------------------

    def broadcast(self, message: dict, exclude: Optional[str] = None) -> None:
        """Send *message* to every connected human in the room."""
        with self.lock:
            targets = [
                p for p in self.players.values()
                if p.connected and not p.is_bot and p.player_id != exclude
                and p.sock is not None
            ]
        for p in targets:
            send_message(p.sock, message)

    def broadcast_lobby(self) -> None:
        """Broadcast the current lobby snapshot to all clients."""
        with self.lock:
            players = [
                p.public_view() for p in self.players.values()
                if p.connected or p.is_bot
            ]
            # v1-compatible player list (name + ready) plus v2 richer fields.
            simple = [{"name": p["name"], "ready": p["ready"]} for p in players]
            settings = self.settings.to_dict()
            host_id = self.host_id
        self.broadcast(make_message(
            C.MSG_LOBBY_UPDATE, players=simple, players_v2=players,
            room_code=self.code, settings=settings, host_id=host_id))

    def _send_to(self, player_id: str, message: dict) -> None:
        """(lock held OK) Send a message to a single player if connected."""
        p = self.players.get(player_id)
        if p and p.connected and not p.is_bot and p.sock is not None:
            send_message(p.sock, message)

    # -----------------------------------------------------------------------
    # Timers
    # -----------------------------------------------------------------------

    def _schedule(self, delay_sec: float, fn: Callable, *args) -> None:
        """(lock held) Schedule *fn(*args)* after *delay_sec* and track it."""
        timer = threading.Timer(max(0.0, delay_sec), fn, args=args)
        timer.daemon = True
        self._round_timers.append(timer)
        timer.start()

    def _cancel_timers(self) -> None:
        """(lock held) Cancel any outstanding bot/decoy timers."""
        for t in self._round_timers:
            t.cancel()
        self._round_timers.clear()

    def close(self) -> None:
        """Force the room to stop (server shutdown)."""
        with self.lock:
            self._closing = True
            self.session.force_state(C.STATE_GAME_OVER)
            self._cancel_timers()
            self._all_responded.set()


# ============================================================================
# Room manager
# ============================================================================

_ROOM_CODE_ALPHABET = string.ascii_uppercase + string.digits


class RoomManager:
    """Creates, finds, and cleans up rooms; owns the default room."""

    def __init__(self, config: ServerConfig, db=None) -> None:
        self.config = config
        self.db = db
        self.rooms: Dict[str, Room] = {}
        self.lock = threading.Lock()

        # Backward-compatible default room bound to the server access code.
        self.default_room_code = config.access_code
        default_settings = RoomSettings(
            mode=config.mode,
            rounds=config.rounds,
            min_players=config.min_players,
            max_players=config.max_players,
            latency_compensation=config.latency_compensation,
        )
        self.rooms[self.default_room_code] = Room(
            self.default_room_code, default_settings, db=db,
            on_empty=self._on_room_empty)

    # -----------------------------------------------------------------------
    # Lookup / creation
    # -----------------------------------------------------------------------

    def get_room(self, code: str) -> Optional[Room]:
        with self.lock:
            return self.rooms.get(code)

    def get_default_room(self) -> Room:
        """Return (recreating if needed) the backward-compatible default room."""
        with self.lock:
            room = self.rooms.get(self.default_room_code)
            if room is None:
                room = self._make_default_room_locked()
            return room

    def _make_default_room_locked(self) -> Room:
        settings = RoomSettings(
            mode=self.config.mode, rounds=self.config.rounds,
            min_players=self.config.min_players,
            max_players=self.config.max_players,
            latency_compensation=self.config.latency_compensation)
        room = Room(self.default_room_code, settings, db=self.db,
                    on_empty=self._on_room_empty)
        self.rooms[self.default_room_code] = room
        return room

    def create_room(self, settings: RoomSettings) -> Room:
        """Create a new room with a unique short code."""
        with self.lock:
            code = self._unique_code_locked()
            room = Room(code, settings, db=self.db,
                        on_empty=self._on_room_empty)
            self.rooms[code] = room
            log.info("Room created: %s (mode=%s)", code, settings.mode)
            return room

    def _unique_code_locked(self) -> str:
        """(lock held) Generate a readable 6-char room code not in use."""
        while True:
            code = "".join(random.choices(_ROOM_CODE_ALPHABET, k=6))
            if code not in self.rooms:
                return code

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def _on_room_empty(self, code: str) -> None:
        """Callback when a room reports it has no connected humans left."""
        with self.lock:
            room = self.rooms.get(code)
            if room is None:
                return
            # Never delete the default room; just let it sit idle for reuse.
            if code == self.default_room_code:
                return
            # Double-check under our lock before removing.
            if room.is_empty():
                self.rooms.pop(code, None)
                log.info("Room removed (empty): %s", code)

    def cleanup_empty_rooms(self) -> None:
        """Remove all empty, non-default rooms (used periodically)."""
        with self.lock:
            for code in list(self.rooms.keys()):
                if code == self.default_room_code:
                    continue
                room = self.rooms[code]
                if room.is_empty():
                    self.rooms.pop(code, None)

    def all_rooms(self) -> List[Room]:
        with self.lock:
            return list(self.rooms.values())

    def close_all(self) -> None:
        """Stop every room (server shutdown)."""
        for room in self.all_rooms():
            room.close()
