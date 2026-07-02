"""Tests for the wire protocol (framing, validation, size limits)."""

import json
import socket

from reaction_rush import protocol as P
from reaction_rush import constants as C


class FakeSocket:
    """A minimal socket stand-in that yields preset byte chunks from recv."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def recv(self, _bufsize):
        if self._chunks:
            return self._chunks.pop(0)
        raise socket.timeout()


def test_make_message_is_flat_v1():
    msg = P.make_message(C.MSG_READY, foo=1)
    assert msg == {"type": "ready", "foo": 1}


def test_make_envelope_has_version_and_payload():
    env = P.make_envelope(C.MSG_CLICK, {"early": True})
    assert env["version"] == C.PROTOCOL_VERSION
    assert env["payload"] == {"early": True}
    assert "request_id" in env


def test_get_payload_handles_both_shapes():
    flat = P.make_message(C.MSG_CLICK, early=True)
    env = P.make_envelope(C.MSG_CLICK, {"early": True})
    assert P.get_payload(flat) == {"early": True}
    assert P.get_payload(env) == {"early": True}


def test_validate_message():
    assert P.validate_message({"type": "ready"}) is True
    assert P.validate_message({"no_type": 1}) is False
    assert P.validate_message("not a dict") is False
    assert P.validate_message({"type": ""}) is False


def test_decode_line_valid_and_invalid():
    assert P.decode_line('{"type": "ready"}') == {"type": "ready"}
    assert P.decode_line("not json") is None
    assert P.decode_line("") is None
    assert P.decode_line('{"no_type": 1}') is None


def test_receive_single_message():
    line = json.dumps({"type": "ready"}) + "\n"
    sock = FakeSocket([line.encode("utf-8")])
    msgs, buf = P.receive_messages(sock, "")
    assert msgs == [{"type": "ready"}]
    assert buf == ""


def test_receive_partial_then_complete():
    full = json.dumps({"type": "ready"}) + "\n"
    part1, part2 = full[:5], full[5:]
    sock = FakeSocket([part1.encode(), part2.encode()])
    msgs, buf = P.receive_messages(sock, "")
    assert msgs == []          # incomplete so far
    msgs, buf = P.receive_messages(sock, buf)
    assert msgs == [{"type": "ready"}]


def test_receive_multiple_messages_at_once():
    line = (json.dumps({"type": "a"}) + "\n"
            + json.dumps({"type": "b"}) + "\n")
    sock = FakeSocket([line.encode()])
    msgs, _ = P.receive_messages(sock, "")
    assert [m["type"] for m in msgs] == ["a", "b"]


def test_receive_skips_invalid_json():
    line = "not-json\n" + json.dumps({"type": "ok"}) + "\n"
    sock = FakeSocket([line.encode()])
    msgs, _ = P.receive_messages(sock, "")
    assert msgs == [{"type": "ok"}]


def test_receive_none_on_closed_connection():
    sock = FakeSocket([b""])          # empty recv = closed
    msgs, buf = P.receive_messages(sock, "")
    assert msgs is None


def test_oversized_line_is_dropped():
    huge = ("x" * (C.MAX_MESSAGE_SIZE + 10)) + "\n"
    sock = FakeSocket([huge.encode()])
    msgs, buf = P.receive_messages(sock, "")
    # No valid message extracted; must not raise.
    assert msgs == []


def test_unknown_message_type_does_not_crash():
    line = json.dumps({"type": "totally_unknown", "x": 1}) + "\n"
    sock = FakeSocket([line.encode()])
    msgs, _ = P.receive_messages(sock, "")
    assert msgs == [{"type": "totally_unknown", "x": 1}]
