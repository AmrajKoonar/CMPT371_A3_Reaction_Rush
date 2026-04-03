"""
client.py

Tkinter client for Reaction Rush.

This file handles:
- connecting to the server
- showing the lobby and ready state
- showing the reaction screen
- displaying round results and final results
- handling disconnects from the server
"""

import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional

from protocol import (
    MSG_JOIN_REQUEST, MSG_JOIN_RESPONSE, MSG_LOBBY_UPDATE,
    MSG_READY, MSG_GAME_START, MSG_ROUND_PREPARE, MSG_ROUND_GO,
    MSG_CLICK, MSG_PENALTY, MSG_ROUND_RESULT, MSG_GAME_OVER,
    MSG_ERROR, MSG_DISCONNECT, MSG_PLAYER_LEFT,
    make_message, send_message, receive_messages,
)
from utils import safe_close, format_ms

# UI colours
BG_DARK    = "#1a1a2e"    # window / connect-screen background
BG_PANEL   = "#16213e"    # lobby card background
BG_ACCENT  = "#0f3460"    # info-bar strip
BG_CARD    = "#111827"
BG_CARD_ALT = "#1f2937"
BG_STROKE  = "#31415f"
FG_LIGHT   = "#e0e0e0"    # secondary text
FG_WHITE   = "#ffffff"    # primary text
FG_MUTED   = "#aab5c9"
BTN_BLUE   = "#3498db"    # default button
BTN_GREEN  = "#2ecc71"    # ready button
RED_SCREEN = "#e74c3c"    # reaction "wait" phase
GREEN_SCREEN = "#27ae60"  # reaction "click!" phase
ORANGE_SCREEN = "#e67e22" # false-start penalty
RESULT_BG  = "#2c3e50"    # round-result / leaderboard panel
GOLD       = "#f1c40f"

