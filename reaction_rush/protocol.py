"""
protocol.py — Newline-delimited JSON wire protocol (v2).

Design goals
------------
* **Backward compatible.** v1 used flat messages like ``{"type": "ready"}``.
  Those still work unchanged. ``make_message`` still returns a flat dict.
* **Safer.** Added a maximum message size, defensive JSON parsing, and a
  ``validate_message`` helper.
* **Richer (optional).** ``make_envelope`` produces v2 messages carrying a
  ``version`` and optional ``request_id`` while remaining plain dicts, so a
  v1 peer that ignores unknown keys still interoperates.

Every message is a single JSON object serialised on one line and terminated
by ``\\n``. TCP is a byte stream, so ``receive_messages`` buffers partial
data and splits on the newline delimiter.
"""

import json
import socket
import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import constants as C

# Re-export the v1/v2 message-type constants so existing imports keep working:
#   from reaction_rush.protocol import MSG_JOIN_REQUEST, ...
from .constants import (  # noqa: F401  (re-exported for callers)
    MSG_JOIN_REQUEST, MSG_READY, MSG_CLICK, MSG_DISCONNECT,
    MSG_JOIN_RESPONSE, MSG_LOBBY_UPDATE, MSG_GAME_START,
    MSG_ROUND_PREPARE, MSG_ROUND_GO, MSG_PENALTY, MSG_ROUND_RESULT,
    MSG_GAME_OVER, MSG_ERROR, MSG_PLAYER_LEFT,
    MSG_CREATE_ROOM, MSG_JOIN_ROOM, MSG_LEAVE_ROOM,
    MSG_ROOM_CREATED, MSG_ROOM_ERROR,
    MSG_REMATCH_READY, MSG_REMATCH_CANCEL, MSG_REMATCH_UPDATE, MSG_NEW_MATCH,
    MSG_ADD_BOT, MSG_REMOVE_BOT, MSG_BOT_ADDED, MSG_BOT_REMOVED,
    MSG_PING, MSG_PONG, MSG_LATENCY,
    MSG_RECONNECT, MSG_RECONNECT_RESPONSE,
    MSG_PLAYER_DISCONNECTED, MSG_PLAYER_RECONNECTED,
    MSG_FAKE_SIGNAL,
    PROTOCOL_VERSION, MAX_MESSAGE_SIZE,
)

# Framing constants (kept identical to v1 for wire compatibility)
DELIMITER = "\n"
ENCODING = "utf-8"
BUFFER_SIZE = 4096


# ============================================================================
# Message construction
# ============================================================================

def make_message(msg_type: str, **kwargs: Any) -> Dict[str, Any]:
    """
    Build a **flat** message dict (v1-compatible).

    ``{"type": msg_type, ...kwargs}``. This is the primary helper used across
    the codebase; it keeps the original v1 shape so old and new peers agree.
    """
    msg: Dict[str, Any] = {"type": msg_type}
    msg.update(kwargs)
    return msg


def make_envelope(
    msg_type: str,
    payload: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a **v2 envelope** message.

    Shape::

        {"type": ..., "version": 2, "request_id": "...", "payload": {...}}

    A v1 peer simply ignores the extra keys, so this stays interoperable.
    Use ``make_envelope`` when you want request/response correlation.
    """
    return {
        "type": msg_type,
        "version": PROTOCOL_VERSION,
        "request_id": request_id or str(uuid.uuid4()),
        "payload": payload or {},
    }


def get_payload(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a message's data regardless of whether it is flat (v1) or an
    envelope (v2). For envelopes the ``payload`` dict is returned; for flat
    messages the message itself (minus ``type``) is returned.
    """
    if isinstance(msg.get("payload"), dict):
        return msg["payload"]
    return {k: v for k, v in msg.items() if k != "type"}


# ============================================================================
# Validation
# ============================================================================

def validate_message(msg: Any) -> bool:
    """
    Return True if *msg* is a well-formed message.

    A valid message is a dict with a non-empty string ``type`` field.
    This guards handlers against malformed / hostile input.
    """
    return (
        isinstance(msg, dict)
        and isinstance(msg.get("type"), str)
        and len(msg["type"]) > 0
    )


# ============================================================================
# Sending
# ============================================================================

def send_message(sock: socket.socket, message: Dict[str, Any]) -> bool:
    """
    Serialise *message* to JSON + newline and send it over *sock*.

    Returns True on success, False if the socket is broken. Oversized
    messages are refused locally to mirror the receive-side size cap.
    """
    try:
        raw = (json.dumps(message) + DELIMITER).encode(ENCODING)
    except (TypeError, ValueError):
        return False
    if len(raw) > MAX_MESSAGE_SIZE:
        # Should never happen for our messages; guard anyway.
        return False
    try:
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
    Read from *sock*, append to *buffer*, and extract complete messages.

    Returns ``(messages, remaining_buffer)`` where *messages* is a list of
    parsed dicts, or **None** when the connection is lost. Malformed JSON
    lines are skipped. If the buffer grows beyond ``MAX_MESSAGE_SIZE``
    without a delimiter (a malicious or broken peer), it is dropped to avoid
    unbounded memory growth.
    """
    try:
        data = sock.recv(BUFFER_SIZE)
        if not data:
            return None, ""
    except socket.timeout:
        return [], buffer
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        return None, ""

    buffer += data.decode(ENCODING, errors="ignore")

    # Guard against an over-long line with no delimiter (buffer flooding).
    if len(buffer) > MAX_MESSAGE_SIZE and DELIMITER not in buffer:
        return [], ""

    messages = _extract_lines(buffer)
    return messages[0], messages[1]


def _extract_lines(buffer: str) -> Tuple[List[Dict[str, Any]], str]:
    """Split *buffer* on the delimiter and parse each complete line."""
    messages: List[Dict[str, Any]] = []
    while DELIMITER in buffer:
        line, buffer = buffer.split(DELIMITER, 1)
        line = line.strip()
        if not line:
            continue
        if len(line) > MAX_MESSAGE_SIZE:
            # Skip an implausibly large single frame.
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if validate_message(obj):
            messages.append(obj)
    return messages, buffer


def decode_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single JSON line into a validated message dict.

    Returns None for blank, malformed, oversized, or invalid input. Useful
    for tests and for parsing without a live socket.
    """
    line = line.strip()
    if not line or len(line) > MAX_MESSAGE_SIZE:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if validate_message(obj) else None
