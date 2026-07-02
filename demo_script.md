# Reaction Rush v2 — 2-Minute Demo Script

A concise plan for a ~2-minute video covering the required deliverables:
**connection setup, data exchange, gameplay, and clean termination** — plus a
few v2 highlights (rooms/bots/rematch) if time allows.

---

## Setup Before Recording

1. Open **three** terminals in the project folder (server + two clients), or
   split-screen so all are visible.
2. Confirm Python 3.9+ (`python --version` / `python3 --version`).
3. Use `python3` on macOS/Linux, `python` on Windows.

---

## Core Demo Sequence (fits in 2 minutes)

| Time | Action | Show / say |
| :--- | :--- | :--- |
| 0:00 | **Start server** | `python3 server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2`. Point at the log line confirming it's listening. |
| 0:10 | **Client 1 connects** | `python3 client.py` → **Join Game** → Host `127.0.0.1`, Port `5000`, Access `RED123`, name **Alice** → **Connect**. Show the lobby with Alice. |
| 0:25 | **Client 2 connects** | Second `python3 client.py` → join as **Bob** with the same access code. Both see each other in the lobby (data exchange / lobby_update). |
| 0:35 | **Ready up** | Click **Ready** on both. Server log shows both ready and the match starting. |
| 0:45 | **Round 1 (normal)** | Red "Wait for green…" → green "Click!" → click both. Show round results + leaderboard. |
| 1:05 | **Round 2 (false start)** | On one client, click **during red**. Show the orange "Penalty: Too soon!" screen and 0 points that round. |
| 1:25 | **Finish + winner** | Let remaining rounds finish (cut in editing). Show the **Game Over** podium, final leaderboard, and personal stats. |
| 1:40 | **Rematch (optional)** | Click **Ready for Rematch** on both to show a new match starts without restarting the server. |
| 1:50 | **Terminate** | Click **Quit** on a client (server logs the disconnect), then **Ctrl+C** the server (clients are notified of shutdown). |
| 2:00 | **Wrap** | Summarize: TCP connection setup, JSON data exchange, fair server-timed gameplay, false-start handling, leaderboard/winner, and clean disconnect. |

---

## Optional v2 Highlights (if you have extra time)

- **Bots for a solo demo:** **Create Room** → add an *Average Bot* and a *Pro Bot*
  from the lobby → Ready → watch bots react and appear on the leaderboard.
- **Game modes:** create a room with **Elimination** or **Chaos** to show variety.
- **Practice mode:** from the landing screen, **Practice Mode** works with **no
  server running** and tracks your best/average locally.

---

## Suggested Voiceover Lines

1. "We start the TCP server on localhost port 5000 with access code RED123."
2. "Alice connects and joins the lobby; the server confirms her join."
3. "Bob joins the same lobby — both players see each other via lobby updates."
4. "Both click Ready, so the server automatically starts the match."
5. "Round one: wait for red, then click on green. The server measures our times
   and awards points."
6. "Now I'll click too early to trigger the false-start penalty — zero points."
7. "After the final round, here's the podium, leaderboard, and my personal stats."
8. "We can rematch instantly — no server restart needed."
9. "Finally, we quit a client cleanly and shut the server down with Ctrl+C."

---

## Recording Tips

- Use **localhost** so latency is negligible and timing feels crisp.
- Arrange windows side-by-side so both clients and the server log are visible.
- To shorten, fast-forward the middle rounds and focus on Rounds 1, 2, and the finish.
