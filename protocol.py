"""
protocol.py — Backward-compatibility shim.

The canonical implementation now lives in ``reaction_rush.protocol``. This
module re-exports it so any legacy import (``import protocol`` /
``from protocol import send_message``) keeps working unchanged.
"""

from reaction_rush.protocol import *  # noqa: F401,F403
from reaction_rush.protocol import (  # noqa: F401  (explicit for tooling)
    make_message, make_envelope, get_payload, validate_message,
    send_message, receive_messages, decode_line,
    DELIMITER, ENCODING, BUFFER_SIZE,
)
