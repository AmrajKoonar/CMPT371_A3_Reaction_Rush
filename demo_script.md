# Reaction Rush — 2-Minute Demo Script

This document outlines a short demonstration of the Reaction Rush multiplayer
reaction-time game. It is designed to fit within a **2-minute video** and
covers all key deliverables: connection setup, data exchange, gameplay, and
clean termination.

---

## Setup Before Recording

1. Have **three** terminal / command-prompt windows open and arranged so they
   are all visible (or use split-screen).
2. Verify Python 3.8+ is installed (`python --version`).
3. `cd` into the project directory in all three terminals.

---

## Demo Sequence

| Time | Action | What to show / say |
|---|---|---|
| **0:00** | **Start the server** | Run `python server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2`. Point out the log output confirming the server is listening. |
| **0:10** | **Launch Client 1** | Run `python client.py`. Fill in Host, Port, Access Code, and Player Name (e.g., "Alice"). Click **Connect**. Show the lobby screen and that Alice appears in the player list. |
| **0:25** | **Launch Client 2** | Run `python client.py` in the third terminal. Connect as "Bob" with the same access code. Show that both Alice and Bob are now visible in each other's lobby. |
| **0:35** | **Ready up** | Click **Ready** on both clients. Point out the server log showing both players are ready and that the game is starting. |
| **0:45** | **Round 1 — gameplay** | Both clients show the red screen ("Wait for green…"). After the random delay, the screen turns green ("Click!"). Click on each client. Show the round results and leaderboard that appear afterwards. |
| **1:05** | **Round 2 — false start** | On one client, deliberately click **during the red screen** before green appears. Show the orange penalty screen ("Penalty: Too soon!"). Point out that the round results give 0 points for the false start. |
| **1:25** | **Skip to final results** | Let the remaining rounds play out (fast-forward or cut in editing if needed). After Round 5, show the **Game Over** screen with the final leaderboard and winner announcement. |
| **1:40** | **Client quit** | Click the **Quit** button on one client. Show the server log indicating the player disconnected. |
| **1:50** | **Server shutdown** | Press **Ctrl+C** in the server terminal. Show the graceful shutdown message and the remaining client receiving a disconnect notification. |
| **2:00** | **End** | Summarise: "We demonstrated TCP connection setup, lobby management, real-time gameplay with server-controlled fairness, false-start handling, leaderboard updates, and clean disconnection for both client and server." |

---

## Suggested Voiceover Lines

1. *"We start the server on localhost port 5000 with access code RED123."*
2. *"Alice connects and enters the lobby. The server confirms her join."*
3. *"Bob joins the same lobby. Both players can see each other."*
4. *"Both players click Ready. The server detects that the minimum player count is met and starts the game."*
5. *"Round 1: the screen is red — we must wait. Now it's green — click! The server measures our reaction times and awards scores."*
6. *"In Round 2, I'll deliberately click too early to show the false-start penalty. The orange screen confirms the penalty, and I receive zero points."*
7. *"After five rounds, the final leaderboard shows the winner."*
8. *"We close the client cleanly, and the server logs the disconnection. Finally, Ctrl+C shuts down the server gracefully."*

---

## Tips for Recording

* Use **localhost** (`127.0.0.1`) so there is no noticeable network latency.
* Arrange windows side-by-side so the grader can see both clients and the
  server simultaneously.
* If the video needs to be shorter, you can fast-forward the middle rounds
  and focus on Rounds 1, 2, and 5.
