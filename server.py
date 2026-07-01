"""
server.py — Entry point for the Reaction Rush server.

Kept as a thin wrapper so the original command still works exactly as before:

    python server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2

All logic lives in the ``reaction_rush`` package (see reaction_rush/server_app.py).
"""

from reaction_rush.server_app import main

if __name__ == "__main__":
    main()
