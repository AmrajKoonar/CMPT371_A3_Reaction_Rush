# Reaction Rush v2 — A TCP Multiplayer Reaction Game

> **Reaction Rush** is a real-time multiplayer reaction-time battle built on raw
> **Python TCP sockets** with a polished **Tkinter** desktop client. Race friends
> (or bots) across five rounds: wait for green, click as fast as you can, and
> don't jump the gun.

**Course:** CMPT 371 — Data Communications & Networking
**Instructor:** Mirza Zaeem Baig · **Semester:** Spring 2026

> **v2 in one line:** multiple rooms, five game modes, server-side bots, an
> offline practice mode, latency compensation, heartbeat + reconnect, SQLite
> stats, a modern themed UI, a test suite, CI, and Docker — all while the
> original v1 run commands still work unchanged.

---

## Group Members

| Name | Student ID | Email | GitHub Username |
| :--- | :--- | :--- | :--- |
| Geonwoo Park | 301635420 | gpa40@sfu.ca | aidenplabs |
| Amraj Koonar | 301559468 | ask36@sfu.ca | AmrajKoonar |

---

## Table of Contents

1. [Features](#features)
2. [Screenshots](#screenshots)
3. [Architecture](#architecture)
4. [Protocol](#protocol)
5. [Game Modes](#game-modes)
6. [Room System](#room-system)
7. [Bots](#bots)
8. [Practice Mode](#practice-mode)
9. [Latency Compensation & Fairness](#latency-compensation--fairness)
10. [Persistence (SQLite)](#persistence-sqlite)
11. [Scoring Rules](#scoring-rules)
12. [Repository Structure](#repository-structure)
13. [Prerequisites](#prerequisites)
14. [Installation](#installation)
15. [Running the Game](#running-the-game)
16. [Playing on a LAN](#playing-on-a-lan)
17. [Server CLI Reference](#server-cli-reference)
18. [Testing](#testing)
19. [Docker](#docker)
20. [How to Quit / Disconnect Behavior](#how-to-quit--disconnect-behavior)
21. [Troubleshooting](#troubleshooting)
22. [Limitations & Known Issues](#limitations--known-issues)
23. [Future Improvements](#future-improvements)
24. [Video Demo](#video-demo)
25. [Academic Integrity & References](#academic-integrity--references)

---

## Features

- **Pure Python TCP sockets** — client-server architecture, newline-delimited
  JSON, no web frameworks (no Flask), no browser.
- **Modern Tkinter UI** — dark/light themes, card-based layout, hover states,
  a landing screen, lobby, animated round overlays, podium, and settings.
- **Multiple rooms** — create private rooms with short codes (`ABC123`) or join
  the shared default room with the classic access code.
- **Five game modes** — Classic, Sudden Death, Elimination, Consistency, Chaos.
- **Server-side bots** — four skill levels; add them from the lobby to fill a game.
- **Practice mode** — a fully offline single-player reaction trainer with local
  SQLite stats and personal bests.
- **Rematch flow** — replay without restarting the server or reconnecting.
- **Latency handling** — ping/pong heartbeat, per-player RTT, and optional,
  bounded latency compensation for scoring.
- **Reconnect** — session tokens let a dropped player rejoin an in-progress room.
- **SQLite persistence** — matches, rounds, participants, and practice results.
- **Structured logging** — console + optional file, adjustable log level.
- **Tested** — a `pytest` suite (unit + integration) and a GitHub Actions CI.
- **Dockerized server** — one command to run the headless server.
- **100% backward compatible** — the original v1 commands and flow still work.

---

## Screenshots

> Placeholders — drop real captures into `assets/` and they'll render here.

| Landing | Lobby | Reaction |
| :---: | :---: | :---: |
| `assets/screenshot_landing.png` | `assets/screenshot_lobby.png` | `assets/screenshot_game.png` |

| Round Results | Game Over (Podium) | Practice |
| :---: | :---: | :---: |
| `assets/screenshot_results.png` | `assets/screenshot_gameover.png` | `assets/screenshot_practice.png` |

---

## Architecture

```
                        TCP  ·  newline-delimited JSON  ·  port 5000
   ┌────────────────────────┐                         ┌───────────────────────────┐
   │   Tkinter GUI Client    │  ◄────────────────────► │        Game Server         │
   │   reaction_rush/        │                         │   reaction_rush/           │
   │     client_app.py       │                         │     server_app.py          │
   │     ui/ (theme,         │                         │     room_manager.py        │
   │         components,     │                         │       └─ Room ── GameSession│
   │         sounds, screens)│                         │     bots.py                │
   └───────────┬────────────┘                         │     persistence.py (SQLite)│
               │                                       └─────────────┬─────────────┘
        shared modules  ────────────────────────────────────────────┘
     protocol.py · game_logic.py · models.py · stats.py · config.py · constants.py
```

**Server threading model**

- **Main thread** — accepts TCP connections.
- **Per-connection thread** — reads messages from one socket and routes them.
- **Per-room game thread** — runs the round state machine for that room.
- **Heartbeat thread** — pings clients and drops silent ones.

All shared room state is guarded by a single `threading.Lock` per room; blocking
I/O (socket sends, sleeps, event waits) always happens **outside** the lock.

**Client threading model**

- **Main (Tk) thread** — owns all widgets; performs quick non-blocking sends.
- **Receiver thread** — reads messages into a `queue.Queue`.
- **Queue poller** — a `root.after()` callback drains the queue on the Tk thread.

### Why TCP?

Every lobby update, round signal, and score must arrive **reliably and in order**.
A lost `round_go` would strand a player on the red screen; a reordered
`round_result` would corrupt the leaderboard. TCP gives us ordered, reliable,
flow-controlled delivery for free — exactly what a turn-based reaction game needs.
UDP would trade that guarantee for latency we don't need on a LAN/localhost.

---

## Protocol

Application-layer messages are JSON objects, one per line (`\n`-terminated),
sent over TCP. Two shapes are supported:

- **Flat (v1, still used everywhere):** `{"type": "ready"}`
- **Envelope (v2, optional):**
  `{"type": "...", "version": 2, "request_id": "...", "payload": {...}}`

The protocol layer (`reaction_rush/protocol.py`) adds a **maximum message size**,
defensive JSON parsing (malformed lines are skipped, never crash), TCP
re-framing for partial/merged reads, and a `validate_message` helper.

Representative message types:

| Direction | Types |
| :--- | :--- |
| Client → Server | `join_request`, `create_room`, `join_room`, `leave_room`, `ready`, `click`, `add_bot`, `remove_bot`, `rematch_ready`, `rematch_cancel`, `reconnect`, `pong`, `disconnect` |
| Server → Client | `join_response`, `room_created`, `room_error`, `lobby_update`, `game_start`, `round_prepare`, `round_go`, `fake_signal`, `penalty`, `round_result`, `game_over`, `rematch_update`, `new_match_starting`, `bot_added`, `bot_removed`, `ping`, `latency_update`, `player_left`, `player_disconnected`, `player_reconnected`, `reconnect_response`, `error`, `disconnect` |

Example click message (client timestamp is diagnostic only — the server stays
authoritative):

```json
{"type": "click", "early": false, "round_number": 3, "client_clicked_at": 1234.56}
```

---

## Game Modes

| Mode | Rounds | How you win |
| :--- | :--- | :--- |
| **Classic** (default) | configurable (5) | Highest total placement score. |
| **Sudden Death** | 1 | Only the single fastest valid click scores. |
| **Elimination** | until one remains | The slowest valid player is eliminated each round; false starts put you at risk. Last player standing wins. |
| **Consistency** | configurable | Best **average** valid reaction time wins; false starts hurt heavily. |
| **Chaos** | configurable | Decoy "fake signals" appear before the real green. Clicking a decoy is a false start. Safe, brief tints — **no** rapid/intense flashing. |

The host picks the mode on the **Create Room** screen (or via `--mode` for the
default room). Sudden Death is automatically clamped to one round.

---

## Room System

- **Default room** — bound to the server access code (`RED123`). The classic
  `join_request` + access-code flow lands here, preserving v1 behavior.
- **Create room** — generates a short, readable 6-character code and lets the
  host choose mode, rounds, player limits, latency compensation, and bots.
- **Join by code** — enter a room code on the Join screen to hop into a specific
  room.
- **Isolation** — each room has independent players, settings, game state, and
  leaderboard. Starting one room never affects another.
- **Cleanup** — empty non-default rooms are removed automatically.

---

## Bots

Add bots from the lobby (host only) to fill out a match — great for demos and
solo testing. Bots live entirely **server-side**, so they behave like real
players: they appear in the lobby, ready up, react (or occasionally false-start),
and land on the leaderboard — all with **no socket connection**.

| Bot | Reaction time | False-start chance |
| :--- | :--- | :--- |
| Beginner | ~450–700 ms | very rare |
| Average | ~250–400 ms | occasional |
| Pro | ~160–240 ms | very rare |
| Risky | ~120–220 ms | high |

---

## Practice Mode

Click **Practice Mode** on the landing screen — **no server required**. It runs
local reaction tests (random wait → green → click), detects false starts, and
tracks your **fastest / slowest / average** times, **attempts**, **false starts**,
and a **consistency** score. Stats are saved locally in SQLite
(`reaction_rush_practice.db`) and can be reset from the screen.

---

## Latency Compensation & Fairness

The server is always authoritative. Reaction time is measured from the moment
the server **sends** `round_go` to the moment the click **arrives** — using
`time.monotonic()` on the server.

- A **ping/pong heartbeat** estimates each player's round-trip time (RTT).
- With latency compensation **on**, scoring subtracts an estimated one-way delay
  (`RTT / 2`) from the raw time, **bounded** so nobody can reach an impossible
  sub-50 ms result.
- Both **raw** and **adjusted** times are stored; adjusted is used for scoring
  only when enabled.
- Implausibly fast reactions (< 80 ms) are flagged **suspicious** rather than
  blindly trusted. Client-provided timestamps are used for diagnostics only.

Fairness guarantees every player the **same round configuration** (same round
number, same server-chosen delay, same simultaneous `round_go`).

---

## Persistence (SQLite)

Enabled by default (disable with `--disable-persistence`). Uses only the
standard-library `sqlite3` module. Tables: `players`, `matches`,
`match_participants`, `round_results`, `practice_results`, `personal_bests`.

```bash
python3 server.py --db reaction_rush.db
```

---

## Scoring Rules

Per round (Classic/Chaos), valid clicks are ranked fastest → slowest:

| Placement | Points |
| :--- | :--- |
| 1st | 100 |
| 2nd | 75 |
| 3rd | 50 |
| 4th and below | 25 |
| False start / timeout | 0 |

- **Winner:** highest total score. **Tie-break:** lowest cumulative reaction time.
- **Sudden Death:** only the fastest valid player scores.
- **Consistency:** ranked by best average valid reaction time.
- **Elimination:** survive each round; last player standing wins.

Timeout: if you don't click within 3 seconds of green, you score 0 for the round.

---

## Repository Structure

```
CMPT371_A3_Reaction_Rush/
├── server.py               # thin entry point → reaction_rush.server_app:main
├── client.py               # thin entry point → reaction_rush.client_app:main
├── protocol.py             # backward-compat shim → reaction_rush.protocol
├── game_logic.py           # backward-compat shim → reaction_rush.game_logic
├── utils.py                # backward-compat shim → reaction_rush.utils
├── reaction_rush/
│   ├── __init__.py
│   ├── constants.py        # message types, states, modes, defaults
│   ├── config.py           # ServerConfig / RoomSettings / ClientSettings
│   ├── logging_config.py   # logging setup
│   ├── protocol.py         # v2 wire protocol (backward compatible)
│   ├── models.py           # dataclasses: sessions, results, standings
│   ├── game_logic.py       # scoring + modes + latency (pure functions)
│   ├── stats.py            # per-player + practice summaries
│   ├── bots.py             # server-side bot players
│   ├── persistence.py      # SQLite layer
│   ├── game_session.py     # per-room state machine
│   ├── room_manager.py     # Room + RoomManager (orchestration)
│   ├── server_app.py       # TCP server (accept loop, heartbeat, reconnect, CLI)
│   ├── client_app.py       # Tkinter client controller (+ CLI)
│   └── ui/
│       ├── theme.py         # colour system + fonts (dark/light)
│       ├── components.py    # reusable widgets (buttons, cards, entries)
│       ├── sounds.py        # optional cross-platform sound feedback
│       └── screens.py       # screen builders
├── tests/
│   ├── test_game_logic.py
│   ├── test_protocol.py
│   ├── test_rooms.py
│   ├── test_persistence.py
│   └── test_integration_basic.py
├── requirements.txt         # runtime deps (none — stdlib only)
├── requirements-dev.txt     # pytest for development
├── pyproject.toml
├── Dockerfile
├── .env.example
├── .github/workflows/tests.yml
├── demo_script.md
└── README.md
```

---

## Prerequisites

- **Python 3.9+** (3.11 recommended).
- **Tkinter** for the client GUI (bundled with CPython on Windows/macOS).
  On Linux: `sudo apt install python3-tk`.
- No third-party packages are required to **play**. `pytest` is only needed to
  run the tests.

---

## Installation

```bash
# 1. Clone
git clone https://github.com/AmrajKoonar/CMPT371_A3_Reaction_Rush.git
cd CMPT371_A3_Reaction_Rush

# 2. (Optional) virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Runtime deps: none required (standard library only)
pip install -r requirements.txt        # documents that no packages are needed

# 4. (Optional) dev/test deps
pip install -r requirements-dev.txt
```

---

## Running the Game

You need **at least 3 windows**: one server + two clients (use `python3` on
macOS/Linux, `python` on Windows if that's your Python 3).

**1. Start the server (classic command still works exactly as in v1):**

```bash
python3 server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2
```

**2. Launch each client:**

```bash
python3 client.py
```

**3. In each client window:**

- **Join Game** → enter Host `127.0.0.1`, Port `5000`, leave Room Code blank,
  Access Code `RED123`, and a unique name → **Connect** → **Ready**.
- Or **Create Room** → pick a mode/settings → share the room code → others use
  **Join Game** with that room code.

The match starts automatically once all connected players are ready (and at
least `--min-players` are present). Add bots from the lobby to reach the minimum.

---

## Playing on a LAN

1. Start the server bound to all interfaces:
   ```bash
   python3 server.py --host 0.0.0.0 --port 5000 --access-code RED123
   ```
2. Find the server machine's LAN IP (e.g. `192.168.1.20`).
3. On each client, use that IP as the Host and the same port/access code.
4. Ensure the port is allowed through the server's firewall.

---

## Server CLI Reference

```bash
python3 server.py --help
```

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--host` | `127.0.0.1` | Interface to bind (`0.0.0.0` for LAN). |
| `--port` | `5000` | TCP port. |
| `--access-code` | `RED123` | Default-room access code. |
| `--min-players` | `2` | Minimum players to start. |
| `--max-players` | `8` | Max players per room. |
| `--rounds` | `5` | Rounds per match. |
| `--mode` | `classic` | Default mode: classic/sudden_death/elimination/consistency/chaos. |
| `--db` | `reaction_rush.db` | SQLite database path. |
| `--log-level` | `INFO` | DEBUG/INFO/WARNING/ERROR. |
| `--log-file` | *(none)* | Also write logs to this file. |
| `--disable-persistence` | off | Run without the database. |
| `--disable-latency-compensation` | off | Use raw reaction times for scoring. |

Client CLI (optional prefill):

```bash
python3 client.py --host 127.0.0.1 --port 5000 --name Alice
```

Examples:

```bash
python3 server.py --host 0.0.0.0 --port 5000 --db reaction_rush.db --log-level INFO
python3 server.py --mode elimination --rounds 7 --max-players 6
```

---

## Testing

```bash
pip install -r requirements-dev.txt
python3 -m pytest
```

The suite covers scoring/modes/stats, the protocol (framing, partial reads,
oversized/invalid input), rooms and the state machine, SQLite persistence, and a
full **server-in-a-thread** integration test (connect → ready → click →
`game_over`). CI runs on Python 3.9 and 3.11 via GitHub Actions.

---

## Docker

The server runs headlessly in Docker (the GUI client runs on your desktop):

```bash
docker build -t reaction-rush-server .
docker run -p 5000:5000 reaction-rush-server
# with options:
docker run -p 5000:5000 reaction-rush-server --access-code MYCODE --mode chaos
```

Then connect desktop clients to your host IP on port `5000`.

---

## How to Quit / Disconnect Behavior

- **Client:** close the window, or use **Leave Room** / **Quit**. The client
  sends a clean `disconnect`.
- **Server:** press **Ctrl+C** — connected clients are notified and sockets are
  closed cleanly; the database is flushed.
- **On disconnect:** the player is removed (or, mid-match, kept for reconnect);
  remaining players are notified and the lobby/leaderboard updates. If too few
  players remain, the match ends gracefully. Broken pipes/resets are handled and
  never crash the app.

---

## Troubleshooting

| Problem | Fix |
| :--- | :--- |
| `Connection refused` | Start the server first; check host/port. |
| `Invalid access code` | Match `--access-code` with the client's Access Code. |
| `Room not found` | Re-check the room code (codes are case-insensitive here). |
| Game won't start | All connected players must be **Ready** and count ≥ `--min-players` (add bots to fill). |
| `Tkinter not found` (Linux) | `sudo apt install python3-tk`. |
| `Address already in use` | Another process holds the port; pick a new `--port`. |
| No sound | Sound is cosmetic; enable it in **Settings**. Custom tones are Windows-only, elsewhere a system bell is used. |

---

## Limitations & Known Issues

- **Latency bias:** measured reaction time includes network round-trip. Latency
  compensation reduces but cannot fully eliminate this; best on LAN/localhost.
- **Tkinter UI:** simple and local; no high-DPI scaling guarantees across all OSes.
- **Reconnect window:** reconnection works while the room still exists and the
  session token matches; if the room ended, you'll get a clear error.
- **Not hardened for hostile internet:** no encryption/accounts beyond the room
  access code; intended for trusted LAN/localhost use.
- **No central matchmaking:** rooms live in a single server process (in memory).
- **Bots are heuristic:** they emulate human-like timing, not real perception.

---

## Future Improvements

- TLS transport and account authentication.
- A room browser / matchmaking lobby.
- Spectator mode and richer post-match analytics from the SQLite history.
- Optional `customtkinter`/`ttkbootstrap` skin (with graceful fallback).
- Cross-machine reconnect persistence.

---

## Video Demo

Our 2-minute demonstration covers connection setup, data exchange, gameplay
(including a false start), the leaderboard, the winner, and clean termination:

[Reaction Rush Video Demo](https://www.youtube.com/watch?v=2MjNeODf68w)

See [`demo_script.md`](demo_script.md) for the scene-by-scene plan.

---

## Academic Integrity & References

- **No Flask / no web frameworks.** This is a pure Python **socket** application
  over **TCP**, with a **Tkinter** GUI client.

- **Code Origin:**
  - The gameplay idea was inspired by the [Human Benchmark: Reaction Time Test](https://humanbenchmark.com/tests/reactiontime).
  - The networking logic, client-server protocol, lobby/room flow, game modes,
    bots, scoring, persistence, and GUI were implemented by the group, using
    course materials and Python documentation as references.

- **GenAI Usage:**
  - ChatGPT was used to help reorganize and polish parts of the `README.md`,
    assist with debugging, clean up code for readability, and clarify technical
    concepts related to `client.py`, `server.py`, `game_logic.py`, and
    `protocol.py`.
  - Codex was used to help create the demo video subtitles and assist with some
    UI/interface improvements, including result/status wording, feedback
    messages, and simple animation/presentation in the client interface.
  - For the v2 upgrade, an AI coding assistant was used to help scaffold the
    package refactor, room/bot/mode systems, tests, and documentation.
  - *(If your course requires it, add a specific citation line here for the exact
    tool/version used and how, so this section reflects your own submission.)*
  - All final code was written, implemented, and reviewed by us to ensure
    academic integrity was upheld.

- **References:**
  - [Human Benchmark: Reaction Time Test](https://humanbenchmark.com/tests/reactiontime)
  - [Python Socket Programming HOWTO](https://docs.python.org/3/howto/sockets.html)
  - [Python `threading` documentation](https://docs.python.org/3/library/threading.html)
  - [Python `tkinter` documentation](https://docs.python.org/3/library/tkinter.html)
  - [Python `sqlite3` documentation](https://docs.python.org/3/library/sqlite3.html)
