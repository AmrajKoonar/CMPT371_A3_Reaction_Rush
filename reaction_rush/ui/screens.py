"""
screens.py — Screen builders for the Tkinter client.

Each ``build_*`` method clears the app container and renders one screen using
the themed :mod:`components`. Screens are intentionally "dumb": they read
state from the app and call ``app.action_*`` / ``app.go_*`` methods for
behaviour, keeping all networking and navigation logic in ``client_app.py``.

The reaction game screen and the animated overlay live here too, ported from
the polished v1 client and adapted to the theme system.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import List

from .. import constants as C
from ..utils import format_ms
from . import components as ui
from . import theme as T


class ScreenManager:
    """Builds and manages the client's screens."""

    def __init__(self, app) -> None:
        self.app = app

    # -- convenience --------------------------------------------------------
    @property
    def p(self) -> dict:
        """Active palette."""
        return self.app.palette

    @property
    def container(self) -> tk.Frame:
        return self.app.container

    def _clear(self) -> None:
        """Destroy current widgets and reset transient refs + overlays."""
        self.app.cancel_overlay()
        self.container.config(bg=self.p["bg"])
        for w in self.container.winfo_children():
            w.destroy()
        self.app.reset_screen_refs()

    def _header(self, parent, kicker: str, title: str) -> None:
        """Standard screen header: small kicker + big title."""
        ui.label(parent, kicker, self.p, size=13, bold=True,
                 fg=self.p["gold"], bg=parent.cget("bg")).pack(anchor="w")
        ui.label(parent, title, self.p, size=30, bold=True,
                 bg=parent.cget("bg")).pack(anchor="w", pady=(2, 16))

    # =======================================================================
    # Landing
    # =======================================================================

    def build_landing(self) -> None:
        self._clear()
        outer = tk.Frame(self.container, bg=self.p["bg"])
        outer.place(relx=0.5, rely=0.5, anchor="center")
        self.app.current_screen = outer

        ui.label(outer, "Reaction Rush", self.p, size=40, bold=True,
                 bg=self.p["bg"]).pack()
        ui.label(outer, "Multiplayer TCP reaction battle", self.p,
                 size=14, muted=True, bg=self.p["bg"]).pack(pady=(6, 4))
        ui.label(outer, f"v{self.app.version}", self.p, size=10, muted=True,
                 bg=self.p["bg"]).pack(pady=(0, 22))

        btns = tk.Frame(outer, bg=self.p["bg"])
        btns.pack()
        ui.button(btns, "Join Game", self.app.go_join, self.p,
                  kind="primary", width=22).pack(pady=5)
        ui.button(btns, "Create Room", self.app.go_create, self.p,
                  kind="success", width=22).pack(pady=5)
        ui.button(btns, "Practice Mode", self.app.go_practice, self.p,
                  kind="ghost", width=22).pack(pady=5)
        ui.button(btns, "Settings", self.app.go_settings, self.p,
                  kind="ghost", width=22).pack(pady=5)

    # =======================================================================
    # Join
    # =======================================================================

    def build_join(self) -> None:
        self._clear()
        outer = tk.Frame(self.container, bg=self.p["bg"])
        outer.place(relx=0.5, rely=0.5, anchor="center")
        self.app.current_screen = outer

        self._header(outer, "CONNECT", "Join a Game")

        cardf = ui.card(outer, self.p, padx=26, pady=24)
        cardf.pack()
        f = ui.inner_of(cardf)

        s = self.app.settings
        rows = [
            ("Host:", str(s.default_host)),
            ("Port:", str(s.default_port)),
            ("Room Code:", ""),
            ("Access Code:", C.DEFAULT_ACCESS_CODE),
            ("Player Name:", s.player_name),
        ]
        entries: List[tk.Entry] = []
        for i, (lbl, default) in enumerate(rows):
            ui.label(f, lbl, self.p, size=12, bg=self.p["surface"]).grid(
                row=i, column=0, sticky="e", padx=(0, 12), pady=7)
            e = ui.entry(f, self.p)
            e.insert(0, default)
            e.grid(row=i, column=1, pady=7, ipady=6)
            entries.append(e)

        ui.label(f, "Leave Room Code blank to use the default room.",
                 self.p, size=10, muted=True, bg=self.p["surface"]).grid(
            row=len(rows), column=0, columnspan=2, pady=(2, 8))

        status = ui.label(f, "", self.p, size=11, fg=self.p["danger"],
                          bg=self.p["surface"])
        status.grid(row=len(rows) + 2, column=0, columnspan=2)
        self.app.status_label = status

        def do_connect() -> None:
            self.app.action_join(
                host=entries[0].get().strip(),
                port=entries[1].get().strip(),
                room_code=entries[2].get().strip(),
                access_code=entries[3].get().strip(),
                name=entries[4].get().strip(),
            )

        for e in entries:
            e.bind("<Return>", lambda _e: do_connect())

        btnrow = tk.Frame(f, bg=self.p["surface"])
        btnrow.grid(row=len(rows) + 1, column=0, columnspan=2, pady=(14, 6))
        ui.button(btnrow, "Connect", do_connect, self.p, width=16).pack(
            side=tk.LEFT, padx=4)
        ui.button(btnrow, "Back", self.app.go_landing, self.p, kind="ghost",
                  width=10).pack(side=tk.LEFT, padx=4)

        entries[4].focus_set()

    # =======================================================================
    # Create room
    # =======================================================================

    def build_create(self) -> None:
        self._clear()
        outer = tk.Frame(self.container, bg=self.p["bg"])
        outer.place(relx=0.5, rely=0.5, anchor="center")
        self.app.current_screen = outer

        self._header(outer, "HOST", "Create a Room")

        cardf = ui.card(outer, self.p, padx=26, pady=22)
        cardf.pack()
        f = ui.inner_of(cardf)

        s = self.app.settings
        host_var = tk.StringVar(value=str(s.default_host))
        port_var = tk.StringVar(value=str(s.default_port))
        name_var = tk.StringVar(value=s.player_name)
        mode_var = tk.StringVar(value=C.MODE_CLASSIC)
        rounds_var = tk.StringVar(value=str(C.DEFAULT_ROUNDS))
        minp_var = tk.StringVar(value=str(C.DEFAULT_MIN_PLAYERS))
        maxp_var = tk.StringVar(value=str(C.DEFAULT_MAX_PLAYERS))
        latency_var = tk.BooleanVar(value=True)
        bots_var = tk.BooleanVar(value=True)

        def add_row(r, lbl, widget):
            ui.label(f, lbl, self.p, size=12, bg=self.p["surface"]).grid(
                row=r, column=0, sticky="e", padx=(0, 12), pady=6)
            widget.grid(row=r, column=1, sticky="w", pady=6)

        e_host = ui.entry(f, self.p, width=22); e_host.insert(0, host_var.get())
        e_port = ui.entry(f, self.p, width=22); e_port.insert(0, port_var.get())
        e_name = ui.entry(f, self.p, width=22); e_name.insert(0, name_var.get())
        add_row(0, "Host:", e_host)
        add_row(1, "Port:", e_port)
        add_row(2, "Player Name:", e_name)
        add_row(3, "Game Mode:", ui.option_menu(f, mode_var, C.ALL_MODES, self.p))
        add_row(4, "Rounds:", ui.option_menu(
            f, rounds_var, [str(x) for x in (3, 5, 7, 10)], self.p))
        add_row(5, "Min Players:", ui.option_menu(
            f, minp_var, [str(x) for x in range(1, 9)], self.p))
        add_row(6, "Max Players:", ui.option_menu(
            f, maxp_var, [str(x) for x in range(2, 13)], self.p))

        cb1 = tk.Checkbutton(
            f, text="Latency compensation", variable=latency_var,
            font=T.font(11), bg=self.p["surface"], fg=self.p["text"],
            selectcolor=self.p["surface_alt"], activebackground=self.p["surface"],
            activeforeground=self.p["text"], highlightthickness=0, bd=0)
        cb2 = tk.Checkbutton(
            f, text="Allow bots", variable=bots_var,
            font=T.font(11), bg=self.p["surface"], fg=self.p["text"],
            selectcolor=self.p["surface_alt"], activebackground=self.p["surface"],
            activeforeground=self.p["text"], highlightthickness=0, bd=0)
        cb1.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        cb2.grid(row=8, column=0, columnspan=2, sticky="w")

        status = ui.label(f, "", self.p, size=11, fg=self.p["danger"],
                          bg=self.p["surface"])
        status.grid(row=10, column=0, columnspan=2)
        self.app.status_label = status

        def do_create() -> None:
            settings = {
                "mode": mode_var.get(),
                "rounds": int(rounds_var.get()),
                "min_players": int(minp_var.get()),
                "max_players": int(maxp_var.get()),
                "latency_compensation": bool(latency_var.get()),
                "allow_bots": bool(bots_var.get()),
            }
            self.app.action_create_room(
                host=e_host.get().strip(), port=e_port.get().strip(),
                name=e_name.get().strip(), settings=settings)

        btnrow = tk.Frame(f, bg=self.p["surface"])
        btnrow.grid(row=9, column=0, columnspan=2, pady=(14, 4))
        ui.button(btnrow, "Create Room", do_create, self.p, kind="success",
                  width=16).pack(side=tk.LEFT, padx=4)
        ui.button(btnrow, "Back", self.app.go_landing, self.p, kind="ghost",
                  width=10).pack(side=tk.LEFT, padx=4)

    # =======================================================================
    # Lobby
    # =======================================================================

    def build_lobby(self) -> None:
        self._clear()
        self.app.current_screen = self.container

        top = tk.Frame(self.container, bg=self.p["bg"])
        top.pack(fill=tk.X, padx=26, pady=(22, 10))

        ui.label(top, "Lobby", self.p, size=28, bold=True,
                 bg=self.p["bg"]).pack(side=tk.LEFT)

        code_frame = tk.Frame(top, bg=self.p["bg"])
        code_frame.pack(side=tk.RIGHT)
        ui.label(code_frame, "Room Code", self.p, size=10, muted=True,
                 bg=self.p["bg"]).pack(anchor="e")
        row = tk.Frame(code_frame, bg=self.p["bg"])
        row.pack(anchor="e")
        ui.label(row, self.app.room_code or "—", self.p, size=18, bold=True,
                 fg=self.p["gold"], bg=self.p["bg"]).pack(side=tk.LEFT, padx=(0, 6))
        ui.button(row, "Copy", self.app.action_copy_code, self.p,
                  kind="ghost", width=6).pack(side=tk.LEFT)

        self.app.status_label = ui.label(
            self.container, "Waiting for players …", self.p, size=12,
            muted=True, bg=self.p["bg"])
        self.app.status_label.pack(anchor="w", padx=26)

        mid = tk.Frame(self.container, bg=self.p["bg"])
        mid.pack(fill=tk.BOTH, expand=True, padx=26, pady=10)

        players_card = ui.card(mid, self.p, padx=20, pady=20)
        players_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 16))
        pc = ui.inner_of(players_card)
        ui.heading(pc, "Players", self.p, bg=self.p["surface"]).pack(anchor="w")
        ui.label(pc, "Everyone must be ready before the match starts.",
                 self.p, size=11, muted=True, bg=self.p["surface"]).pack(
            anchor="w", pady=(2, 12))
        self.app.lobby_players_frame = tk.Frame(pc, bg=self.p["surface"])
        self.app.lobby_players_frame.pack(fill=tk.BOTH, expand=True)

        side = ui.card(mid, self.p, bg=self.p["surface_alt"], padx=20, pady=20)
        side.config(width=250)
        side.pack(side=tk.LEFT, fill=tk.Y)
        sc = ui.inner_of(side)

        ui.heading(sc, "Match Settings", self.p, bg=self.p["surface_alt"]).pack(
            anchor="w")
        st = self.app.room_settings or {}
        summary = (
            f"Mode: {st.get('mode', C.MODE_CLASSIC)}\n"
            f"Rounds: {st.get('rounds', C.DEFAULT_ROUNDS)}\n"
            f"Players: {st.get('min_players', 2)}–{st.get('max_players', 8)}\n"
            f"Latency comp: {'on' if st.get('latency_compensation', True) else 'off'}"
        )
        ui.label(sc, summary, self.p, size=11, bg=self.p["surface_alt"]).pack(
            anchor="w", pady=(8, 14))

        # Host-only bot controls.
        if self.app.is_host and st.get("allow_bots", True):
            ui.label(sc, "Add a bot (host):", self.p, size=11, bold=True,
                     bg=self.p["surface_alt"]).pack(anchor="w")
            bot_var = tk.StringVar(value=C.BOT_AVERAGE)
            ui.option_menu(sc, bot_var, C.ALL_BOT_LEVELS, self.p).pack(
                anchor="w", pady=(4, 6))
            ui.button(sc, "Add Bot",
                      lambda: self.app.action_add_bot(bot_var.get()),
                      self.p, kind="ghost", width=14).pack(anchor="w",
                                                            pady=(0, 12))

        self.app.ready_btn = ui.button(
            sc, "Ready", self.app.action_ready, self.p, kind="success",
            width=16)
        self.app.ready_btn.pack(anchor="w", pady=(4, 6))
        ui.button(sc, "Leave Room", self.app.action_leave_room, self.p,
                  kind="danger", width=16).pack(anchor="w")

        self.refresh_lobby_players()

    def refresh_lobby_players(self) -> None:
        """Redraw the lobby player cards from ``app.lobby_players``."""
        frame = self.app.lobby_players_frame
        if frame is None or not frame.winfo_exists():
            return
        for w in frame.winfo_children():
            w.destroy()

        for pl in self.app.lobby_players:
            ready = pl.get("ready")
            is_bot = pl.get("is_bot")
            latency = pl.get("latency_ms", 0)

            row = tk.Frame(frame, bg=self.p["surface_alt"],
                           highlightthickness=1,
                           highlightbackground=self.p["stroke"])
            row.pack(fill=tk.X, pady=5, ipady=8)

            left = tk.Frame(row, bg=self.p["surface_alt"])
            left.pack(side=tk.LEFT, padx=10)
            name = pl.get("name", "?")
            if pl.get("is_host"):
                name += "  \u2605"
            ui.label(left, name, self.p, size=13, bg=self.p["surface_alt"]).pack(
                side=tk.LEFT)
            if is_bot:
                ui.pill(left, f"BOT · {pl.get('bot_level','')}", self.p,
                        colour=self.p["primary"]).pack(side=tk.LEFT, padx=8)

            right = tk.Frame(row, bg=self.p["surface_alt"])
            right.pack(side=tk.RIGHT, padx=10)
            if not is_bot and latency:
                ui.label(right, f"{latency:.0f} ms", self.p, size=10,
                         fg=ui.latency_colour(self.p, latency),
                         bg=self.p["surface_alt"]).pack(side=tk.RIGHT, padx=(8, 0))
            status = "Ready" if ready else "Waiting …"
            ui.label(right, status, self.p, size=12, bold=True,
                     fg=self.p["success"] if ready else self.p["warning"],
                     bg=self.p["surface_alt"]).pack(side=tk.RIGHT)

    # =======================================================================
    # Reaction game screen
    # =======================================================================

    def build_game(self, round_num: int, total: int) -> None:
        self._clear()
        self.app.current_round = round_num
        self.app.total_rounds = total
        self.app.round_state = "red"

        info = tk.Frame(self.container, bg=self.p["elevated"], height=58)
        info.pack(fill=tk.X, padx=18, pady=(16, 0))
        info.pack_propagate(False)

        self.app.round_info_label = ui.label(
            info, f"Round {round_num} of {total}", self.p, size=16, bold=True,
            bg=self.p["elevated"])
        self.app.round_info_label.pack(side=tk.LEFT, padx=18)

        self.app.game_hint_label = ui.label(
            info, "Wait for green", self.p, size=12, muted=True,
            bg=self.p["elevated"])
        self.app.game_hint_label.pack(side=tk.RIGHT, padx=18)

        frame = tk.Frame(self.container, bg=self.p["red"])
        frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=(12, 18))
        self.app.game_frame = frame
        self.app.current_screen = frame

        panel = tk.Frame(frame, bg=self.p["red"], bd=0, highlightthickness=3,
                         highlightbackground="#ffffff")
        panel.place(relx=0.5, rely=0.5, anchor="center",
                    relwidth=0.72, height=250)
        panel.bind("<Configure>", lambda _e: self.app.fit_game_label())
        self.app.game_panel = panel

        self.app.game_label_font = tkfont.Font(
            family=T.FONT_FAMILY, size=48, weight="bold")
        self.app.game_label = tk.Label(
            panel, text="Wait for green \u2026", font=self.app.game_label_font,
            fg="#ffffff", bg=self.p["red"])
        self.app.game_label.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(panel, text="Click anywhere once the screen changes.",
                 font=T.font(14), fg="#ffe9e9", bg=self.p["red"]).place(
            relx=0.5, rely=0.7, anchor="center")

        # Click anywhere in the game area.
        for w in (frame, panel, self.app.game_label):
            w.bind("<Button-1>", lambda _e: self.app.action_game_click())
        for child in panel.winfo_children():
            child.bind("<Button-1>", lambda _e: self.app.action_game_click())

    # =======================================================================
    # Round result
    # =======================================================================

    def build_round_result(self, data: dict) -> None:
        self._clear()
        self.app.round_state = "idle"
        rnd = data.get("round_number", "?")
        total = data.get("total_rounds", self.app.total_rounds)

        self.container.config(bg=self.p["bg"])
        outer = tk.Frame(self.container, bg=self.p["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=26, pady=20)
        self.app.current_screen = outer

        self._header(outer, f"ROUND {rnd} OF {total}", "Results")

        # Round standings
        card1 = ui.card(outer, self.p, padx=18, pady=16)
        card1.pack(fill=tk.X)
        t1 = ui.inner_of(card1)
        self._table(t1, ["Player", "Reaction", "Score"],
                    [self._round_row(r) for r in data.get("results", [])],
                    self.p["surface"])

        # Leaderboard
        card2 = ui.card(outer, self.p, bg=self.p["surface_alt"],
                        padx=18, pady=16)
        card2.pack(fill=tk.X, pady=(14, 0))
        t2 = ui.inner_of(card2)
        ui.heading(t2, "Leaderboard", self.p, bg=self.p["surface_alt"]).pack(
            anchor="w", pady=(0, 8))
        self._table(
            t2, ["#", "Player", "Score", "Avg"],
            [[str(i), s["player_name"], str(s["total_score"]),
              format_ms(s.get("average_reaction_ms", -1))]
             for i, s in enumerate(data.get("leaderboard", []), 1)],
            self.p["surface_alt"])

        ui.label(outer, "Next round starting soon …", self.p, size=12,
                 muted=True, bg=self.p["bg"]).pack(anchor="w", pady=(14, 0))

        msg, colour = self.app.round_feedback(data)
        self.app.show_overlay(msg, colour)

    def _round_row(self, r: dict) -> list:
        if r.get("false_start"):
            rt = "FALSE START"
        elif r.get("timed_out"):
            rt = "TIMED OUT"
        else:
            rt = format_ms(r.get("adjusted_reaction_ms",
                                 r.get("reaction_time_ms", -1)))
        name = r.get("player_name", "?")
        if r.get("eliminated"):
            name += " (out)"
        return [name, rt, str(r.get("score", 0))]

    def _table(self, parent, headers: list, rows: list, bg: str) -> None:
        """Render a simple aligned table of labels.

        The table lives in its own gridded sub-frame that is *packed* into the
        parent, so a parent using ``pack`` (e.g. a heading above the table)
        never clashes with this table's ``grid`` usage.
        """
        grid = tk.Frame(parent, bg=bg)
        grid.pack(anchor="w", fill=tk.X)
        for c, h in enumerate(headers):
            ui.label(grid, h, self.p, size=11, bold=True, fg=self.p["gold"],
                     bg=bg).grid(row=0, column=c, padx=6, pady=3, sticky="w")
        for i, row in enumerate(rows, 1):
            for c, val in enumerate(row):
                ui.label(grid, str(val), self.p, size=12, bg=bg).grid(
                    row=i, column=c, padx=6, pady=2, sticky="w")

    # =======================================================================
    # Game over
    # =======================================================================

    def build_game_over(self, data: dict) -> None:
        self._clear()
        self.app.round_state = "idle"
        outer = tk.Frame(self.container, bg=self.p["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=28, pady=22)
        self.app.current_screen = outer

        self._header(outer, "GAME OVER", "Final Results")

        winner = data.get("winner", "???")
        lb = data.get("final_leaderboard", [])

        # Podium (top 3).
        podium = tk.Frame(outer, bg=self.p["bg"])
        podium.pack(fill=tk.X, pady=(0, 10))
        medals = ["\U0001F947", "\U0001F948", "\U0001F949"]
        for i, entry in enumerate(lb[:3]):
            col = ui.card(podium, self.p, bg=self.p["surface_alt"],
                          padx=16, pady=14)
            col.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=6)
            ci = ui.inner_of(col)
            ui.label(ci, medals[i], self.p, size=22,
                     bg=self.p["surface_alt"]).pack()
            ui.label(ci, entry["player_name"], self.p, size=14, bold=True,
                     bg=self.p["surface_alt"]).pack()
            ui.label(ci, f"{entry['total_score']} pts", self.p, size=12,
                     fg=self.p["gold"], bg=self.p["surface_alt"]).pack()

        ui.label(outer, f"Champion: {winner}", self.p, size=18, bold=True,
                 fg=self.p["success"], bg=self.p["bg"]).pack(anchor="w",
                                                             pady=(6, 10))

        # Full leaderboard
        card2 = ui.card(outer, self.p, padx=18, pady=14)
        card2.pack(fill=tk.X)
        t2 = ui.inner_of(card2)
        self._table(
            t2, ["Rank", "Player", "Score", "Fastest", "Avg", "FS"],
            [[f"#{e.get('rank', i)}", e["player_name"], str(e["total_score"]),
              format_ms(e.get("fastest_reaction_ms", -1)),
              format_ms(e.get("average_reaction_ms", -1)),
              str(e.get("false_starts", 0))]
             for i, e in enumerate(lb, 1)],
            self.p["surface"])

        # Personal stats
        me = data.get("personal_stats", {}).get(self.app.player_name)
        if me:
            ps = ui.card(outer, self.p, bg=self.p["surface_alt"],
                         padx=18, pady=12)
            ps.pack(fill=tk.X, pady=(12, 0))
            psi = ui.inner_of(ps)
            ui.heading(psi, "Your Stats", self.p,
                       bg=self.p["surface_alt"]).pack(anchor="w")
            ui.label(
                psi,
                f"Avg {format_ms(me['average_reaction_ms'])}   ·   "
                f"Fastest {format_ms(me['fastest_reaction_ms'])}   ·   "
                f"False starts {me['false_starts']}",
                self.p, size=12, bg=self.p["surface_alt"]).pack(anchor="w",
                                                                pady=(4, 0))

        btns = tk.Frame(outer, bg=self.p["bg"])
        btns.pack(anchor="w", pady=(16, 0))
        self.app.rematch_btn = ui.button(
            btns, "Ready for Rematch", self.app.action_rematch, self.p,
            kind="success", width=18)
        self.app.rematch_btn.pack(side=tk.LEFT, padx=(0, 8))
        ui.button(btns, "Leave Room", self.app.action_leave_room, self.p,
                  kind="ghost", width=14).pack(side=tk.LEFT, padx=4)
        ui.button(btns, "Quit", self.app.action_quit, self.p, kind="danger",
                  width=10).pack(side=tk.LEFT, padx=4)

        if winner == self.app.player_name:
            self.app.show_overlay("You Win!", self.p["success"])
        else:
            self.app.show_overlay("Game Over", self.p["gold"])

    # =======================================================================
    # Practice
    # =======================================================================

    def build_practice(self) -> None:
        self._clear()
        self.app.round_state = "idle"

        top = tk.Frame(self.container, bg=self.p["bg"])
        top.pack(fill=tk.X, padx=24, pady=(18, 6))
        ui.label(top, "Practice Mode", self.p, size=24, bold=True,
                 bg=self.p["bg"]).pack(side=tk.LEFT)
        ui.button(top, "Back", self.app.go_landing, self.p, kind="ghost",
                  width=8).pack(side=tk.RIGHT)

        stats_bar = tk.Frame(self.container, bg=self.p["bg"])
        stats_bar.pack(fill=tk.X, padx=24)
        self.app.practice_stats_label = ui.label(
            stats_bar, self.app.practice_summary_text(), self.p, size=11,
            muted=True, bg=self.p["bg"])
        self.app.practice_stats_label.pack(side=tk.LEFT)
        ui.button(stats_bar, "Reset Stats", self.app.practice_reset, self.p,
                  kind="ghost", width=12).pack(side=tk.RIGHT)

        frame = tk.Frame(self.container, bg=self.p["red"])
        frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)
        self.app.game_frame = frame
        self.app.current_screen = frame

        panel = tk.Frame(frame, bg=self.p["red"], highlightthickness=3,
                         highlightbackground="#ffffff")
        panel.place(relx=0.5, rely=0.5, anchor="center",
                    relwidth=0.72, height=240)
        panel.bind("<Configure>", lambda _e: self.app.fit_game_label())
        self.app.game_panel = panel

        self.app.game_label_font = tkfont.Font(
            family=T.FONT_FAMILY, size=44, weight="bold")
        self.app.game_label = tk.Label(
            panel, text="Click to start", font=self.app.game_label_font,
            fg="#ffffff", bg=self.p["red"])
        self.app.game_label.place(relx=0.5, rely=0.5, anchor="center")

        for w in (frame, panel, self.app.game_label):
            w.bind("<Button-1>", lambda _e: self.app.practice_click())

    # =======================================================================
    # Settings
    # =======================================================================

    def build_settings(self) -> None:
        self._clear()
        outer = tk.Frame(self.container, bg=self.p["bg"])
        outer.place(relx=0.5, rely=0.5, anchor="center")
        self.app.current_screen = outer

        self._header(outer, "PREFERENCES", "Settings")

        cardf = ui.card(outer, self.p, padx=26, pady=22)
        cardf.pack()
        f = ui.inner_of(cardf)
        s = self.app.settings

        theme_var = tk.StringVar(value=s.theme)
        sound_var = tk.BooleanVar(value=s.sound_enabled)
        volume_var = tk.DoubleVar(value=s.volume)
        host_var = tk.StringVar(value=str(s.default_host))
        port_var = tk.StringVar(value=str(s.default_port))
        name_var = tk.StringVar(value=s.player_name)
        debug_var = tk.BooleanVar(value=s.debug_mode)

        r = 0
        ui.label(f, "Theme:", self.p, size=12, bg=self.p["surface"]).grid(
            row=r, column=0, sticky="e", padx=(0, 12), pady=6)
        theme_row = tk.Frame(f, bg=self.p["surface"])
        theme_row.grid(row=r, column=1, sticky="w")
        for val in ("dark", "light"):
            tk.Radiobutton(
                theme_row, text=val.capitalize(), variable=theme_var, value=val,
                font=T.font(11), bg=self.p["surface"], fg=self.p["text"],
                selectcolor=self.p["surface_alt"],
                activebackground=self.p["surface"],
                activeforeground=self.p["text"], highlightthickness=0,
                bd=0).pack(side=tk.LEFT, padx=4)

        r += 1
        e_host = ui.entry(f, self.p, width=22); e_host.insert(0, host_var.get())
        e_port = ui.entry(f, self.p, width=22); e_port.insert(0, port_var.get())
        e_name = ui.entry(f, self.p, width=22); e_name.insert(0, name_var.get())

        def field(row, lbl, widget):
            ui.label(f, lbl, self.p, size=12, bg=self.p["surface"]).grid(
                row=row, column=0, sticky="e", padx=(0, 12), pady=6)
            widget.grid(row=row, column=1, sticky="w", pady=6)

        field(r, "Default Host:", e_host); r += 1
        field(r, "Default Port:", e_port); r += 1
        field(r, "Player Name:", e_name); r += 1

        tk.Checkbutton(
            f, text="Sound enabled", variable=sound_var, font=T.font(11),
            bg=self.p["surface"], fg=self.p["text"],
            selectcolor=self.p["surface_alt"], activebackground=self.p["surface"],
            activeforeground=self.p["text"], highlightthickness=0, bd=0).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(6, 0)); r += 1

        ui.label(f, "Volume:", self.p, size=12, bg=self.p["surface"]).grid(
            row=r, column=0, sticky="e", padx=(0, 12))
        tk.Scale(f, variable=volume_var, from_=0.0, to=1.0, resolution=0.1,
                 orient=tk.HORIZONTAL, length=160, bg=self.p["surface"],
                 fg=self.p["text"], highlightthickness=0,
                 troughcolor=self.p["surface_alt"]).grid(
            row=r, column=1, sticky="w"); r += 1

        tk.Checkbutton(
            f, text="Debug mode", variable=debug_var, font=T.font(11),
            bg=self.p["surface"], fg=self.p["text"],
            selectcolor=self.p["surface_alt"], activebackground=self.p["surface"],
            activeforeground=self.p["text"], highlightthickness=0, bd=0).grid(
            row=r, column=0, columnspan=2, sticky="w"); r += 1

        def do_save() -> None:
            self.app.action_save_settings(
                theme=theme_var.get(), sound=sound_var.get(),
                volume=volume_var.get(), host=e_host.get().strip(),
                port=e_port.get().strip(), name=e_name.get().strip(),
                debug=debug_var.get())

        btnrow = tk.Frame(f, bg=self.p["surface"])
        btnrow.grid(row=r, column=0, columnspan=2, pady=(14, 4))
        ui.button(btnrow, "Save", do_save, self.p, width=14).pack(
            side=tk.LEFT, padx=4)
        ui.button(btnrow, "Back", self.app.go_landing, self.p, kind="ghost",
                  width=10).pack(side=tk.LEFT, padx=4)
