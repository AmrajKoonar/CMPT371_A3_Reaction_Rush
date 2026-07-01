"""
Reaction Rush v2 — a TCP multiplayer reaction game.

This package contains the full v2 implementation:

    protocol.py       Newline-delimited JSON wire protocol (v2, backward compatible)
    constants.py      Shared string/int constants (message types, states, modes)
    config.py         Server + room configuration dataclasses and defaults
    logging_config.py Structured logging setup
    models.py         Dataclasses for players, sessions, results
    game_logic.py     Pure scoring / round logic for every game mode
    stats.py          Aggregate per-player statistics helpers
    bots.py           Server-side bot players
    persistence.py    Optional SQLite persistence layer (standard library)
    game_session.py   Per-room game state machine
    room_manager.py   Rooms and the manager that routes players to them
    server_app.py     TCP server application (accept loop, heartbeat, reconnect)
    client_app.py     Tkinter GUI client application
    ui/               Reusable Tkinter theme, components, sounds and screens

The top-level ``server.py`` and ``client.py`` remain as thin entry points so
the original run commands keep working:

    python server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2
    python client.py
"""

__version__ = "2.0.0"
