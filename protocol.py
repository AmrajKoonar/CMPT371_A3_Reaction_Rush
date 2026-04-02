"""
protocol.py — Network message protocol for Reaction Rush.

All client-server communication uses **newline-delimited JSON** over TCP.
Every message is a Python dict serialised as a single JSON line, terminated
by '\\n'.  A mandatory ``"type"`` field identifies the message kind.

This module provides:
    * Constants for every message type used in the game.
    * ``make_message``  — build a message dict from keyword args.
    * ``send_message``  — serialise + transmit in one call.
    * ``receive_messages`` — stream-safe reader that handles TCP
      fragmentation and buffering.
"""

import json
import socket
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# Message-type constants
# ============================================================================
# Client → Server
MSG_JOIN_REQUEST  = "join_request"      # player wants to enter the lobby
MSG_READY         = "ready"             # player is ready to start
MSG_CLICK         = "click"             # player clicked during a round
MSG_DISCONNECT    = "disconnect"        # clean client shutdown

# Server → Client
MSG_JOIN_RESPONSE = "join_response"     # accept / reject a join request
MSG_LOBBY_UPDATE  = "lobby_update"      # current player list + ready flags
MSG_GAME_START    = "game_start"        # game is about to begin
MSG_ROUND_PREPARE = "round_prepare"     # show the red screen
MSG_ROUND_GO      = "round_go"          # switch to green — react now!
MSG_PENALTY       = "penalty"           # false-start confirmation
MSG_ROUND_RESULT  = "round_result"      # per-round scores & leaderboard
MSG_GAME_OVER     = "game_over"         # final standings + winner
MSG_ERROR         = "error"             # generic server error
MSG_PLAYER_LEFT   = "player_left"       # another player disconnected

# ============================================================================
# Framing constants
# ============================================================================
DELIMITER   = "\n"       # each JSON message ends with a newline
ENCODING    = "utf-8"    # text encoding for the wire
BUFFER_SIZE = 4096       # bytes per recv() call


# ============================================================================
# Message construction
# ============================================================================

def make_message(msg_type: str, **kwargs: Any) -> Dict[str, Any]:
    """
    Build a message dict.

    Parameters
    ----------
    msg_type : str
        One of the ``MSG_*`` constants above.
    **kwargs
        Arbitrary payload fields appended to the message.

    Returns
    -------
    dict
        ``{"type": msg_type, ...kwargs}``
    """
    msg: Dict[str, Any] = {"type": msg_type}
    msg.update(kwargs)
    return msg


# ============================================================================
# Sending
# ============================================================================

def send_message(sock: socket.socket, message: Dict[str, Any]) -> bool:
    """
    Serialise *message* as JSON + newline and send it over *sock*.

    Uses ``sendall`` so the entire payload is guaranteed to be transmitted
    (or an error is raised).

    Returns
    -------
    bool
        ``True`` on success, ``False`` if the socket is broken.
    """
    try:
        raw = (json.dumps(message) + DELIMITER).encode(ENCODING)
        sock.sendall(raw)
        return True
    except (BrokenPipeError, ConnectionResetError,
            ConnectionAbortedError, OSError):
        return False


# ============================================================================
# Receiving
# ============================================================================

def receive_messages(
    sock: socket.socket,
    buffer: str,
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """
    Read data from *sock*, append to *buffer*, and extract complete messages.

    Because TCP is a **stream** protocol, a single ``recv`` may deliver a
    partial message, exactly one message, or several concatenated messages.
    This function accumulates data in *buffer* and splits on ``DELIMITER``
    to yield zero or more fully-parsed dicts.

    Parameters
    ----------
    sock : socket.socket
        Connected TCP socket (may have a timeout set).
    buffer : str
        Leftover bytes from the previous call.

    Returns
    -------
    (messages, remaining_buffer)
        *messages* is a list of parsed dicts, or **None** when the
        connection has been lost (remote close or socket error).
        *remaining_buffer* carries any trailing bytes for the next call.
    """
    try:
        data = sock.recv(BUFFER_SIZE)
        if not data:
            # Empty recv → remote side closed the connection
            return None, ""
    except socket.timeout:
        # No data available yet — not an error
        return [], buffer
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        return None, ""

    buffer += data.decode(ENCODING)
    messages: List[Dict[str, Any]] = []

    while DELIMITER in buffer:
        line, buffer = buffer.split(DELIMITER, 1)
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "type" in obj:
                messages.append(obj)
            # Non-dict or missing "type" → silently discard
        except json.JSONDecodeError:
            # Malformed JSON → skip without crashing
            pass

    return messages, buffer
