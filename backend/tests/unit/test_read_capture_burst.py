"""Directive v11 M2: the capture burst is judged on captured == due, the lowest
working-set headroom (>= 100 MB), and no restart since the burst began."""

from __future__ import annotations

from scripts.read_capture_burst import summarize


def _health(passes, uptime=20_000, timestamp="2026-10-09T19:30:00+00:00"):
    return {
        "timestamp": timestamp,
        "uptime_seconds": uptime,
        "components": {"prediction_capture": {"recent": passes}},
    }


def _pass(due=1, captured=1, headroom=150):
    return {
        "due": due,
        "captured": captured,
        "errors": due - captured,
        "duration_ms": 900.0,
        "rss_mb": 360,
        "working_set_mb": 512 - headroom,
        "anon_mb": 300,
        "headroom_mb": headroom,
    }


def test_a_clean_burst_passes():
    report = summarize(_health([_pass(), _pass(due=2, captured=2, headroom=120)]), since="2026-10-09T15:00:00Z")
    assert report["verdict"] == "PASS"
    assert (report["due"], report["captured"], report["min_headroom_mb"]) == (3, 3, 120)


def test_the_lowest_headroom_decides_not_the_last_reading():
    report = summarize(_health([_pass(headroom=90), _pass(headroom=170)]))
    assert report["checks"]["peak_headroom_ok"] is False
    assert report["verdict"] == "FAIL"


def test_a_missed_capture_fails():
    assert summarize(_health([_pass(due=2, captured=1)]))["verdict"] == "FAIL"


def test_a_restart_during_the_burst_fails():
    # Up 1 hour at 19:30 means it restarted after 15:00; the history before that is gone.
    report = summarize(_health([_pass()], uptime=3_600), since="2026-10-09T15:00:00Z")
    assert report["checks"]["no_restart_since"] is False
    assert report["verdict"] == "FAIL"


def test_missing_memory_figures_are_incomplete_not_a_pass():
    passes = [{"due": 1, "captured": 1, "headroom_mb": None}]
    assert summarize(_health(passes))["verdict"] == "INCOMPLETE"


def test_nothing_to_read_yet():
    assert summarize(_health([]))["verdict"] == "NO_DATA"


def test_quota_is_reported_for_m3():
    evidence = {"providers": {"the_odds_api": {"quota": {"remaining": 194, "cost": 306}}}}
    report = summarize(_health([_pass()]), evidence)
    assert (report["odds_quota_remaining"], report["odds_quota_used"]) == (194, 306)