class ReactionRushClient:
    """GUI client for the multiplayer game"""

    # Window setup and shared state
    def __init__(self) -> None:
        # Main window
        self.root = tk.Tk()
        self.root.title("Reaction Rush")
        self.root.geometry("820x620")
        self.root.minsize(640, 480)
        self.root.configure(bg=BG_DARK)

        # Network state
        self.sock: Optional[socket.socket] = None
        self.connected: bool = False
        self.running: bool = True
        self.msg_queue: queue.Queue = queue.Queue()

        # Game state
        self.player_name: str = ""
        self.current_round: int = 0
        self.total_rounds: int = 5
        self.round_state: str = "idle"

        # Every screen in the app is drawn inside this container frame
        self.container = tk.Frame(self.root, bg=BG_DARK)
        self.container.pack(fill=tk.BOTH, expand=True)

        # Widget references that get reused across different screens
        self.game_frame: Optional[tk.Frame] = None
        self.game_label: Optional[tk.Label] = None
        self.round_info_label: Optional[tk.Label] = None
        self.game_hint_label: Optional[tk.Label] = None
        self.lobby_players_frame: Optional[tk.Frame] = None
        self.lobby_status_label: Optional[tk.Label] = None
        self.connect_status_label: Optional[tk.Label] = None
        self._ready_btn: Optional[tk.Button] = None
        self._entries: list = []
        self._overlay_widget: Optional[tk.Frame] = None
        self._overlay_after_ids: list[str] = []
        self._current_screen: Optional[tk.Widget] = None

        self._show_connect_screen()
        self._poll_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def run(self) -> None:
        """Start the Tkinter event loop"""
        self.root.mainloop()

    # Screen helpers
    def _clear(self) -> None:
        """Clear the current screen and reset widget references"""
        self.container.config(bg=BG_DARK)
        for w in self.container.winfo_children():
            w.destroy()
        self.game_frame = None
        self.game_label = None
        self.round_info_label = None
        self.game_hint_label = None
        self.lobby_players_frame = None
        self.lobby_status_label = None
        self.connect_status_label = None
        self._ready_btn = None
        self._current_screen = None
        for after_id in self._overlay_after_ids:
            self.root.after_cancel(after_id)
        self._overlay_after_ids.clear()
        self._overlay_widget = None

    def _make_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        width: int,
    ) -> tk.Button:
        """Create a button using the shared app style"""
        return tk.Button(
            parent,
            text=text,
            font=("Helvetica", 13, "bold"),
            bg="#ffffff",
            fg="#000000",
            activebackground="#ffffff",
            activeforeground="#000000",
            disabledforeground="#000000",
            width=width,
            command=command,
            relief="raised",
            bd=3,
            highlightthickness=2,
            highlightbackground="#000000",
            highlightcolor="#000000",
            padx=8,
            pady=4,
        )

    def _make_panel(
        self,
        parent: tk.Widget,
        bg: str = BG_CARD,
        padx: int = 24,
        pady: int = 24,
    ) -> tk.Frame:
        """Create a reusable panel frame with an optional inner frame"""
        panel = tk.Frame(
            parent,
            bg=bg,
            bd=0,
            highlightthickness=1,
            highlightbackground=BG_STROKE,
        )
        if padx or pady:
            inner = tk.Frame(panel, bg=bg)
            inner.pack(fill=tk.BOTH, expand=True, padx=padx, pady=pady)
            panel.inner = inner  # type: ignore[attr-defined]  # easy way to access the padded inner area
        return panel

    @staticmethod
    def _panel_inner(panel: tk.Frame) -> tk.Frame:
        """Get the inner frame if one was created"""
        return getattr(panel, "inner", panel)

    def _style_entry(self, entry: tk.Entry) -> None:
        """Apply the shared style used for text inputs"""
        entry.config(
            font=("Helvetica", 13),
            width=24,
            bg="#f8fafc",
            fg="#0f172a",
            insertbackground="#0f172a",
            relief="flat",
            highlightthickness=2,
            highlightbackground=BG_STROKE,
            highlightcolor=BTN_BLUE,
            bd=0,
        )

    def _show_overlay_message(
        self,
        text: str,
        fg: str = FG_WHITE,
        duration_ms: int = 1300,
    ) -> None:
        """Show a short animated message over the current screen"""
        for after_id in self._overlay_after_ids:
            self.root.after_cancel(after_id)
        self._overlay_after_ids.clear()
        if self._overlay_widget is not None:
            self._overlay_widget.destroy()
            self._overlay_widget = None

        host = self._current_screen if self._current_screen is not None else self.container
        base_bg = str(host.cget("bg"))
        overlay = tk.Frame(
            host,
            bg=base_bg,
            bd=0,
            highlightthickness=0,
        )
        overlay.place(x=0, y=0, relwidth=1, relheight=1)

        sparkle = tk.Label(
            overlay,
            text="✦ ✦ ✦",
            font=("Helvetica", 24, "bold"),
            fg=fg,
            bg=base_bg,
        )
        sparkle.place(relx=0.5, rely=0.27, anchor="center")

        shadow = tk.Label(
            overlay,
            text=text,
            font=("Helvetica", 88, "bold"),
            fg="#05070c",
            bg=base_bg,
        )
        shadow.place(relx=0.5, rely=0.51, anchor="center")

        main = tk.Label(
            overlay,
            text=text,
            font=("Helvetica", 88, "bold"),
            fg=fg,
            bg=base_bg,
        )
        main.place(relx=0.5, rely=0.49, anchor="center")

        subtitle = tk.Label(
            overlay,
            text="REACTION RUSH",
            font=("Helvetica", 18, "bold"),
            fg=FG_WHITE,
            bg=base_bg,
        )
        subtitle.place(relx=0.5, rely=0.66, anchor="center")

        self._overlay_widget = overlay
        overlay.lift()
        if host is not self.container and isinstance(host, tk.Widget):
            for child in host.winfo_children():
                if child is not overlay:
                    overlay.lift(child)

        sizes = [62, 88, 124, 112]
        y_positions = [0.54, 0.5, 0.47, 0.49]

        def _set_style(size: int, y_pos: float, sparkle_text: str) -> None:
            if self._overlay_widget is overlay:
                shadow.config(font=("Helvetica", size, "bold"))
                main.config(font=("Helvetica", size, "bold"))
                shadow.place_configure(relx=0.5, rely=y_pos + 0.02, anchor="center")
                main.place_configure(relx=0.5, rely=y_pos, anchor="center")
                sparkle.config(text=sparkle_text)

        sparkles = ["✦", "✦ ✦", "✦ ✦ ✦", "✦ ✦"]

        for index, (size, y_pos, sparkle_text) in enumerate(zip(sizes, y_positions, sparkles)):
            if index == 0:
                _set_style(size, y_pos, sparkle_text)
            else:
                after_id = self.root.after(
                    index * 80,
                    lambda s=size, y=y_pos, st=sparkle_text: _set_style(s, y, st),
                )
                self._overlay_after_ids.append(after_id)

        def _clear_overlay() -> None:
            if self._overlay_widget is overlay:
                overlay.destroy()
                self._overlay_widget = None
            self._overlay_after_ids.clear()

        self._overlay_after_ids.append(self.root.after(duration_ms, _clear_overlay))

    def _get_round_feedback(self, data: dict) -> tuple[str, str]:
        """Pick the short result message for this player."""
        my_result = None
        results = data.get("results", [])
        for result in results:
            if result.get("player_name") == self.player_name:
                my_result = result
                break

        if not my_result:
            return "Round Over!", FG_WHITE
        if my_result.get("false_start"):
            return "Too soon!", "#ffb347"
        if my_result.get("timed_out"):
            return "Too late!", "#ff7a7a"

        top_score = max((r.get("score", 0) for r in results), default=0)
        if my_result.get("score", 0) == top_score and top_score > 0:
            return "Nice!", "#7CFFB2"
        return "Too late!", "#ff7a7a"

    # Connect screen
    def _show_connect_screen(self) -> None:
        """Show the connection form."""
        self._clear()

        outer = tk.Frame(self.container, bg=BG_DARK)
        outer.place(relx=0.5, rely=0.5, anchor="center")
        self._current_screen = outer

        tk.Label(
            outer, text="Reaction Rush",
            font=("Helvetica", 34, "bold"), fg=FG_WHITE, bg=BG_DARK,
        ).pack(anchor="w")
        tk.Label(
            outer, text="Fast TCP multiplayer reaction game",
            font=("Helvetica", 13), fg=FG_MUTED, bg=BG_DARK,
        ).pack(anchor="w", pady=(6, 18))

        shell = tk.Frame(outer, bg=BG_DARK)
        shell.pack()

        form_panel = self._make_panel(shell, bg=BG_CARD, padx=26, pady=24)
        form_panel.pack(side=tk.LEFT, padx=(0, 18))
        frame = self._panel_inner(form_panel)

        tk.Label(
            frame, text="Join The Lobby",
            font=("Helvetica", 18, "bold"), fg=FG_WHITE, bg=BG_CARD,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(
            frame,
            text="Enter the server details and your player name.",
            font=("Helvetica", 11), fg=FG_MUTED, bg=BG_CARD,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 18))

        labels   = ["Host:", "Port:", "Access Code:", "Player Name:"]
        defaults = ["127.0.0.1", "5000", "RED123", ""]
        self._entries = []

        for i, (lbl, default) in enumerate(zip(labels, defaults)):
            tk.Label(
                frame, text=lbl, font=("Helvetica", 12),
                fg=FG_LIGHT, bg=BG_CARD,
            ).grid(row=i + 2, column=0, sticky="e", padx=(0, 12), pady=7)

            entry = tk.Entry(frame)
            self._style_entry(entry)
            entry.insert(0, default)
            entry.grid(row=i + 2, column=1, padx=0, pady=7, ipady=6)
            entry.bind("<Return>", lambda _e: self._do_connect())
            self._entries.append(entry)

        self._make_button(
            frame,
            text="Connect",
            width=18,
            command=self._do_connect,
        ).grid(row=len(labels) + 2, column=0, columnspan=2, pady=(18, 8))

        self.connect_status_label = tk.Label(
            frame, text="", font=("Helvetica", 11),
            fg="#e74c3c", bg=BG_CARD, justify="center",
        )
        self.connect_status_label.grid(
            row=len(labels) + 3, column=0, columnspan=2,
        )

        side_panel = self._make_panel(shell, bg=BG_PANEL, padx=24, pady=24)
        side_panel.config(width=280, height=312)
        side_panel.pack(side=tk.LEFT)
        side = self._panel_inner(side_panel)

        tk.Label(
            side, text="How It Works",
            font=("Helvetica", 16, "bold"), fg=FG_WHITE, bg=BG_PANEL,
        ).pack(anchor="w")
        tk.Label(
            side,
            text=(
                "1. Connect to the server\n"
                "2. Wait in the lobby\n"
                "3. Everyone clicks Ready\n"
                "4. React as soon as the screen turns green"
            ),
            font=("Helvetica", 12), fg=FG_LIGHT, bg=BG_PANEL,
            justify="left", anchor="w", padx=0, pady=0,
        ).pack(anchor="w", pady=(12, 18))
        tk.Label(
            side,
            text="Default access code: RED123",
            font=("Helvetica", 12, "bold"), fg=GOLD, bg=BG_PANEL,
        ).pack(anchor="w")
        tk.Label(
            side,
            text="Best shown with one server and two client windows side by side.",
            font=("Helvetica", 11), fg=FG_MUTED, bg=BG_PANEL,
            justify="left", wraplength=220,
        ).pack(anchor="w", pady=(12, 0))

        self._entries[3].focus_set()

    def _do_connect(self) -> None:
        """Connect to the server and send the join request."""
        host = self._entries[0].get().strip()
        port_str = self._entries[1].get().strip()
        code = self._entries[2].get().strip()
        name = self._entries[3].get().strip()

        if not host or not port_str or not code or not name:
            self.connect_status_label.config(text="All fields are required.")
            return
        try:
            port = int(port_str)
        except ValueError:
            self.connect_status_label.config(text="Port must be a number.")
            return

        self.connected = False
        if self.sock is not None:
            safe_close(self.sock)
            self.sock = None

        # Remove any old queued messages from a previous connection attempt
        while not self.msg_queue.empty():
            try:
                self.msg_queue.get_nowait()
            except queue.Empty:
                break

        self.connect_status_label.config(text="Connecting …", fg="#f1c40f")
        self.root.update_idletasks()

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((host, port))
            self.sock.settimeout(1.0)
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            self.connect_status_label.config(
                text=f"Connection failed: {exc}", fg="#e74c3c")
            self.sock = None
            return

        self.connected = True
        self.player_name = name

        # Keep this exact socket reference so old receiver threads can tell
        # when they no longer belong to the current connection
        my_sock = self.sock
        threading.Thread(
            target=self._recv_loop, args=(my_sock,), daemon=True,
        ).start()

        send_message(self.sock, make_message(
            MSG_JOIN_REQUEST, player_name=name, access_code=code))

    # Lobby helpers
    def _show_lobby_screen(self) -> None:
        """Show the lobby screen with the player list and ready button"""
        self._clear()

        top = tk.Frame(self.container, bg=BG_DARK)
        top.pack(fill=tk.X, padx=28, pady=(24, 14))
        self._current_screen = self.container

        tk.Label(
            top, text="Lobby", font=("Helvetica", 28, "bold"),
            fg=FG_WHITE, bg=BG_DARK,
        ).pack(anchor="w")

        self.lobby_status_label = tk.Label(
            top, text="Waiting for players …",
            font=("Helvetica", 12), fg=FG_MUTED, bg=BG_DARK,
        )
        self.lobby_status_label.pack(anchor="w", pady=(6, 0))

        mid = tk.Frame(self.container, bg=BG_DARK)
        mid.pack(fill=tk.BOTH, expand=True, padx=28, pady=8)

        players_panel = self._make_panel(mid, bg=BG_PANEL, padx=22, pady=22)
        players_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 16))
        mid_left = self._panel_inner(players_panel)

        tk.Label(
            mid_left, text="Players In Lobby", font=("Helvetica", 16, "bold"),
            fg=FG_WHITE, bg=BG_PANEL,
        ).pack(anchor="w")
        tk.Label(
            mid_left, text="Everyone must be ready before the game starts.",
            font=("Helvetica", 11), fg=FG_MUTED, bg=BG_PANEL,
        ).pack(anchor="w", pady=(4, 12))

        self.lobby_players_frame = tk.Frame(mid_left, bg=BG_PANEL)
        self.lobby_players_frame.pack(
            fill=tk.BOTH, expand=True,
        )

        side_panel = self._make_panel(mid, bg=BG_CARD, padx=22, pady=22)
        side_panel.config(width=250)
        side_panel.pack(side=tk.LEFT, fill=tk.Y)
        side = self._panel_inner(side_panel)

        tk.Label(
            side, text="Quick Rules", font=("Helvetica", 16, "bold"),
            fg=FG_WHITE, bg=BG_CARD,
        ).pack(anchor="w")
        tk.Label(
            side,
            text=(
                "Wait for green.\n"
                "Click too early and you get 0 points.\n"
                "Fastest player gets the most points."
            ),
            font=("Helvetica", 11), fg=FG_LIGHT, bg=BG_CARD,
            justify="left", wraplength=180,
        ).pack(anchor="w", pady=(10, 18))

        self._ready_btn = self._make_button(
            side,
            text="Ready",
            width=14,
            command=self._do_ready,
        )
        self._ready_btn.pack(anchor="w")
        tk.Label(
            side,
            text="Once you are ready, your button locks in.",
            font=("Helvetica", 10), fg=FG_MUTED, bg=BG_CARD,
            justify="left", wraplength=180,
        ).pack(anchor="w", pady=(10, 0))

    def _do_ready(self) -> None:
        """Tell the server this player is ready"""
        send_message(self.sock, make_message(MSG_READY))
        if self._ready_btn is not None:
            self._ready_btn.config(state="disabled", text="Ready  \u2713")

    def _update_lobby_players(self, players: list) -> None:
        """Refresh the player list shown in the lobby"""
        if self.lobby_players_frame is None:
            return

        for w in self.lobby_players_frame.winfo_children():
            w.destroy()

        for p in players:
            status = "Ready" if p["ready"] else "Waiting …"
            colour = "#2ecc71" if p["ready"] else "#f39c12"

            row = tk.Frame(
                self.lobby_players_frame,
                bg=BG_CARD_ALT,
                highlightthickness=1,
                highlightbackground=BG_STROKE,
            )
            row.pack(fill=tk.X, pady=6, ipady=8)

            tk.Label(
                row, text=p["name"], font=("Helvetica", 13),
                fg=FG_WHITE, bg=BG_CARD_ALT, anchor="w",
            ).pack(side=tk.LEFT, padx=10)

            tk.Label(
                row, text=status, font=("Helvetica", 12, "bold"),
                fg=colour, bg=BG_CARD_ALT, anchor="e",
            ).pack(side=tk.RIGHT, padx=10)

    # Game screen
    def _show_game_screen(self, round_num: int, total: int) -> None:
        """Show the main reaction screen for the current round"""
        self._clear()
        self.current_round = round_num
        self.total_rounds = total
        self.round_state = "red"

        info = tk.Frame(self.container, bg=BG_ACCENT, height=58)
        info.pack(fill=tk.X, padx=20, pady=(16, 0))
        info.pack_propagate(False)

        self.round_info_label = tk.Label(
            info, text=f"Round {round_num} of {total}",
            font=("Helvetica", 16, "bold"), fg=FG_WHITE, bg=BG_ACCENT,
        )
        self.round_info_label.pack(side=tk.LEFT, padx=18)

        self.game_hint_label = tk.Label(
            info, text="Wait for green",
            font=("Helvetica", 12), fg=FG_LIGHT, bg=BG_ACCENT,
        )
        self.game_hint_label.pack(side=tk.RIGHT, padx=18)

        self.game_frame = tk.Frame(self.container, bg=RED_SCREEN)
        self.game_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(12, 20))
        self._current_screen = self.game_frame

        center_panel = tk.Frame(
            self.game_frame,
            bg=RED_SCREEN,
            bd=0,
            highlightthickness=3,
            highlightbackground=FG_WHITE,
        )
        center_panel.place(relx=0.5, rely=0.5, anchor="center", width=520, height=250)

        self.game_label = tk.Label(
            center_panel, text="Wait for green \u2026",
            font=("Helvetica", 48, "bold"), fg=FG_WHITE, bg=RED_SCREEN,
        )
        self.game_label.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(
            center_panel,
            text="Click anywhere once the screen changes.",
            font=("Helvetica", 14), fg="#ffe9e9", bg=RED_SCREEN,
        ).place(relx=0.5, rely=0.7, anchor="center")

        # Bind clicks on the main frame and the center panel so the
        # player can click basically anywhere on the game screen
        self.game_frame.bind("<Button-1>", self._on_click)
        center_panel.bind("<Button-1>", self._on_click)
        self.game_label.bind("<Button-1>", self._on_click)
        for child in center_panel.winfo_children():
            child.bind("<Button-1>", self._on_click)

    def _set_game_colour(self, bg: str, text: str) -> None:
        """Update the game screen colours and the main message text"""
        if self.game_frame is not None:
            self.game_frame.config(bg=bg)
        if self.game_label is not None:
            self.game_label.config(bg=bg, text=text)
            parent = self.game_label.master
            if isinstance(parent, tk.Frame):
                parent.config(bg=bg)
                for child in parent.winfo_children():
                    if isinstance(child, tk.Label):
                        child.config(bg=bg)
        if self.game_hint_label is not None:
            hint = "Wait for green"
            if bg == GREEN_SCREEN:
                hint = "Click now"
            elif bg == ORANGE_SCREEN:
                hint = "Penalty applied"
            self.game_hint_label.config(text=hint)

    def _on_click(self, _event: object = None) -> None:
        """Handle a click on the reaction screen"""
        if self.round_state == "red":
            self.round_state = "penalized"
            self._set_game_colour(ORANGE_SCREEN, "Penalty: Too soon!")
            send_message(self.sock, make_message(
                MSG_CLICK, early=True, round_number=self.current_round))

        elif self.round_state == "green":
            self.round_state = "clicked"
            self._set_game_colour(GREEN_SCREEN, "Clicked!  Waiting \u2026")
            send_message(self.sock, make_message(
                MSG_CLICK, early=False, round_number=self.current_round))

    # Result screens
    def _show_round_result(self, data: dict) -> None:
        """Show the round result screen and the current leaderboard"""
        self._clear()
        self.round_state = "idle"

        rnd   = data.get("round_number", "?")
        total = data.get("total_rounds", self.total_rounds)

        self.container.config(bg=RESULT_BG)
        outer = tk.Frame(self.container, bg=RESULT_BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=26, pady=22)
        self._current_screen = outer

        tk.Label(
            outer, text=f"Round {rnd} of {total}",
            font=("Helvetica", 15, "bold"), fg=GOLD, bg=RESULT_BG,
        ).pack(anchor="w")
        tk.Label(
            outer, text="Results",
            font=("Helvetica", 30, "bold"), fg=FG_WHITE, bg=RESULT_BG,
        ).pack(anchor="w", pady=(4, 16))

        results_panel = self._make_panel(outer, bg=BG_CARD, padx=18, pady=18)
        results_panel.pack(fill=tk.X)
        table = self._panel_inner(results_panel)

        tk.Label(
            table, text="Round Standings",
            font=("Helvetica", 16, "bold"), fg=FG_WHITE, bg=BG_CARD,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        for c, header in enumerate(["Player", "Reaction", "Score"]):
            tk.Label(
                table, text=header, font=("Helvetica", 12, "bold"),
                fg=GOLD, bg=BG_CARD, width=16,
            ).grid(row=1, column=c, padx=4, pady=2)

        for i, r in enumerate(data.get("results", []), start=2):
            if r["false_start"]:
                rt_text = "FALSE START"
            elif r["timed_out"]:
                rt_text = "TIMED OUT"
            else:
                rt_text = format_ms(r["reaction_time_ms"])

            for c, val in enumerate([r["player_name"], rt_text, str(r["score"])]):
                cell_bg = BG_CARD_ALT if i % 2 == 0 else BG_CARD
                tk.Label(
                    table, text=val, font=("Helvetica", 12),
                    fg=FG_WHITE, bg=cell_bg, width=16,
                ).grid(row=i, column=c, padx=4, pady=1)

        leaderboard_panel = self._make_panel(outer, bg=BG_PANEL, padx=18, pady=18)
        leaderboard_panel.pack(fill=tk.X, pady=(16, 0))
        lb_frame = self._panel_inner(leaderboard_panel)

        tk.Label(
            lb_frame, text="Leaderboard",
            font=("Helvetica", 16, "bold"), fg=FG_WHITE, bg=BG_PANEL,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        for c, header in enumerate(["#", "Player", "Total Score", "Total Time"]):
            tk.Label(
                lb_frame, text=header, font=("Helvetica", 11, "bold"),
                fg=GOLD, bg=BG_PANEL, width=14,
            ).grid(row=1, column=c, padx=3, pady=2)

        for i, s in enumerate(data.get("leaderboard", []), start=2):
            vals = [
                str(i - 1),
                s["player_name"],
                str(s["total_score"]),
                format_ms(s["total_reaction_time_ms"]),
            ]
            for c, v in enumerate(vals):
                cell_bg = BG_PANEL if i % 2 == 0 else BG_ACCENT
                tk.Label(
                    lb_frame, text=v, font=("Helvetica", 11),
                    fg=FG_WHITE, bg=cell_bg, width=14,
                ).grid(row=i, column=c, padx=3, pady=1)

        tk.Label(
            outer, text="Next round starting soon \u2026",
            font=("Helvetica", 12, "italic"), fg=FG_LIGHT, bg=RESULT_BG,
        ).pack(anchor="w", pady=(16, 0))

        message, colour = self._get_round_feedback(data)
        self._show_overlay_message(message, colour)

    def _show_game_over(self, data: dict) -> None:
        """Show the final results screen"""
        self._clear()
        self.round_state = "idle"

        outer = tk.Frame(self.container, bg=BG_DARK)
        outer.pack(fill=tk.BOTH, expand=True, padx=30, pady=28)
        self._current_screen = outer

        tk.Label(
            outer, text="Game Over",
            font=("Helvetica", 16, "bold"), fg=GOLD, bg=BG_DARK,
        ).pack(anchor="w")
        tk.Label(
            outer, text="Final Results",
            font=("Helvetica", 32, "bold"), fg=FG_WHITE, bg=BG_DARK,
        ).pack(anchor="w", pady=(4, 18))

        winner = data.get("winner", "???")
        winner_panel = self._make_panel(outer, bg=BG_PANEL, padx=22, pady=20)
        winner_panel.pack(fill=tk.X)
        winner_inner = self._panel_inner(winner_panel)
        tk.Label(
            winner_inner, text="Champion",
            font=("Helvetica", 13, "bold"), fg=GOLD, bg=BG_PANEL,
        ).pack(anchor="w")
        tk.Label(
            winner_inner, text=winner,
            font=("Helvetica", 26, "bold"), fg="#7CFFB2", bg=BG_PANEL,
        ).pack(anchor="w", pady=(6, 0))

        leaderboard_panel = self._make_panel(outer, bg=BG_CARD, padx=18, pady=18)
        leaderboard_panel.pack(fill=tk.X, pady=(16, 0))
        lb_frame = self._panel_inner(leaderboard_panel)

        for c, header in enumerate(["Rank", "Player", "Score", "Total Time"]):
            tk.Label(
                lb_frame, text=header, font=("Helvetica", 12, "bold"),
                fg=GOLD, bg=BG_CARD, width=14,
            ).grid(row=0, column=c, padx=5, pady=5)

        for entry in data.get("final_leaderboard", []):
            r = entry["rank"]
            vals = [
                f"#{r}",
                entry["player_name"],
                str(entry["total_score"]),
                format_ms(entry["total_reaction_time_ms"]),
            ]
            for c, v in enumerate(vals):
                cell_bg = BG_CARD_ALT if r % 2 == 1 else BG_CARD
                tk.Label(
                    lb_frame, text=v, font=("Helvetica", 12),
                    fg=FG_WHITE, bg=cell_bg, width=14,
                ).grid(row=r, column=c, padx=5, pady=3)

        self._make_button(
            outer,
            text="Quit",
            width=14,
            command=self._on_closing,
        ).pack(anchor="w", pady=(20, 0))

        if data.get("winner") == self.player_name:
            self._show_overlay_message("You Win!", "#7CFFB2")
        else:
            self._show_overlay_message("You Lose!", "#ff7a7a")

    # Network message handling
    def _recv_loop(self, my_sock: socket.socket) -> None:
        """Receive server messages on a background thread"""
        buf = ""
        while self.running and self.sock is my_sock:
            msgs, buf = receive_messages(my_sock, buf)
            if msgs is None:
                # Only post a disconnect if this thread still belongs to
                # the current active socket
                if self.sock is my_sock:
                    self.msg_queue.put({"type": "_disconnected"})
                break
            for m in msgs:
                if self.sock is my_sock:
                    self.msg_queue.put(m)

    def _poll_queue(self) -> None:
        """Handle queued server messages on the Tkinter thread"""
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass

        if self.running:
            self.root.after(50, self._poll_queue)

    def _handle(self, msg: dict) -> None:
        """Route each server message to the matching UI handler"""
        t = msg.get("type", "")

        if   t == MSG_JOIN_RESPONSE: self._on_join_response(msg)
        elif t == MSG_LOBBY_UPDATE:  self._on_lobby_update(msg)
        elif t == MSG_GAME_START:    self._on_game_start(msg)
        elif t == MSG_ROUND_PREPARE: self._on_round_prepare(msg)
        elif t == MSG_ROUND_GO:      self._on_round_go(msg)
        elif t == MSG_PENALTY:       self._on_penalty(msg)
        elif t == MSG_ROUND_RESULT:  self._on_round_result(msg)
        elif t == MSG_GAME_OVER:     self._on_game_over(msg)
        elif t == MSG_ERROR:         self._on_error(msg)
        elif t == MSG_PLAYER_LEFT:   self._on_player_left(msg)
        elif t == MSG_DISCONNECT:    self._on_server_disconnect(msg)
        elif t == "_disconnected":   self._on_server_disconnect(msg)

    # Individual message handlers
    def _on_join_response(self, msg: dict) -> None:
        """Handle the result of the join request"""
        if msg.get("success"):
            self._show_lobby_screen()
        else:
            self.connected = False
            safe_close(self.sock)
            self.sock = None
            if self.connect_status_label is not None:
                self.connect_status_label.config(
                    text=msg.get("message", "Join rejected."), fg="#e74c3c")

    def _on_lobby_update(self, msg: dict) -> None:
        """Update the lobby player list and ready count"""
        players = msg.get("players", [])
        self._update_lobby_players(players)
        if self.lobby_status_label is not None:
            ready = sum(1 for p in players if p.get("ready"))
            self.lobby_status_label.config(
                text=f"{len(players)} player(s) connected  \u2014  "
                     f"{ready} ready")

    def _on_game_start(self, msg: dict) -> None:
        """Show the short game-start screen"""
        self.total_rounds = msg.get("total_rounds", 5)
        self._clear()
        splash = self._make_panel(self.container, bg=BG_PANEL, padx=28, pady=28)
        splash.place(relx=0.5, rely=0.5, anchor="center", width=420, height=220)
        self._current_screen = splash
        inner = self._panel_inner(splash)
        tk.Label(
            inner, text="Reaction Rush",
            font=("Helvetica", 16, "bold"), fg=GOLD, bg=BG_PANEL,
        ).pack(anchor="center")
        tk.Label(
            inner, text="Game starting \u2026",
            font=("Helvetica", 30, "bold"), fg=FG_WHITE, bg=BG_PANEL,
        ).pack(pady=(18, 10))
        tk.Label(
            inner,
            text=f"Get ready for {self.total_rounds} fast rounds.",
            font=("Helvetica", 12), fg=FG_LIGHT, bg=BG_PANEL,
        ).pack()

    def _on_round_prepare(self, msg: dict) -> None:
        """Switch into the red-screen state for a new round"""
        rnd   = msg.get("round_number", 1)
        total = msg.get("total_rounds", self.total_rounds)
        self._show_game_screen(rnd, total)

    def _on_round_go(self, _msg: dict) -> None:
        """Switch to the green-screen click state"""
        if self.round_state == "red":
            self.round_state = "green"
            self._set_game_colour(GREEN_SCREEN, "Click!")

    def _on_penalty(self, _msg: dict) -> None:
        """Show the penalty state after an early click"""
        if self.round_state != "penalized":
            self.round_state = "penalized"
            self._set_game_colour(ORANGE_SCREEN, "Penalty: Too soon!")

    def _on_round_result(self, msg: dict) -> None:
        """Show the round result screen"""
        self._show_round_result(msg)

    def _on_game_over(self, msg: dict) -> None:
        """Show the final game-over screen"""
        self._show_game_over(msg)

    def _on_error(self, msg: dict) -> None:
        """Show a server-side error message"""
        messagebox.showerror("Server Error", msg.get("message", "Unknown error."))

    def _on_player_left(self, msg: dict) -> None:
        """Update the UI when another player disconnects"""
        name = msg.get("player_name", "?")
        if self.lobby_status_label is not None:
            self.lobby_status_label.config(text=f"{name} disconnected.")
        elif self.round_info_label is not None:
            self.round_info_label.config(
                text=f"{name} left  \u2014  "
                     f"Round {self.current_round} of {self.total_rounds}")

    def _on_server_disconnect(self, _msg: dict) -> None:
        """Handle a lost connection to the server"""
        if not self.connected:
            return
        self.connected = False
        messagebox.showinfo(
            "Disconnected", "Lost connection to the server.")
        self._show_connect_screen()

    # Closing / cleanup
    def _on_closing(self) -> None:
        """Close the client window and disconnect first"""
        self.running = False
        self.connected = False
        if self.sock is not None:
            send_message(self.sock, make_message(
                MSG_DISCONNECT, message="Client quit."))
            safe_close(self.sock)
        self.root.destroy()

if __name__ == "__main__":
    ReactionRushClient().run()
