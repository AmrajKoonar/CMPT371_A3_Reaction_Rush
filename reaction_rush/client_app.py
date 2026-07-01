"""
client_app.py — Tkinter GUI client application for Reaction Rush v2.

This module is the *controller*: it owns the Tk root, the network socket, the
message queue, and all navigation/state. Screen construction is delegated to
:class:`reaction_rush.ui.screens.ScreenManager`; visual styling comes from
:mod:`reaction_rush.ui.theme` / :mod:`reaction_rush.ui.components`.

Threading model
---------------
* **Main (Tk) thread** — owns every widget. Socket *sends* are quick,
  non-blocking ``sendall`` calls, so they are safe here.
* **Receiver thread** — loops on ``receive_messages`` and pushes parsed dicts
  into a ``queue.Queue``.
* **Queue poller** — a ``root.after`` callback drains the queue every 50 ms
  and dispatches on the main thread, keeping Tkinter single-threaded.

The client speaks the v2 protocol but stays compatible with the classic flow:
connecting with an access code drops the player into the server's default room.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import List, Optional

from . import __version__, constants as C
from .config import ClientSettings
from .protocol import (
    make_message, receive_messages, send_message,
)
from .ui import theme as T
from .ui.screens import ScreenManager
from .ui.sounds import SoundManager
from .utils import safe_close, valid_player_name

_SETTINGS_FILE = "reaction_rush_client.json"


class ReactionRushClient:
    """The Reaction Rush desktop client."""

    # -----------------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------------

    def __init__(self, cli_host: Optional[str] = None,
                 cli_port: Optional[int] = None,
                 cli_name: Optional[str] = None) -> None:
        self.version = __version__

        # Persisted preferences (theme, sound, defaults).
        self.settings = self._load_settings()
        if cli_host:
            self.settings.default_host = cli_host
        if cli_port:
            self.settings.default_port = cli_port
        if cli_name:
            self.settings.player_name = cli_name

        self.palette = T.get_palette(self.settings.theme)

        # Tk root.
        self.root = tk.Tk()
        self.root.title("Reaction Rush")
        self.root.geometry("900x680")
        self.root.minsize(720, 560)
        self.root.configure(bg=self.palette["bg"])

        self.container = tk.Frame(self.root, bg=self.palette["bg"])
        self.container.pack(fill=tk.BOTH, expand=True)

        self.screens = ScreenManager(self)
        self.sounds = SoundManager(
            enabled=self.settings.sound_enabled,
            volume=self.settings.volume,
            bell=self.root.bell,
        )

        # Network state.
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.running = True
        self.msg_queue: "queue.Queue" = queue.Queue()

        # Session / room state.
        self.player_name = self.settings.player_name
        self.my_player_id = ""
        self.session_token = ""
        self.room_code = ""
        self.is_host = False
        self.room_settings: dict = {}
        self.lobby_players: List[dict] = []

        # Game state.
        self.mode = C.MODE_CLASSIC
        self.current_round = 0
        self.total_rounds = 5
        self.round_state = "idle"   # idle|red|green|penalized|clicked

        # Widget references (reset per screen).
        self.current_screen: Optional[tk.Widget] = None
        self.status_label: Optional[tk.Label] = None
        self.ready_btn: Optional[tk.Button] = None
        self.rematch_btn: Optional[tk.Button] = None
        self.lobby_players_frame: Optional[tk.Frame] = None
        self.game_frame: Optional[tk.Frame] = None
        self.game_panel: Optional[tk.Frame] = None
        self.game_label: Optional[tk.Label] = None
        self.game_label_font = None
        self.game_hint_label: Optional[tk.Label] = None
        self.round_info_label: Optional[tk.Label] = None

        # Overlay / timers.
        self._overlay: Optional[tk.Frame] = None
        self._overlay_after: List[str] = []

        # Practice mode state.
        self.practice_state = "idle"
        self.practice_green_time = 0.0
        self._practice_after: Optional[str] = None
        self.practice_db = None
        self._init_practice_db()

        # Boot.
        self.screens.build_landing()
        self._poll_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.action_quit)

    def run(self) -> None:
        """Enter the Tkinter main loop."""
        self.root.mainloop()

    # -----------------------------------------------------------------------
    # Settings persistence
    # -----------------------------------------------------------------------

    def _load_settings(self) -> ClientSettings:
        try:
            if os.path.exists(_SETTINGS_FILE):
                with open(_SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    return ClientSettings.from_dict(json.load(fh))
        except (OSError, ValueError):
            pass
        return ClientSettings()

    def _save_settings(self) -> None:
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(self.settings.to_dict(), fh, indent=2)
        except OSError:
            pass

    def _init_practice_db(self) -> None:
        """Open the local practice-stats SQLite database (best effort)."""
        try:
            from .persistence import Database
            self.practice_db = Database(C.PRACTICE_DB_PATH)
        except Exception:
            self.practice_db = None

    # -----------------------------------------------------------------------
    # Screen ref management + overlay
    # -----------------------------------------------------------------------

    def reset_screen_refs(self) -> None:
        """Clear per-screen widget references (called by ScreenManager)."""
        self.status_label = None
        self.ready_btn = None
        self.rematch_btn = None
        self.lobby_players_frame = None
        self.game_frame = None
        self.game_panel = None
        self.game_label = None
        self.game_label_font = None
        self.game_hint_label = None
        self.round_info_label = None
        self.current_screen = None

    def cancel_overlay(self) -> None:
        for aid in self._overlay_after:
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._overlay_after.clear()
        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None

    def show_overlay(self, text: str, colour: str,
                     duration_ms: int = 1300) -> None:
        """Show a short animated headline over the current screen."""
        self.cancel_overlay()
        host = self.current_screen or self.container
        base = str(host.cget("bg"))
        overlay = tk.Frame(host, bg=base)
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self._overlay = overlay

        shadow = tk.Label(overlay, text=text, font=T.font(80, True),
                          fg="#05070c", bg=base)
        shadow.place(relx=0.5, rely=0.51, anchor="center")
        main = tk.Label(overlay, text=text, font=T.font(80, True),
                        fg=colour, bg=base)
        main.place(relx=0.5, rely=0.49, anchor="center")
        tk.Label(overlay, text="REACTION RUSH", font=T.font(16, True),
                 fg=self.palette["text"], bg=base).place(
            relx=0.5, rely=0.66, anchor="center")
        overlay.lift()

        sizes = [60, 84, 100]
        for i, sz in enumerate(sizes):
            aid = self.root.after(
                i * 70,
                lambda s=sz: (shadow.config(font=T.font(s, True)),
                              main.config(font=T.font(s, True))))
            self._overlay_after.append(aid)

        self._overlay_after.append(self.root.after(duration_ms, self.cancel_overlay))

    def round_feedback(self, data: dict) -> tuple:
        """Pick a short result message + colour for this player's round."""
        mine = None
        results = data.get("results", [])
        for r in results:
            if r.get("player_name") == self.player_name:
                mine = r
                break
        if not mine:
            return "Round Over", self.palette["text"]
        if mine.get("false_start"):
            return "Too soon!", self.palette["orange"]
        if mine.get("timed_out"):
            return "Too late!", self.palette["danger"]
        top = max((r.get("score", 0) for r in results), default=0)
        if mine.get("score", 0) == top and top > 0:
            return "Nice!", self.palette["success"]
        return "Good try", self.palette["warning"]

    # -----------------------------------------------------------------------
    # Reaction-screen colour helpers
    # -----------------------------------------------------------------------

    def fit_game_label(self) -> None:
        """Shrink the reaction headline so it fits the panel width."""
        if not (self.game_panel and self.game_label and self.game_label_font):
            return
        width = self.game_panel.winfo_width()
        if width <= 1:
            return
        text = str(self.game_label.cget("text"))
        avail = max(width - 60, 120)
        for size in range(48, 23, -2):
            self.game_label_font.configure(size=size)
            if self.game_label_font.measure(text) <= avail:
                break

    def set_game_colour(self, bg: str, text: str) -> None:
        """Update the reaction area's colour, headline, and hint."""
        if self.game_frame:
            self.game_frame.config(bg=bg)
        if self.game_panel:
            self.game_panel.config(bg=bg)
            for child in self.game_panel.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(bg=bg)
        if self.game_label:
            self.game_label.config(bg=bg, text=text)
            self.fit_game_label()
        if self.game_hint_label:
            hint = "Wait for green"
            if bg == self.palette["green"]:
                hint = "Click now!"
            elif bg == self.palette["orange"]:
                hint = "Penalty applied"
            self.game_hint_label.config(text=hint)

    # -----------------------------------------------------------------------
    # Navigation
    # -----------------------------------------------------------------------

    def go_landing(self) -> None:
        self.screens.build_landing()

    def go_join(self) -> None:
        self.screens.build_join()

    def go_create(self) -> None:
        self.screens.build_create()

    def go_practice(self) -> None:
        self.practice_state = "idle"
        self.screens.build_practice()

    def go_settings(self) -> None:
        self.screens.build_settings()

    # -----------------------------------------------------------------------
    # Networking helpers
    # -----------------------------------------------------------------------

    def _open_socket(self, host: str, port: int) -> bool:
        """(Re)connect the TCP socket and start a fresh receiver thread."""
        self.connected = False
        if self.sock is not None:
            safe_close(self.sock)
            self.sock = None
        while not self.msg_queue.empty():
            try:
                self.msg_queue.get_nowait()
            except queue.Empty:
                break
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((host, port))
            s.settimeout(1.0)
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            self._set_status(f"Connection failed: {exc}", error=True)
            return False
        self.sock = s
        self.connected = True
        my_sock = s
        threading.Thread(target=self._recv_loop, args=(my_sock,),
                         daemon=True).start()
        return True

    def _set_status(self, text: str, error: bool = False) -> None:
        if self.status_label is not None and self.status_label.winfo_exists():
            self.status_label.config(
                text=text,
                fg=self.palette["danger"] if error else self.palette["gold"])

    def _recv_loop(self, my_sock: socket.socket) -> None:
        buf = ""
        while self.running and self.sock is my_sock:
            msgs, buf = receive_messages(my_sock, buf)
            if msgs is None:
                if self.sock is my_sock:
                    self.msg_queue.put({"type": C.MSG_INTERNAL_DISCONNECTED})
                break
            for m in msgs:
                if self.sock is my_sock:
                    self.msg_queue.put(m)

    def _poll_queue(self) -> None:
        try:
            while True:
                self._handle(self.msg_queue.get_nowait())
        except queue.Empty:
            pass
        if self.running:
            self.root.after(50, self._poll_queue)

    # -----------------------------------------------------------------------
    # Actions (called from screens)
    # -----------------------------------------------------------------------

    def action_join(self, host: str, port: str, room_code: str,
                    access_code: str, name: str) -> None:
        if not host or not port or not name:
            self._set_status("Host, port and name are required.", error=True)
            return
        if not valid_player_name(name):
            self._set_status("Name must be 1–20 characters.", error=True)
            return
        try:
            port_num = int(port)
        except ValueError:
            self._set_status("Port must be a number.", error=True)
            return

        self._set_status("Connecting …")
        self.root.update_idletasks()
        if not self._open_socket(host, port_num):
            return

        self.player_name = name
        self.settings.player_name = name
        self.settings.default_host = host
        self.settings.default_port = port_num
        self._save_settings()

        if room_code:
            send_message(self.sock, make_message(
                C.MSG_JOIN_ROOM, room_code=room_code.upper(),
                player_name=name))
        else:
            send_message(self.sock, make_message(
                C.MSG_JOIN_REQUEST, player_name=name,
                access_code=access_code or C.DEFAULT_ACCESS_CODE))

    def action_create_room(self, host: str, port: str, name: str,
                           settings: dict) -> None:
        if not host or not port or not name:
            self._set_status("Host, port and name are required.", error=True)
            return
        if not valid_player_name(name):
            self._set_status("Name must be 1–20 characters.", error=True)
            return
        try:
            port_num = int(port)
        except ValueError:
            self._set_status("Port must be a number.", error=True)
            return

        self._set_status("Connecting …")
        self.root.update_idletasks()
        if not self._open_socket(host, port_num):
            return

        self.player_name = name
        self.settings.player_name = name
        self.settings.default_host = host
        self.settings.default_port = port_num
        self._save_settings()

        send_message(self.sock, make_message(
            C.MSG_CREATE_ROOM, player_name=name, settings=settings))

    def action_ready(self) -> None:
        self.sounds.click()
        send_message(self.sock, make_message(C.MSG_READY))
        if self.ready_btn is not None:
            self.ready_btn.config(state="disabled", text="Ready \u2713")

    def action_add_bot(self, level: str) -> None:
        send_message(self.sock, make_message(C.MSG_ADD_BOT, bot_level=level))

    def action_remove_bot(self, bot_id: str) -> None:
        send_message(self.sock, make_message(C.MSG_REMOVE_BOT, bot_id=bot_id))

    def action_leave_room(self) -> None:
        if self.sock is not None:
            send_message(self.sock, make_message(C.MSG_LEAVE_ROOM))
            send_message(self.sock, make_message(
                C.MSG_DISCONNECT, message="Left room."))
            safe_close(self.sock)
            self.sock = None
        self.connected = False
        self._reset_room_state()
        self.go_landing()

    def action_rematch(self) -> None:
        self.sounds.click()
        send_message(self.sock, make_message(C.MSG_REMATCH_READY))
        if self.rematch_btn is not None:
            self.rematch_btn.config(state="disabled", text="Waiting …")

    def action_copy_code(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.room_code)
        except Exception:
            pass

    def action_game_click(self) -> None:
        """Handle a click on the reaction area."""
        if self.round_state == "red":
            self.round_state = "penalized"
            self.set_game_colour(self.palette["orange"], "Penalty: Too soon!")
            self.sounds.false_start()
            send_message(self.sock, make_message(
                C.MSG_CLICK, early=True, round_number=self.current_round,
                client_clicked_at=time.perf_counter()))
        elif self.round_state == "green":
            self.round_state = "clicked"
            self.set_game_colour(self.palette["green"], "Clicked! Waiting …")
            self.sounds.click()
            send_message(self.sock, make_message(
                C.MSG_CLICK, early=False, round_number=self.current_round,
                client_clicked_at=time.perf_counter()))

    def action_save_settings(self, theme: str, sound: bool, volume: float,
                             host: str, port: str, name: str,
                             debug: bool) -> None:
        self.settings.theme = theme
        self.settings.sound_enabled = bool(sound)
        self.settings.volume = float(volume)
        self.settings.default_host = host or C.DEFAULT_HOST
        try:
            self.settings.default_port = int(port)
        except ValueError:
            pass
        self.settings.player_name = name
        self.settings.debug_mode = bool(debug)
        self._save_settings()

        # Apply immediately.
        self.palette = T.get_palette(theme)
        self.root.configure(bg=self.palette["bg"])
        self.container.configure(bg=self.palette["bg"])
        self.sounds.set_enabled(self.settings.sound_enabled)
        self.sounds.set_volume(self.settings.volume)
        self.go_landing()

    def action_quit(self) -> None:
        self.running = False
        self.connected = False
        if self.sock is not None:
            send_message(self.sock, make_message(
                C.MSG_DISCONNECT, message="Client quit."))
            safe_close(self.sock)
        if self.practice_db is not None:
            self.practice_db.close()
        self.root.destroy()

    def _reset_room_state(self) -> None:
        self.my_player_id = ""
        self.room_code = ""
        self.is_host = False
        self.room_settings = {}
        self.lobby_players = []

    # -----------------------------------------------------------------------
    # Message dispatch
    # -----------------------------------------------------------------------

    def _handle(self, msg: dict) -> None:
        t = msg.get("type", "")
        handler = {
            C.MSG_JOIN_RESPONSE: self._on_join_response,
            C.MSG_ROOM_CREATED: self._on_room_created,
            C.MSG_ROOM_ERROR: self._on_room_error,
            C.MSG_LOBBY_UPDATE: self._on_lobby_update,
            C.MSG_GAME_START: self._on_game_start,
            C.MSG_ROUND_PREPARE: self._on_round_prepare,
            C.MSG_ROUND_GO: self._on_round_go,
            C.MSG_FAKE_SIGNAL: self._on_fake_signal,
            C.MSG_PENALTY: self._on_penalty,
            C.MSG_ROUND_RESULT: self._on_round_result,
            C.MSG_GAME_OVER: self._on_game_over,
            C.MSG_ERROR: self._on_error,
            C.MSG_PLAYER_LEFT: self._on_player_left,
            C.MSG_PLAYER_DISCONNECTED: self._noop,
            C.MSG_PLAYER_RECONNECTED: self._noop,
            C.MSG_REMATCH_UPDATE: self._on_rematch_update,
            C.MSG_NEW_MATCH: self._on_new_match,
            C.MSG_PING: self._on_ping,
            C.MSG_LATENCY: self._noop,
            C.MSG_BOT_ADDED: self._noop,
            C.MSG_BOT_REMOVED: self._noop,
            C.MSG_DISCONNECT: self._on_server_disconnect,
            C.MSG_INTERNAL_DISCONNECTED: self._on_server_disconnect,
        }.get(t)
        if handler:
            handler(msg)

    def _noop(self, _msg: dict) -> None:
        pass

    # -- handlers -----------------------------------------------------------

    def _on_join_response(self, msg: dict) -> None:
        if msg.get("success"):
            self.my_player_id = msg.get("player_id", "")
            self.session_token = msg.get("session_token", "")
            self.room_code = msg.get("room_code", "")
            self.room_settings = msg.get("settings", {})
            self.mode = self.room_settings.get("mode", C.MODE_CLASSIC)
            self.screens.build_lobby()
        else:
            self.connected = False
            safe_close(self.sock)
            self.sock = None
            self._set_status(msg.get("message", "Join rejected."), error=True)

    def _on_room_created(self, msg: dict) -> None:
        if msg.get("success"):
            self.my_player_id = msg.get("player_id", "")
            self.session_token = msg.get("session_token", "")
            self.room_code = msg.get("room_code", "")
            self.room_settings = msg.get("settings", {})
            self.mode = self.room_settings.get("mode", C.MODE_CLASSIC)
            self.is_host = True
            self.screens.build_lobby()
        else:
            self._set_status(msg.get("message", "Could not create room."),
                             error=True)

    def _on_room_error(self, msg: dict) -> None:
        self.connected = False
        if self.sock is not None:
            safe_close(self.sock)
            self.sock = None
        self._set_status(msg.get("message", "Room error."), error=True)

    def _on_lobby_update(self, msg: dict) -> None:
        self.lobby_players = msg.get("players_v2") or [
            {"name": p["name"], "ready": p["ready"]}
            for p in msg.get("players", [])
        ]
        if msg.get("room_code"):
            self.room_code = msg["room_code"]
        if msg.get("settings"):
            self.room_settings = msg["settings"]
        host_id = msg.get("host_id")
        if host_id is not None:
            self.is_host = (host_id == self.my_player_id)
        # Refresh lobby view if we're on it.
        if self.lobby_players_frame is not None:
            self.screens.refresh_lobby_players()
            ready = sum(1 for p in self.lobby_players if p.get("ready"))
            if self.status_label is not None:
                self.status_label.config(
                    text=f"{len(self.lobby_players)} player(s) connected"
                         f"  —  {ready} ready")

    def _on_game_start(self, msg: dict) -> None:
        self.total_rounds = msg.get("total_rounds", 5)
        self.mode = msg.get("mode", C.MODE_CLASSIC)
        self.cancel_overlay()
        self.screens._clear()
        splash = tk.Frame(self.container, bg=self.palette["bg"])
        splash.place(relx=0.5, rely=0.5, anchor="center")
        self.current_screen = splash
        tk.Label(splash, text="Get Ready", font=T.font(34, True),
                 fg=self.palette["gold"], bg=self.palette["bg"]).pack()
        tk.Label(splash, text=f"Mode: {self.mode}  ·  {self.total_rounds} rounds",
                 font=T.font(13), fg=self.palette["text_muted"],
                 bg=self.palette["bg"]).pack(pady=8)

    def _on_round_prepare(self, msg: dict) -> None:
        rnd = msg.get("round_number", 1)
        total = msg.get("total_rounds", self.total_rounds)
        self.screens.build_game(rnd, total)
        self.sounds.prepare()

    def _on_round_go(self, _msg: dict) -> None:
        if self.round_state == "red":
            self.round_state = "green"
            self.set_game_colour(self.palette["green"], "Click!")
            self.sounds.go()

    def _on_fake_signal(self, _msg: dict) -> None:
        """Chaos mode decoy: brief tint while still in the 'wait' state."""
        if self.round_state != "red" or not self.game_panel:
            return
        decoy = "#c0392b"  # slightly different red so a click is still a fault
        try:
            self.game_panel.config(bg=decoy)
            if self.game_label:
                self.game_label.config(bg=decoy, text="Not yet…")
            self.root.after(180, lambda: self._restore_red())
        except Exception:
            pass

    def _restore_red(self) -> None:
        if self.round_state == "red":
            self.set_game_colour(self.palette["red"], "Wait for green …")

    def _on_penalty(self, _msg: dict) -> None:
        if self.round_state != "penalized":
            self.round_state = "penalized"
            self.set_game_colour(self.palette["orange"], "Penalty: Too soon!")
            self.sounds.false_start()

    def _on_round_result(self, msg: dict) -> None:
        self.screens.build_round_result(msg)
        self.sounds.result()

    def _on_game_over(self, msg: dict) -> None:
        self.screens.build_game_over(msg)
        self.sounds.game_over()

    def _on_error(self, msg: dict) -> None:
        messagebox.showwarning("Server", msg.get("message", "Unknown error."))

    def _on_player_left(self, msg: dict) -> None:
        name = msg.get("player_name", "?")
        if self.status_label is not None and self.status_label.winfo_exists():
            self.status_label.config(text=f"{name} disconnected.")

    def _on_rematch_update(self, msg: dict) -> None:
        players = msg.get("players", [])
        ready = sum(1 for p in players if p.get("rematch_ready"))
        if self.rematch_btn is not None and self.rematch_btn.winfo_exists():
            self.rematch_btn.config(
                text=f"Rematch ({ready}/{len(players)})")

    def _on_new_match(self, msg: dict) -> None:
        self.room_settings = msg.get("settings", self.room_settings)
        self.mode = self.room_settings.get("mode", self.mode)
        self.cancel_overlay()

    def _on_ping(self, msg: dict) -> None:
        # Reply so the server can measure RTT and know we're alive.
        send_message(self.sock, make_message(
            C.MSG_PONG, client_time=time.perf_counter(),
            server_time=msg.get("server_time")))

    def _on_server_disconnect(self, _msg: dict) -> None:
        if not self.connected:
            return
        self.connected = False
        messagebox.showinfo("Disconnected", "Lost connection to the server.")
        self._reset_room_state()
        self.go_landing()

    # -----------------------------------------------------------------------
    # Practice mode (fully offline)
    # -----------------------------------------------------------------------

    def practice_click(self) -> None:
        if self.practice_state in ("idle", "done"):
            self.practice_state = "red"
            self.set_game_colour(self.palette["red"], "Wait for green …")
            delay = random.uniform(1.5, 4.0)
            self._practice_after = self.root.after(
                int(delay * 1000), self._practice_go)
        elif self.practice_state == "red":
            # False start.
            self.practice_state = "done"
            if self._practice_after:
                self.root.after_cancel(self._practice_after)
                self._practice_after = None
            self.set_game_colour(self.palette["orange"], "Too soon!")
            self.sounds.false_start()
            self._practice_record(None, True)
            self.root.after(1200, self._practice_reset_prompt)
        elif self.practice_state == "green":
            reaction_ms = (time.perf_counter() - self.practice_green_time) * 1000
            self.practice_state = "done"
            self.set_game_colour(self.palette["green"],
                                 f"{reaction_ms:.0f} ms")
            self.sounds.click()
            self._practice_record(reaction_ms, False)
            self.root.after(1400, self._practice_reset_prompt)

    def _practice_go(self) -> None:
        if self.practice_state == "red":
            self.practice_state = "green"
            self.practice_green_time = time.perf_counter()
            self.set_game_colour(self.palette["green"], "CLICK!")
            self.sounds.go()

    def _practice_reset_prompt(self) -> None:
        if self.practice_state == "done":
            self.practice_state = "idle"
            self.set_game_colour(self.palette["red"], "Click to start")

    def _practice_record(self, reaction_ms, false_start: bool) -> None:
        if self.practice_db is not None:
            try:
                self.practice_db.save_practice_result(
                    self.player_name or "You", reaction_ms, false_start)
            except Exception:
                pass
        if getattr(self, "practice_stats_label", None) is not None:
            try:
                self.practice_stats_label.config(text=self.practice_summary_text())
            except Exception:
                pass

    def practice_reset(self) -> None:
        if self.practice_db is not None:
            try:
                self.practice_db.reset_practice_results(self.player_name or "You")
            except Exception:
                pass
        if getattr(self, "practice_stats_label", None) is not None:
            self.practice_stats_label.config(text=self.practice_summary_text())

    def practice_summary_text(self) -> str:
        if self.practice_db is None:
            return "Practice stats unavailable."
        try:
            from .stats import summarize_practice
            attempts = self.practice_db.get_practice_results(
                self.player_name or "You")
            s = summarize_practice(attempts)
            best = self.practice_db.get_personal_best(self.player_name or "You")
        except Exception:
            return "Practice stats unavailable."
        if s["attempts"] == 0:
            return "No attempts yet — click the panel to begin."
        best_txt = f"{best:.0f} ms" if best else "—"
        return (f"Attempts: {s['attempts']}   ·   Best: {best_txt}   ·   "
                f"Avg: {s['average_ms']:.0f} ms   ·   "
                f"False starts: {s['false_starts']}   ·   "
                f"Consistency: {s['consistency']}")


# ============================================================================
# CLI entry point
# ============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Reaction Rush v2 — Tkinter game client")
    ap.add_argument("--host", default=None, help="Prefill server host")
    ap.add_argument("--port", type=int, default=None, help="Prefill server port")
    ap.add_argument("--name", default=None, help="Prefill player name")
    return ap


def main(argv=None) -> None:
    args = build_arg_parser().parse_args(argv)
    app = ReactionRushClient(
        cli_host=args.host, cli_port=args.port, cli_name=args.name)
    app.run()


if __name__ == "__main__":
    main()
