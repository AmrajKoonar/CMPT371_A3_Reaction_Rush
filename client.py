"""
client.py — Tkinter GUI client for Reaction Rush.

Responsibilities
----------------
* Connect to the game server via TCP.
* Present a lobby where players can see who else has joined and ready up.
* Display the reaction-time game: red screen → green screen → click!
* Detect early clicks (false starts) and show the orange penalty screen.
* Show per-round results, a running leaderboard, and the final winner.
* Handle server disconnects and allow the player to quit cleanly.

Usage
-----
    python client.py

Architecture
------------
* **Main (Tk) thread** — owns every widget; never touches the socket
  directly (except for ``send_message`` which is a quick, non-blocking
  ``sendall`` call).
* **Receiver thread** — loops on ``receive_messages()`` and pushes parsed
  dicts into a ``queue.Queue``.
* **Queue poller** — a ``root.after()`` callback that drains the queue
  every 50 ms and dispatches messages to handler methods on the main
  thread, keeping Tkinter happy.
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

# ============================================================================
# Colour palette — keeps the UI consistent and easy to tweak
# ============================================================================
BG_DARK    = "#1a1a2e"    # window / connect-screen background
BG_PANEL   = "#16213e"    # lobby card background
BG_ACCENT  = "#0f3460"    # info-bar strip
FG_LIGHT   = "#e0e0e0"    # secondary text
FG_WHITE   = "#ffffff"    # primary text
BTN_BLUE   = "#3498db"    # default button
BTN_GREEN  = "#2ecc71"    # ready button
RED_SCREEN = "#e74c3c"    # reaction "wait" phase
GREEN_SCREEN = "#27ae60"  # reaction "click!" phase
ORANGE_SCREEN = "#e67e22" # false-start penalty
RESULT_BG  = "#2c3e50"    # round-result / leaderboard panel


# ============================================================================
# Client application
# ============================================================================

class ReactionRushClient:
    """Tkinter-based GUI client for the Reaction Rush multiplayer game."""

    # -----------------------------------------------------------------------
    # Initialisation
    # -----------------------------------------------------------------------

    def __init__(self) -> None:
        # -- Tk root --
        self.root = tk.Tk()
        self.root.title("Reaction Rush")
        self.root.geometry("820x620")
        self.root.minsize(640, 480)
        self.root.configure(bg=BG_DARK)

        # -- Network state --
        self.sock: Optional[socket.socket] = None
        self.connected: bool = False
        self.running: bool = True
        self.msg_queue: queue.Queue = queue.Queue()

        # -- Game state --
        self.player_name: str = ""
        self.current_round: int = 0
        self.total_rounds: int = 5
        # Round-phase state machine: idle → red → green/penalized → clicked → idle
        self.round_state: str = "idle"

        # -- Main container (screens are packed inside this) --
        self.container = tk.Frame(self.root, bg=BG_DARK)
        self.container.pack(fill=tk.BOTH, expand=True)

        # -- Widget references (set during screen creation) --
        self.game_frame: Optional[tk.Frame] = None
        self.game_label: Optional[tk.Label] = None
        self.round_info_label: Optional[tk.Label] = None
        self.lobby_players_frame: Optional[tk.Frame] = None
        self.lobby_status_label: Optional[tk.Label] = None
        self.connect_status_label: Optional[tk.Label] = None
        self._ready_btn: Optional[tk.Button] = None
        self._entries: list = []

        # -- Draw the first screen --
        self._show_connect_screen()

        # -- Start the queue-polling loop --
        self._poll_queue()

        # -- Handle the window close button --
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def run(self) -> None:
        """Enter the Tkinter main loop (blocks until the window closes)."""
        self.root.mainloop()

    # -----------------------------------------------------------------------
    # Screen helpers
    # -----------------------------------------------------------------------

    def _clear(self) -> None:
        """Destroy every widget inside the container frame."""
        for w in self.container.winfo_children():
            w.destroy()
        # Reset widget references
        self.game_frame = None
        self.game_label = None
        self.round_info_label = None
        self.lobby_players_frame = None
        self.lobby_status_label = None
        self.connect_status_label = None
        self._ready_btn = None

    def _make_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        width: int,
    ) -> tk.Button:
        """Create a button with clearer borders and text on macOS."""
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

    # -----------------------------------------------------------------------
    # Connect screen
    # -----------------------------------------------------------------------

    def _show_connect_screen(self) -> None:
        """Render the server-connection form."""
        self._clear()

        frame = tk.Frame(self.container, bg=BG_DARK)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        # Title
        tk.Label(
            frame, text="Reaction Rush",
            font=("Helvetica", 28, "bold"), fg=FG_WHITE, bg=BG_DARK,
        ).grid(row=0, column=0, columnspan=2, pady=(0, 5))

        tk.Label(
            frame, text="A TCP Multiplayer Reaction Game",
            font=("Helvetica", 11), fg=FG_LIGHT, bg=BG_DARK,
        ).grid(row=1, column=0, columnspan=2, pady=(0, 20))

        # Form fields: label + entry
        labels   = ["Host:", "Port:", "Access Code:", "Player Name:"]
        defaults = ["127.0.0.1", "5000", "RED123", ""]
        self._entries = []

        for i, (lbl, default) in enumerate(zip(labels, defaults)):
            tk.Label(
                frame, text=lbl, font=("Helvetica", 12),
                fg=FG_LIGHT, bg=BG_DARK,
            ).grid(row=i + 2, column=0, sticky="e", padx=5, pady=4)

            entry = tk.Entry(frame, font=("Helvetica", 12), width=22)
            entry.insert(0, default)
            entry.grid(row=i + 2, column=1, padx=5, pady=4)
            # Press Enter in any field → connect
            entry.bind("<Return>", lambda _e: self._do_connect())
            self._entries.append(entry)

        # Connect button
        self._make_button(
            frame,
            text="Connect",
            width=18,
            command=self._do_connect,
        ).grid(row=len(labels) + 2, column=0, columnspan=2, pady=(15, 5))

        # Status message (errors, "Connecting…", etc.)
        self.connect_status_label = tk.Label(
            frame, text="", font=("Helvetica", 11),
            fg="#e74c3c", bg=BG_DARK,
        )
        self.connect_status_label.grid(
            row=len(labels) + 3, column=0, columnspan=2,
        )

        # Focus the name field since the others have defaults
        self._entries[3].focus_set()

    def _do_connect(self) -> None:
        """Validate form, open a TCP socket, and send a join request."""
        host = self._entries[0].get().strip()
        port_str = self._entries[1].get().strip()
        code = self._entries[2].get().strip()
        name = self._entries[3].get().strip()

        # --- Input validation ---
        if not host or not port_str or not code or not name:
            self.connect_status_label.config(text="All fields are required.")
            return
        try:
            port = int(port_str)
        except ValueError:
            self.connect_status_label.config(text="Port must be a number.")
            return

        # --- Tear down any previous connection ---
        self.connected = False
        if self.sock is not None:
            safe_close(self.sock)
            self.sock = None

        # Drain stale messages that belong to an old session
        while not self.msg_queue.empty():
            try:
                self.msg_queue.get_nowait()
            except queue.Empty:
                break

        self.connect_status_label.config(text="Connecting …", fg="#f1c40f")
        self.root.update_idletasks()

        # --- Open TCP connection ---
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)       # connection timeout
            self.sock.connect((host, port))
            self.sock.settimeout(1.0)       # recv timeout for the reader loop
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            self.connect_status_label.config(
                text=f"Connection failed: {exc}", fg="#e74c3c")
            self.sock = None
            return

        self.connected = True
        self.player_name = name

        # Capture the socket reference so the receiver thread can detect
        # when this session has been superseded by a new _do_connect call.
        my_sock = self.sock
        threading.Thread(
            target=self._recv_loop, args=(my_sock,), daemon=True,
        ).start()

        # Ask the server to let us in
        send_message(self.sock, make_message(
            MSG_JOIN_REQUEST, player_name=name, access_code=code))

    # -----------------------------------------------------------------------
    # Lobby screen
    # -----------------------------------------------------------------------

    def _show_lobby_screen(self) -> None:
        """Render the lobby: player list, ready button, status bar."""
        self._clear()

        # -- Header --
        top = tk.Frame(self.container, bg=BG_DARK)
        top.pack(fill=tk.X, padx=20, pady=(20, 10))

        tk.Label(
            top, text="Lobby", font=("Helvetica", 22, "bold"),
            fg=FG_WHITE, bg=BG_DARK,
        ).pack()

        self.lobby_status_label = tk.Label(
            top, text="Waiting for players …",
            font=("Helvetica", 12), fg=FG_LIGHT, bg=BG_DARK,
        )
        self.lobby_status_label.pack(pady=5)

        # -- Player list panel --
        mid = tk.Frame(self.container, bg=BG_PANEL, bd=2, relief="groove")
        mid.pack(fill=tk.BOTH, expand=True, padx=40, pady=10)

        tk.Label(
            mid, text="Players", font=("Helvetica", 14, "bold"),
            fg=FG_WHITE, bg=BG_PANEL,
        ).pack(pady=(10, 5))

        self.lobby_players_frame = tk.Frame(mid, bg=BG_PANEL)
        self.lobby_players_frame.pack(
            fill=tk.BOTH, expand=True, padx=20, pady=5,
        )

        # -- Ready button --
        bottom = tk.Frame(self.container, bg=BG_DARK)
        bottom.pack(fill=tk.X, padx=20, pady=(5, 20))

        self._ready_btn = self._make_button(
            bottom,
            text="Ready",
            width=14,
            command=self._do_ready,
        )
        self._ready_btn.pack()

    def _do_ready(self) -> None:
        """Notify the server that this player is ready to play."""
        send_message(self.sock, make_message(MSG_READY))
        if self._ready_btn is not None:
            self._ready_btn.config(state="disabled", text="Ready  \u2713")

    def _update_lobby_players(self, players: list) -> None:
        """Refresh the player-list widget with the latest data."""
        if self.lobby_players_frame is None:
            return

        for w in self.lobby_players_frame.winfo_children():
            w.destroy()

        for p in players:
            status = "Ready" if p["ready"] else "Waiting …"
            colour = "#2ecc71" if p["ready"] else "#f39c12"

            row = tk.Frame(self.lobby_players_frame, bg=BG_PANEL)
            row.pack(fill=tk.X, pady=2)

            tk.Label(
                row, text=p["name"], font=("Helvetica", 13),
                fg=FG_WHITE, bg=BG_PANEL, anchor="w",
            ).pack(side=tk.LEFT, padx=10)

            tk.Label(
                row, text=status, font=("Helvetica", 12, "bold"),
                fg=colour, bg=BG_PANEL, anchor="e",
            ).pack(side=tk.RIGHT, padx=10)

    # -----------------------------------------------------------------------
    # Game screen (reaction area)
    # -----------------------------------------------------------------------

    def _show_game_screen(self, round_num: int, total: int) -> None:
        """
        Prepare the reaction-game canvas for a new round.

        The canvas fills the window with a solid colour (red, green, or
        orange) and displays a large centred instruction label.
        Clicking anywhere on the canvas triggers ``_on_click``.
        """
        self._clear()
        self.current_round = round_num
        self.total_rounds = total
        self.round_state = "red"

        # Info bar at the top
        info = tk.Frame(self.container, bg=BG_ACCENT, height=40)
        info.pack(fill=tk.X)
        info.pack_propagate(False)

        self.round_info_label = tk.Label(
            info, text=f"Round {round_num} of {total}",
            font=("Helvetica", 14, "bold"), fg=FG_WHITE, bg=BG_ACCENT,
        )
        self.round_info_label.pack(expand=True)

        # Game area — a coloured frame with a centred label
        self.game_frame = tk.Frame(self.container, bg=RED_SCREEN)
        self.game_frame.pack(fill=tk.BOTH, expand=True)

        self.game_label = tk.Label(
            self.game_frame, text="Wait for green \u2026",
            font=("Helvetica", 52, "bold"), fg=FG_WHITE, bg=RED_SCREEN,
        )
        self.game_label.place(relx=0.5, rely=0.5, anchor="center")

        # Bind click on BOTH the frame and the label so clicking
        # anywhere in the game area is detected
        self.game_frame.bind("<Button-1>", self._on_click)
        self.game_label.bind("<Button-1>", self._on_click)

    def _set_game_colour(self, bg: str, text: str) -> None:
        """Change the game area's background colour and centre text."""
        if self.game_frame is not None:
            self.game_frame.config(bg=bg)
        if self.game_label is not None:
            self.game_label.config(bg=bg, text=text)

    def _on_click(self, _event: object = None) -> None:
        """
        Handle a mouse click on the game area.

        * During the **red** phase → false start (penalty).
        * During the **green** phase → valid reaction click.
        * Any other state → ignore.
        """
        if self.round_state == "red":
            # Player clicked too early — show penalty locally and inform server
            self.round_state = "penalized"
            self._set_game_colour(ORANGE_SCREEN, "Penalty: Too soon!")
            send_message(self.sock, make_message(
                MSG_CLICK, early=True, round_number=self.current_round))

        elif self.round_state == "green":
            # Valid click!
            self.round_state = "clicked"
            self._set_game_colour(GREEN_SCREEN, "Clicked!  Waiting \u2026")
            send_message(self.sock, make_message(
                MSG_CLICK, early=False, round_number=self.current_round))

    # -----------------------------------------------------------------------
    # Round-result screen
    # -----------------------------------------------------------------------

    def _show_round_result(self, data: dict) -> None:
        """Display per-round scores and the current leaderboard."""
        self._clear()
        self.round_state = "idle"

        rnd   = data.get("round_number", "?")
        total = data.get("total_rounds", self.total_rounds)

        # Outer coloured canvas
        bg_canvas = tk.Canvas(self.container, bg=RESULT_BG, highlightthickness=0)
        bg_canvas.pack(fill=tk.BOTH, expand=True)

        inner = tk.Frame(bg_canvas, bg=RESULT_BG)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        # -- Heading --
        tk.Label(
            inner, text=f"Round {rnd} of {total}  \u2014  Results",
            font=("Helvetica", 20, "bold"), fg=FG_WHITE, bg=RESULT_BG,
        ).pack(pady=(0, 15))

        # -- Results table --
        table = tk.Frame(inner, bg=RESULT_BG)
        table.pack()

        for c, header in enumerate(["Player", "Reaction", "Score"]):
            tk.Label(
                table, text=header, font=("Helvetica", 12, "bold"),
                fg="#f1c40f", bg=RESULT_BG, width=16,
            ).grid(row=0, column=c, padx=4, pady=2)

        for i, r in enumerate(data.get("results", []), start=1):
            if r["false_start"]:
                rt_text = "FALSE START"
            elif r["timed_out"]:
                rt_text = "TIMED OUT"
            else:
                rt_text = format_ms(r["reaction_time_ms"])

            for c, val in enumerate([r["player_name"], rt_text, str(r["score"])]):
                tk.Label(
                    table, text=val, font=("Helvetica", 12),
                    fg=FG_WHITE, bg=RESULT_BG, width=16,
                ).grid(row=i, column=c, padx=4, pady=1)

        # -- Leaderboard --
        tk.Label(
            inner, text="Leaderboard",
            font=("Helvetica", 16, "bold"), fg="#f1c40f", bg=RESULT_BG,
        ).pack(pady=(20, 5))

        lb_frame = tk.Frame(inner, bg=RESULT_BG)
        lb_frame.pack()

        for c, header in enumerate(["#", "Player", "Total Score", "Total Time"]):
            tk.Label(
                lb_frame, text=header, font=("Helvetica", 11, "bold"),
                fg="#f1c40f", bg=RESULT_BG, width=14,
            ).grid(row=0, column=c, padx=3, pady=2)

        for i, s in enumerate(data.get("leaderboard", []), start=1):
            vals = [
                str(i),
                s["player_name"],
                str(s["total_score"]),
                format_ms(s["total_reaction_time_ms"]),
            ]
            for c, v in enumerate(vals):
                tk.Label(
                    lb_frame, text=v, font=("Helvetica", 11),
                    fg=FG_WHITE, bg=RESULT_BG, width=14,
                ).grid(row=i, column=c, padx=3, pady=1)

        # -- Next-round hint --
        tk.Label(
            inner, text="Next round starting soon \u2026",
            font=("Helvetica", 12, "italic"), fg=FG_LIGHT, bg=RESULT_BG,
        ).pack(pady=(15, 0))

    # -----------------------------------------------------------------------
    # Game-over screen
    # -----------------------------------------------------------------------

    def _show_game_over(self, data: dict) -> None:
        """Show the final leaderboard, winner, and a Quit button."""
        self._clear()
        self.round_state = "idle"

        frame = tk.Frame(self.container, bg=BG_DARK)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            frame, text="Game Over!",
            font=("Helvetica", 30, "bold"), fg="#f1c40f", bg=BG_DARK,
        ).pack(pady=(0, 10))

        winner = data.get("winner", "???")
        tk.Label(
            frame, text=f"Winner:  {winner}",
            font=("Helvetica", 22, "bold"), fg="#2ecc71", bg=BG_DARK,
        ).pack(pady=(0, 20))

        # -- Final leaderboard --
        lb_frame = tk.Frame(frame, bg=BG_PANEL, bd=2, relief="groove")
        lb_frame.pack(padx=20, pady=10)

        for c, header in enumerate(["Rank", "Player", "Score", "Total Time"]):
            tk.Label(
                lb_frame, text=header, font=("Helvetica", 12, "bold"),
                fg="#f1c40f", bg=BG_PANEL, width=14,
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
                tk.Label(
                    lb_frame, text=v, font=("Helvetica", 12),
                    fg=FG_WHITE, bg=BG_PANEL, width=14,
                ).grid(row=r, column=c, padx=5, pady=3)

        # -- Quit button --
        self._make_button(
            frame,
            text="Quit",
            width=14,
            command=self._on_closing,
        ).pack(pady=(20, 0))

    # -----------------------------------------------------------------------
    # Network: receiver thread + queue polling
    # -----------------------------------------------------------------------

    def _recv_loop(self, my_sock: socket.socket) -> None:
        """
        Background thread: read messages from *my_sock* into the queue.

        *my_sock* is the socket that was current when this thread was
        spawned.  If the user reconnects (creating a new socket), this
        thread detects the mismatch and exits silently, preventing stale
        messages from polluting the new session.
        """
        buf = ""
        while self.running and self.sock is my_sock:
            msgs, buf = receive_messages(my_sock, buf)
            if msgs is None:
                # Connection lost — only notify if we're still the active session
                if self.sock is my_sock:
                    self.msg_queue.put({"type": "_disconnected"})
                break
            for m in msgs:
                if self.sock is my_sock:
                    self.msg_queue.put(m)

    def _poll_queue(self) -> None:
        """
        Drain the message queue and dispatch each item (runs on Tk thread).

        Scheduled every 50 ms via ``root.after``.
        """
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass

        if self.running:
            self.root.after(50, self._poll_queue)

    # -----------------------------------------------------------------------
    # Message dispatch
    # -----------------------------------------------------------------------

    def _handle(self, msg: dict) -> None:
        """Route a server message to the appropriate handler."""
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

    # -- individual handlers ------------------------------------------------

    def _on_join_response(self, msg: dict) -> None:
        if msg.get("success"):
            self._show_lobby_screen()
        else:
            # Rejected — close this connection so the user can retry
            self.connected = False
            safe_close(self.sock)
            self.sock = None
            if self.connect_status_label is not None:
                self.connect_status_label.config(
                    text=msg.get("message", "Join rejected."), fg="#e74c3c")

    def _on_lobby_update(self, msg: dict) -> None:
        players = msg.get("players", [])
        self._update_lobby_players(players)
        if self.lobby_status_label is not None:
            ready = sum(1 for p in players if p.get("ready"))
            self.lobby_status_label.config(
                text=f"{len(players)} player(s) connected  \u2014  "
                     f"{ready} ready")

    def _on_game_start(self, msg: dict) -> None:
        self.total_rounds = msg.get("total_rounds", 5)
        self._clear()
        tk.Label(
            self.container, text="Game starting \u2026",
            font=("Helvetica", 32, "bold"), fg=FG_WHITE, bg=BG_DARK,
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _on_round_prepare(self, msg: dict) -> None:
        rnd   = msg.get("round_number", 1)
        total = msg.get("total_rounds", self.total_rounds)
        self._show_game_screen(rnd, total)

    def _on_round_go(self, _msg: dict) -> None:
        # Only switch to green if the player hasn't already false-started
        if self.round_state == "red":
            self.round_state = "green"
            self._set_game_colour(GREEN_SCREEN, "Click!")

    def _on_penalty(self, _msg: dict) -> None:
        # Server confirmation of a false start
        if self.round_state != "penalized":
            self.round_state = "penalized"
            self._set_game_colour(ORANGE_SCREEN, "Penalty: Too soon!")

    def _on_round_result(self, msg: dict) -> None:
        self._show_round_result(msg)

    def _on_game_over(self, msg: dict) -> None:
        self._show_game_over(msg)

    def _on_error(self, msg: dict) -> None:
        messagebox.showerror("Server Error", msg.get("message", "Unknown error."))

    def _on_player_left(self, msg: dict) -> None:
        name = msg.get("player_name", "?")
        if self.lobby_status_label is not None:
            self.lobby_status_label.config(text=f"{name} disconnected.")
        elif self.round_info_label is not None:
            self.round_info_label.config(
                text=f"{name} left  \u2014  "
                     f"Round {self.current_round} of {self.total_rounds}")

    def _on_server_disconnect(self, _msg: dict) -> None:
        # Guard: if we already intentionally closed (e.g. rejected join),
        # don't show the popup.
        if not self.connected:
            return
        self.connected = False
        messagebox.showinfo(
            "Disconnected", "Lost connection to the server.")
        self._show_connect_screen()

    # -----------------------------------------------------------------------
    # Clean-up
    # -----------------------------------------------------------------------

    def _on_closing(self) -> None:
        """Handle the window ✕ button: disconnect and destroy."""
        self.running = False
        self.connected = False
        if self.sock is not None:
            send_message(self.sock, make_message(
                MSG_DISCONNECT, message="Client quit."))
            safe_close(self.sock)
        self.root.destroy()


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    ReactionRushClient().run()
