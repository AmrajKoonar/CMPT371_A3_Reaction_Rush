"""Tests for the SQLite persistence layer."""

import os
import tempfile

import pytest

from reaction_rush.persistence import Database


@pytest.fixture()
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    yield database
    database.close()
    try:
        os.remove(path)
    except OSError:
        pass


def test_database_initializes(db):
    # A fresh player is created and returns a stable id.
    pid = db.upsert_player("Alice")
    assert pid
    assert db.upsert_player("Alice") == pid   # idempotent


def test_save_match_and_round(db):
    match_id = db.start_match("RED123", "classic")
    assert match_id
    pid = db.upsert_player("Alice")
    db.save_round_result(match_id, 1, pid, "Alice", 200.0, 190.0, False, 100)
    db.finish_match(match_id, pid, [
        {"player_id": pid, "player_name": "Alice", "total_score": 100},
    ])
    assert db.get_player_match_count("Alice") == 1


def test_practice_results_and_personal_best(db):
    db.save_practice_result("Bob", 250.0, False)
    db.save_practice_result("Bob", 200.0, False)
    db.save_practice_result("Bob", None, True)      # false start
    rows = db.get_practice_results("Bob")
    assert len(rows) == 3
    assert db.get_personal_best("Bob") == 200.0


def test_reset_practice(db):
    db.save_practice_result("Cara", 300.0, False)
    assert db.get_practice_results("Cara")
    db.reset_practice_results("Cara")
    assert db.get_practice_results("Cara") == []
    assert db.get_personal_best("Cara") is None
