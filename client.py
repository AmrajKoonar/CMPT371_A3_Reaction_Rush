"""
client.py — Entry point for the Reaction Rush GUI client.

Kept as a thin wrapper so the original command still works exactly as before:

    python client.py

All logic lives in the ``reaction_rush`` package (see reaction_rush/client_app.py).
"""

from reaction_rush.client_app import main

if __name__ == "__main__":
    main()
