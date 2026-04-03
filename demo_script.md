# Reaction Rush — 2-Minute Demo Script

This document outlines a short demo plan for the Reaction Rush multiplayer
TCP game. The goal is to clearly show that the code runs, establishes
connections, exchanges gameplay data correctly, and handles termination
cleanly within the 2-minute limit.

---

## Setup Before Recording

1. Open one server terminal and two client terminals.
2. Arrange the server terminal and both client windows so they are visible in
   the recording at the same time whenever possible.
3. Verify that Python 3.9+ is available.
4. In each terminal, move to the project directory.
5. Keep the server terminal font large enough that the logs are readable in
   the final video.

---

## Recommended Demo Flow

1. **Start the server**
   Run:
   ```bash
   python3 server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2
   ```
   Show the server log confirming that it is listening and waiting for players.

2. **Connect Client 1**
   Run:
   ```bash
   python3 client.py
   ```
   Enter the host, port, access code, and a player name such as `Alice`.
   Click `Connect` and show that the player appears in the lobby.

3. **Connect Client 2**
   Run:
   ```bash
   python3 client.py
   ```
   Enter the same host, port, and access code, but use a different player
   name such as `Bob`. Show that both players are visible in the same lobby.

4. **Show lobby synchronization**
   Click `Ready` on both clients and show that the game starts only after all
   connected players are ready. Keep the server log visible so the transition
   from lobby to game is easy to follow.

5. **Demonstrate a normal round**
   Show one round where both players wait during the red screen, react after
   the green screen appears, and then receive the round results and updated
   leaderboard.

6. **Demonstrate a false start**
   In the next round, intentionally click during the red screen on one client.
   Show the orange penalty feedback and then show the round results where the
   false-starting player receives 0 points.

7. **Show the final game result**
   Let the remaining rounds continue, or trim / fast-forward them in editing if
   needed. Show the `Game Over` screen, the final leaderboard, and the winner.

8. **Demonstrate clean client termination**
   Click the `Quit` button on one client and show the server logging that the
   player disconnected.

9. **Demonstrate clean server termination**
   Press `Ctrl+C` in the server terminal and show the remaining client
   receiving the disconnect notification.

---

## What the Video Should Prove

- The application runs successfully without setup confusion.
- The server and clients establish TCP connections correctly.
- The application exchanges lobby, gameplay, scoring, and final-result data.
- The server handles timing, penalties, leaderboard updates, and winner
  selection.
- The system handles disconnects and shutdown cleanly.

---

## Suggested Voiceover Lines

1. *"This project is a TCP client-server multiplayer reaction game built in Python."*
2. *"We start the server first, then connect two clients to the same lobby using the same access code."*
3. *"The lobby updates in real time as players join and mark themselves ready."*
4. *"The game begins only when all connected players are ready."*
5. *"In each round, the server controls the timing and the clients react when the screen turns green."*
6. *"After each round, the server sends the results and the updated leaderboard to both clients."*
7. *"Here we demonstrate a false start, where clicking during the red screen triggers a penalty and gives 0 points."*
8. *"At the end of the game, the final leaderboard and winner are displayed."*
9. *"We also demonstrate clean client disconnect and graceful server shutdown."*

---

## Recording Tips

- Use `127.0.0.1` so latency does not distract from the demo.
- Keep all important windows visible at the same time whenever possible.
- Use short player names so the UI is easy to read.
- If the full match feels too long on video, keep the normal round, the
  false-start round, and the final results, then trim repetitive middle parts.
- Stay under the 2-minute limit with a small buffer instead of aiming exactly
  at 120 seconds.
