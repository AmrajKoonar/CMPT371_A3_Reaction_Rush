"""
protocol.py

Shared message helpers for the client and server.

This file defines:
- message type names
- JSON send helper
- message receive helper that rebuilds full lines from TCP data
"""

import json
import socket
from typing import Any, Dict, List, Optional, Tuple

# Client → Server
MSG_JOIN_REQUEST  = "join_request"
MSG_READY         = "ready"
MSG_CLICK         = "click"
MSG_DISCONNECT    = "disconnect"

# Server → Client
MSG_JOIN_RESPONSE = "join_response"
MSG_LOBBY_UPDATE  = "lobby_update"
MSG_GAME_START    = "game_start"
MSG_ROUND_PREPARE = "round_prepare"
MSG_ROUND_GO      = "round_go"
MSG_PENALTY       = "penalty"
MSG_ROUND_RESULT  = "round_result"
MSG_GAME_OVER     = "game_over"
MSG_ERROR         = "error"
MSG_PLAYER_LEFT   = "player_left"

DELIMITER   = "\n"       # we split messages by newline
ENCODING    = "utf-8"
BUFFER_SIZE = 4096

def make_message(msg_type: str, **kwargs: Any) -> Dict[str, Any]:
    """Create one message dictionary with a type and payload"""
    msg: Dict[str, Any] = {"type": msg_type}
    msg.update(kwargs)
    return msg

def send_message(sock: socket.socket, message: Dict[str, Any]) -> bool:
    """Send one JSON message over the socket using a newline delimiter"""
    try:
        raw = (json.dumps(message) + DELIMITER).encode(ENCODING)
        sock.sendall(raw)
        return True
    except (BrokenPipeError, ConnectionResetError,
            ConnectionAbortedError, OSError):
        return False

def receive_messages(
    sock: socket.socket,
    buffer: str,
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Read from the socket and return any full JSON messages found"""
    try:
        data = sock.recv(BUFFER_SIZE)
        if not data:
            return None, ""
    except socket.timeout:
        return [], buffer
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        return None, ""

    buffer += data.decode(ENCODING)
    messages: List[Dict[str, Any]] = []

    # TCP can give partial or multiple messages at once, so we split by newline
    while DELIMITER in buffer:
        line, buffer = buffer.split(DELIMITER, 1)
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "type" in obj:
                messages.append(obj)
        except json.JSONDecodeError:
            pass

    return messages, buffer
