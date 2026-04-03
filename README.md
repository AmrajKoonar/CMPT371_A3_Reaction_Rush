# CMPT 371 A3 Socket Programming `Reaction Rush`

**Course:** CMPT 371 - Data Communications & Networking  
**Instructor:** Mirza Zaeem Baig  
**Semester:** Spring 2026  
**RUBRIC NOTE:** As per submission guidelines, only one group member should submit the repository link on Canvas.

## **Group Members**

| Name | Student ID | Email | GitHub Username |
| :---- | :---- | :---- | :---- |
| Geonwoo Park | 301635420 | gpa40@sfu.ca |   aidenplabs |
| Amraj Koonar | 301559468 | ask36@sfu.ca |   AmrajKoonar |

## **1. Project Overview & Description**

This project is a multiplayer reaction game built using Python's Socket API with
TCP. It uses a client-server architecture where one server manages the game and
multiple clients connect to the same lobby.

Each player opens the client, enters the host, port, access code, and a player
name, then joins the lobby. When at least 2 players connect and click `Ready`,
the server starts a 5-round reaction game. The server handles round timing,
false start checks, score calculation, leaderboard updates, and final winner
selection.

This version is designed for one game session per server run.
To play again, restart the server and reconnect the clients.

## **2. System Limitations & Edge Cases**

As required by the project specifications, we identified the following limits
and edge cases in the current project scope:

* **Lobby / player count:**  
  * **Current behavior:** The game starts only when at least 2 connected players are ready.  
  * **Limitation:** This project is mainly intended for a small localhost or LAN demo, not large public use.
* **Network delay:**  
  * **Current behavior:** The server measures reaction times and sends results to every client.  
  * **Limitation:** Measured reaction time includes network delay, so players on slower connections may be slightly disadvantaged.
* **TCP message handling:**  
  * **Current behavior:** Messages are sent as newline-delimited JSON so the client and server can separate complete TCP messages correctly.
* **Disconnects:**  
  * **Current behavior:** If a player disconnects, the server notifies the remaining clients.  
  * **Limitation:** If too few players remain, the current game ends early.
* **Security / deployment:**  
  * **Limitation:** There is no encryption, account system, or strong authentication beyond the lobby access code.
* **GUI dependency:**  
  * **Limitation:** The client uses Tkinter, so Tkinter must be available on the machine running the client.

## **3. Video Demo**

**RUBRIC NOTE:** Include a clickable link.  
Our 2-minute video demonstration covering connection establishment, data
exchange, gameplay, and process termination can be viewed below:  
[**Add video link here**]

## **4. Prerequisites (Fresh Environment)**

To run this project, you need:

* **Python 3.8** or higher  
* No external pip installations are required for the main project  
* **Tkinter** must be available for the client GUI  
* On macOS, use `python3` if `python` does not point to Python 3
* On Windows, `python` may already point to Python 3, but if not, use `py` or `python3` depending on your setup.
If you are on Linux and Tkinter is missing:

```bash
sudo apt install python3-tk
```

## **5. Step-by-Step Run Guide**

**RUBRIC NOTE:** The grader should be able to copy-paste these commands.

Open **3 terminals** in the project folder: one for the server and two for the
clients.

### **Step 1: Start the Server**

```bash
python3 server.py --host 127.0.0.1 --port 5000 --access-code RED123 --min-players 2
```

This starts the TCP server on `127.0.0.1:5000` and waits for at least 2 players
to join and click `Ready`.

### **Step 2: Start Client 1**

```bash
python3 client.py
```

In the client window, enter:

* Host: `127.0.0.1`
* Port: `5000`
* Access Code: `RED123`
* Player Name: any unique player name

Then click `Connect`, and after joining the lobby, click `Ready`.

### **Step 3: Start Client 2**

```bash
python3 client.py
```

Enter the same host, port, and access code. Use a different player name. Then
click `Connect` and `Ready`.

### **Step 4: Gameplay**

1. Once at least 2 players are ready, the server starts the game automatically.  
2. Each round begins with a red screen.  
3. Wait until the screen turns green, then click.  
4. If a player clicks too early, that player gets a false start penalty.  
5. After each round, the server sends the round results and leaderboard.  
6. After 5 rounds, the final winner is shown.  

## **6. Connection / Data Exchange / Termination**

* **Connection establishment:**  
  * Each client opens a TCP connection to the server and sends a `join_request`.
* **Data exchange:**  
  * The server and clients exchange lobby updates, ready messages, round start messages, click messages, round results, leaderboard data, and final game over messages.
* **Termination:**  
  * A client can close its window and disconnect.  
  * The server can be stopped with `Ctrl+C`.  
  * Clients are notified when the server shuts down.

## **7. Technical Protocol Details (JSON over TCP)**

This project uses a simple application-layer protocol with newline-delimited
JSON messages over TCP.

* **Message format:** `{"type": <string>, ...}`
* **Examples used in the project:**  
  * Client sends: `{"type": "join_request", "player_name": "Alice", "access_code": "RED123"}`  
  * Server sends: `{"type": "join_response", "success": true, ...}`  
  * Client sends: `{"type": "ready"}`  
  * Server sends: `{"type": "round_prepare", ...}`  
  * Server sends: `{"type": "round_go", ...}`  
  * Client sends: `{"type": "click", "early": false, ...}`  
  * Server sends: `{"type": "round_result", ...}`  
  * Server sends: `{"type": "game_over", ...}`  

## **8. Academic Integrity & References**

* **Code Origin:**  
  * The project was built as a Python socket programming assignment using TCP sockets, threading, Tkinter, and JSON message passing.
* **GenAI Usage:**  
  * [Add ChatGPT / Copilot usage here]
* **References:**  
  * [Add websites, documentation, or other references here]

