"""Tests for the API layer in main.py.

The endpoints are plain functions, so they are called directly: that keeps the
test dependencies to pytest alone, the same way the rest of the repo runs on
the standard library.
"""
import json

import pytest

import main
import nfl_scores
from test_season import make_game

# The scheduled warm-up job calls /api/season/refresh, and the cron service
# rejects ("Response data too big") and eventually disables a job whose response
# runs long; the full season payload, which this endpoint used to return, is
# ~65 KB. A summary of a handful of scalars has no business approaching that, so
# hold it to a kilobyte and the endpoint can never grow back into the failure.
REFRESH_RESPONSE_BUDGET = 1024


@pytest.fixture
def results():
    return {
        "season": 2026,
        "fetched_at": "2026-09-13T16:00:00Z",
        "games": [
            make_game("1", 1, "BUF", "KC", 24, 17, completed=True),
            make_game("2", 1, "SEA", "DAL", 20, 20, completed=True),
            make_game("3", 2, "KC", "SEA"),
        ],
    }


@pytest.fixture(autouse=True)
def clear_season_cache():
    main._season_cache.update({"fingerprint": None, "state": None})
    yield
    main._season_cache.update({"fingerprint": None, "state": None})


def test_refresh_returns_a_summary_not_the_season_payload(monkeypatch, results):
    monkeypatch.setattr(nfl_scores, "refresh", lambda: results)

    body = main.refresh_season()

    assert body["ok"] is True
    assert body["season"] == 2026
    assert body["fetched_at"] == "2026-09-13T16:00:00Z"
    assert body["games_played"] == 2
    assert body["games_total"] == 3
    assert body["weeks_played"] == [1]
    # The heavy keys belong to GET /api/season; shipping them here is what got
    # the scheduled job disabled.
    assert not {"games", "leaderboard", "history"} & set(body)
    assert len(json.dumps(body)) < REFRESH_RESPONSE_BUDGET


def test_refresh_still_fills_the_cache_that_get_season_reads(monkeypatch, results):
    monkeypatch.setattr(nfl_scores, "refresh", lambda: results)
    main.refresh_season()

    # load_results() returning nothing proves the payload came from the cache
    # the refresh filled, not from a second trip to ESPN.
    monkeypatch.setattr(nfl_scores, "load_results", lambda: results)
    monkeypatch.setattr(nfl_scores, "refresh", _unreachable)

    state = main.get_season()
    assert state["games_played"] == 2
    assert len(state["games"]) == 3
    assert [entry["rank"] for entry in state["leaderboard"]][0] == 1


def test_get_season_pulls_from_espn_when_the_cache_is_empty(monkeypatch, results):
    monkeypatch.setattr(nfl_scores, "load_results", lambda: {"season": 2026, "games": []})
    monkeypatch.setattr(nfl_scores, "refresh", lambda: results)

    state = main.get_season()
    assert state["games_total"] == 3
    assert state["leaderboard"]


@pytest.mark.parametrize("endpoint", [lambda: main.refresh_season(), lambda: main.get_season()])
def test_a_failed_espn_fetch_becomes_a_502(monkeypatch, endpoint):
    monkeypatch.setattr(nfl_scores, "load_results", lambda: {"season": 2026, "games": []})

    def boom():
        raise nfl_scores.ScoreFetchError("ESPN said no")

    monkeypatch.setattr(nfl_scores, "refresh", boom)

    with pytest.raises(main.HTTPException) as excinfo:
        endpoint()
    assert excinfo.value.status_code == 502
    assert "ESPN said no" in excinfo.value.detail


def _unreachable():
    raise AssertionError("refresh() should not be called when the cache is warm")
