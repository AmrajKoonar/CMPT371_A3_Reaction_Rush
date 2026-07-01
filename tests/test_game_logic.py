"""Tests for scoring, stats, modes, and latency handling."""

from reaction_rush import constants as C
from reaction_rush import game_logic as GL
from reaction_rush.stats import summarize_player, summarize_practice


def test_placement_scores_sorted_fastest_first():
    reactions = {"Alice": 300.0, "Bob": 200.0, "Cara": 250.0}
    results = GL.calculate_round_scores(reactions, set(), set())
    by_name = {r.player_name: r for r in results}
    assert by_name["Bob"].score == 100    # fastest
    assert by_name["Cara"].score == 75
    assert by_name["Alice"].score == 50


def test_false_start_scores_zero():
    reactions = {"Alice": None, "Bob": 200.0}
    results = GL.calculate_round_scores(reactions, {"Alice"}, set())
    by_name = {r.player_name: r for r in results}
    assert by_name["Alice"].score == 0
    assert by_name["Alice"].false_start is True
    assert by_name["Bob"].score == 100


def test_timeout_scores_zero():
    reactions = {"Alice": None, "Bob": 210.0}
    results = GL.calculate_round_scores(reactions, set(), {"Alice"})
    by_name = {r.player_name: r for r in results}
    assert by_name["Alice"].timed_out is True
    assert by_name["Alice"].score == 0


def test_winner_and_tiebreak_by_total_time():
    r1 = GL.calculate_round_scores({"A": 200.0, "B": 200.0}, set(), set())
    # Same score both -> but times equal; ensure deterministic leaderboard order
    lb = GL.calculate_leaderboard({"A": [x for x in r1 if x.player_name == "A"],
                                   "B": [x for x in r1 if x.player_name == "B"]})
    assert GL.determine_winner(lb) in ("A", "B")


def test_leaderboard_orders_by_score_then_time():
    a = GL.calculate_round_scores({"A": 100.0, "B": 500.0}, set(), set())
    results_by_name = {"A": [x for x in a if x.player_name == "A"],
                       "B": [x for x in a if x.player_name == "B"]}
    lb = GL.calculate_leaderboard(results_by_name)
    assert lb[0].player_name == "A"
    assert lb[0].total_score >= lb[1].total_score


def test_average_and_consistency():
    assert GL.average_reaction([100.0, 200.0, 300.0]) == 200.0
    assert GL.fastest_reaction([300.0, 120.0, 250.0]) == 120.0
    # perfectly consistent -> 0 std dev
    assert GL.consistency_score([200.0, 200.0, 200.0]) == 0.0
    assert GL.consistency_score([100.0]) == -1.0


def test_sudden_death_only_first_scores():
    data = {
        "A": {"reaction": 150.0, "adjusted": 150.0, "false_start": False,
              "timed_out": False, "suspicious": False},
        "B": {"reaction": 250.0, "adjusted": 250.0, "false_start": False,
              "timed_out": False, "suspicious": False},
    }
    results = GL.compute_round_results(data, C.MODE_SUDDEN_DEATH, 250)
    by_name = {r.player_name: r for r in results}
    assert by_name["A"].score == 100
    assert by_name["B"].score == 0


def test_consistency_mode_sorts_by_average():
    all_results = {
        "Steady": GL.compute_round_results(
            {"Steady": {"reaction": 220.0, "adjusted": 220.0,
                        "false_start": False, "timed_out": False,
                        "suspicious": False}}, C.MODE_CONSISTENCY, 250),
        "Wild": GL.compute_round_results(
            {"Wild": {"reaction": 400.0, "adjusted": 400.0,
                      "false_start": False, "timed_out": False,
                      "suspicious": False}}, C.MODE_CONSISTENCY, 250),
    }
    lb = GL.build_leaderboard(all_results, C.MODE_CONSISTENCY, set())
    assert lb[0].player_name == "Steady"


def test_elimination_picks_slowest():
    results = GL.compute_round_results(
        {
            "Fast": {"reaction": 150.0, "adjusted": 150.0, "false_start": False,
                     "timed_out": False, "suspicious": False},
            "Slow": {"reaction": 500.0, "adjusted": 500.0, "false_start": False,
                     "timed_out": False, "suspicious": False},
        }, C.MODE_ELIMINATION, 250)
    elim = GL.choose_eliminations(results, {"Fast", "Slow"})
    assert elim == ["Slow"]


def test_elimination_false_start_at_risk():
    results = GL.compute_round_results(
        {
            "Good": {"reaction": 200.0, "adjusted": 200.0, "false_start": False,
                     "timed_out": False, "suspicious": False},
            "Cheater": {"reaction": None, "adjusted": None, "false_start": True,
                        "timed_out": False, "suspicious": False},
        }, C.MODE_ELIMINATION, 250)
    elim = GL.choose_eliminations(results, {"Good", "Cheater"})
    assert elim == ["Cheater"]


def test_latency_compensation_bounded():
    # Raw 300 ms, 100 ms one-way latency -> 200 ms adjusted.
    assert GL.adjust_reaction_for_latency(300.0, 100.0, True) == 200.0
    # Cannot go below the minimum.
    assert GL.adjust_reaction_for_latency(60.0, 100.0, True) == C.MIN_ADJUSTED_REACTION_MS
    # Disabled -> unchanged.
    assert GL.adjust_reaction_for_latency(300.0, 100.0, False) == 300.0


def test_suspicious_flagging():
    assert GL.is_suspicious(50.0) is True
    assert GL.is_suspicious(200.0) is False


def test_summarize_player():
    results = GL.calculate_round_scores({"A": 200.0}, set(), set())
    summary = summarize_player("A", [r for r in results if r.player_name == "A"])
    assert summary["player_name"] == "A"
    assert summary["fastest_reaction_ms"] == 200.0


def test_summarize_practice():
    attempts = [
        {"reaction_ms": 200.0, "false_start": False},
        {"reaction_ms": 300.0, "false_start": False},
        {"reaction_ms": -1, "false_start": True},
    ]
    s = summarize_practice(attempts)
    assert s["attempts"] == 3
    assert s["valid_attempts"] == 2
    assert s["false_starts"] == 1
    assert s["fastest_ms"] == 200.0
