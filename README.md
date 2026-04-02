# Reaction Rush: A TCP Multiplayer Reaction Game

A real-time multiplayer reaction-time game built entirely with the **Python standard library**.  
Players connect to a shared lobby over **TCP sockets**, then compete across five rounds to see who has the fastest reflexes.

> **Course:** CMPT 371 — Data Communications and Networking  
> **Assignment:** A3 — Socket Programming Project

---

## Table of Contents

1. [Features](#features)  
2. [Architecture Overview](#architecture-overview)  
3. [Why TCP?](#why-tcp)  
4. [Fairness Design](#fairness-design)  
5. [Project Structure](#project-structure)  
6. [Prerequisites](#prerequisites)  
7. [Installation & Setup](#installation--setup)  
8. [Running the Application](#running-the-application)  
9. [Example Session](#example-session)  
10. [How to Quit / Terminate](#how-to-quit--terminate)  
11. [Scoring Rules](#scoring-rules)  
12. [Limitations & Known Issues](#limitations--known-issues)  
13. [Troubleshooting](#troubleshooting)  
14. [Demo Video](#demo-video)  
15. [Team Members](#team-members)  
16. [GenAI Citation](#genai-citation)

---

## Features

| Feature | Details |
|---|---|
| **TCP client-server networking** | All communication uses `socket` + `threading` from the Python standard library. |
| **Lobby system** | Access-code-protected lobby with player names and ready states. |
| **5-round reaction game** | Server-controlled red → green screen transitions with random delays. |
| **False-start detection** | Clicking before green triggers a penalty (0 points for the round). |
| **Live leaderboard** | Updated after every round and broadcast to all players. |
| **Graceful disconnects** | Mid-game disconnects are handled cleanly; remaining players continue. |
| **Tkinter GUI** | Lightweight, cross-platform graphical client — no browser or external UI framework needed. |
| **No external dependencies** | Uses only Python's standard library (`socket`, `threading`, `tkinter`, `json`, `time`, `random`, `queue`, `argparse`, `dataclasses`, `typing`, `traceback`). |

---

## Architecture Overview

```
┌───────────────┐        TCP / JSON + newline         ┌────────────────┐
│  Client (Tk)  │ ◄──────────────────────────────────► │  Game Server   │
│  client.py    │        port 5000 (default)           │  server.py     │
└───────────────┘                                      └────────────────┘
       ▲                                                      ▲
       │  imports                                              │  imports
       ▼                                                      ▼
  protocol.py   utils.py                          protocol.py   utils.py
                                                  game_logic.py
```

* **Server (`server.py`)** — binds a TCP socket, spawns one thread per client for receiving messages, and runs a dedicated game-controller thread for round timing and scoring.  
* **Client (`client.py`)** — connects via TCP, runs a background receiver thread, and uses `root.after()` to safely push server messages into the Tkinter event loop.  
* **Protocol (`protocol.py`)** — defines every message type and provides `send_message` / `receive_messages` helpers for newline-delimited JSON over TCP.  
* **Game logic (`game_logic.py`)** — pure functions for scoring, leaderboard calculation, and round configuration.  
* **Utilities (`utils.py`)** — small shared helpers (safe socket close, timestamp formatting).

---

## Why TCP?

TCP guarantees **reliable, ordered delivery** of data, which is essential for this game:

* Every lobby update, round signal, and score must arrive intact and in the correct sequence.  
* Lost or reordered messages would corrupt the game state (e.g., a missing `round_go` would leave a player stuck on the red screen).  
* TCP's built-in flow control and congestion management mean we don't have to implement our own retransmission logic.

UDP would offer lower latency but would require manual reliability, which adds significant complexity for marginal benefit in a turn-based reaction game on a LAN.

---

## Fairness Design

| Concern | How it is addressed |
|---|---|
| **Identical round configuration** | The server generates one random delay per round and broadcasts the same `round_prepare` / `round_go` to all clients simultaneously. |
| **Server-authoritative timing** | Reaction time = `time.monotonic()` on the server at click-arrival minus `time.monotonic()` at GO-send. The client never decides its own score. |
| **False-start detection** | Both server-side (click arrived before `round_go` was sent) and client-reported (`early=True`) checks prevent false starts from being scored. |
| **Single click per round** | Duplicate clicks are ignored server-side. |
| **Timeout** | Players who do not click within 3 seconds after GO receive 0 points for that round. |

> **Limitation:** Because reaction time is measured between server-send and server-receive, each player's measured time includes **two network hops** of latency. On localhost this is negligible; on a real network, higher-latency players are slightly disadvantaged. This is documented as a known limitation.

---

## Project Structure

```
CMPT371_A3_Reaction_Rush/
├── server.py            # TCP game server (CLI)
├── client.py            # Tkinter GUI client
├── protocol.py          # Message types & JSON framing
├── game_logic.py        # Scoring, leaderboard, round config
├── utils.py             # Shared small helpers
├── requirements.txt     # Dependency manifest (standard library only)
├── README.md            # This file
├── demo_script.md       # 2-minute video demo plan
├── .gitignore           # Python ignores
└── assets/
    └── optional_placeholder.txt
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| **Python** | 3.8 or newer (3.10+ recommended) |
| **Tkinter** | Included with standard CPython installs on Windows and macOS. On some Linux distros you may need `sudo apt install python3-tk`. |

No third-party packages are required.

---

## Installation & Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd CMPT371_A3_Reaction_Rush

# 2. (Optional) Create a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 3. Install dependencies (none required, but provided for completeness)
pip install -r requirements.txt
```

---

## Running the Application

You need **at least 3 terminal / command-prompt windows** for a basic session: one for the server and two for clients.

### 1. Start the server

```bash
python server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2
```

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Interface to bind to. Use `0.0.0.0` for LAN play. |
| `--port` | `5000` | TCP port to listen on. |
| `--access-code` | `RED123` | Players must enter this code to join the lobby. |
| `--min-players` | `2` | Minimum players required before the game starts. |

### 2. Launch each client

```bash
python client.py
```

A Tkinter window opens. Fill in:

* **Host** — `127.0.0.1` (or the server machine's IP)  
* **Port** — `5000`  
* **Access Code** — `RED123`  
* **Player Name** — any name up to 20 characters  

Click **Connect**, then click **Ready** in the lobby. Once all connected players are ready (and at least the minimum count), the game starts automatically.

---

## Example Session

```
# Terminal 1 — Server
python server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2

# Terminal 2 — Player 1
python client.py
# → Enter host=127.0.0.1, port=5000, code=RED123, name=Alice → Connect → Ready

# Terminal 3 — Player 2
python client.py
# → Enter host=127.0.0.1, port=5000, code=RED123, name=Bob → Connect → Ready

# Game starts automatically once both players are ready.
# Play 5 rounds. Final winner is announced on screen.
```

---

## How to Quit / Terminate

| Action | How |
|---|---|
| **Client quit** | Close the window (✕ button) or click the **Quit** button on the Game Over screen. |
| **Server shutdown** | Press **Ctrl+C** in the server terminal. All connected clients are notified. |

---

## Scoring Rules

Each of the 5 rounds awards points based on placement:

| Placement | Points |
|---|---|
| 1st (fastest) | 100 |
| 2nd | 75 |
| 3rd | 50 |
| 4th and below | 25 |
| False start | 0 |
| Timeout (no click within 3 s) | 0 |

**Final winner:** highest total score after 5 rounds.  
**Tie-breaker:** lowest cumulative reaction time.

---

## Limitations & Known Issues

1. **Network latency bias** — Measured reaction time includes round-trip latency between server and client. Players with higher latency are at a small disadvantage. The game is designed for localhost / LAN testing.
2. **Single lobby per server instance** — The server supports only one concurrent game session. Restart the server for a new game.
3. **No persistent state** — There is no database or login system. Scores exist only for the duration of the session.
4. **Tkinter limitations** — The GUI is functional but simple. Tkinter does not support rich animations or high-DPI scaling on all platforms.
5. **Not hardened for hostile deployment** — There is no encryption, authentication (beyond the access code), or rate limiting. Intended for trusted LAN / localhost use only.
6. **Maximum tested players** — Designed for 2–4 players. More may work but has not been stress-tested.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `Connection refused` | Make sure the server is running and you entered the correct host and port. |
| `Invalid access code` | Double-check the `--access-code` flag on the server and the code you entered in the client. |
| `Tkinter not found` | On Linux: `sudo apt install python3-tk`. On Windows/macOS this is included by default. |
| `Address already in use` | Another process is using the port. Either stop it or choose a different `--port`. |
| Game never starts | All connected players must click **Ready**, and there must be at least `--min-players` connected. |
| Client freezes on disconnect | Close and reopen the client window. |

---

## Demo Video

> **Video link:** *(insert link here)*

See [`demo_script.md`](demo_script.md) for the planned demo sequence.

---

## Team Members

| Name | Student ID | Email |
|---|---|---|
| *(Your Name)* | *(Student ID)* | *(Email)* |
| *(Partner Name)* | *(Student ID)* | *(Email)* |
| *(Partner Name)* | *(Student ID)* | *(Email)* |

---

## GenAI Citation

> If any generative AI tools (e.g., ChatGPT, GitHub Copilot, Claude) were used during development, cite them here per your course's academic integrity policy.

| Tool | How it was used |
|---|---|
| *(Tool name)* | *(Brief description of use)* |

---

**Note:** This project is a pure Python socket application. It does **not** use Flask, Django, or any web framework. The client GUI is built with **Tkinter** (standard library). All networking uses the Python `socket` module over TCP.
