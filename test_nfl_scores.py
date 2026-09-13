from datetime import datetime, timezone

import pytest

import nfl_scores as ns


# --------------------------------------------------------------------------- current_season

def test_current_season_before_march_belongs_to_previous_year():
    assert ns.current_season(datetime(2027, 2, 1, tzinfo=timezone.utc)) == 2026


def test_current_season_on_or_after_march_belongs_to_this_year():
    assert ns.current_season(datetime(2026, 9, 13, tzinfo=timezone.utc)) == 2026


# --------------------------------------------------------------------------- _normalize

def test_normalize_maps_espn_washington_spelling():
    assert ns._normalize("wsh") == "WAS"


def test_normalize_passes_through_unmapped_teams():
    assert ns._normalize("buf") == "BUF"


# --------------------------------------------------------------------------- _parse_event

def _event(home_abbr, away_abbr, home_score=None, away_score=None, completed=False):
    def side(abbr, score):
        return {
            "homeAway": "home" if abbr == home_abbr else "away",
            "team": {"abbreviation": abbr},
            "score": None if score is None else str(score),
        }

    return {
        "id": "401",
        "date": "2026-09-13T17:00Z",
        "competitions": [{
            "competitors": [side(home_abbr, home_score), side(away_abbr, away_score)],
            "status": {"type": {
                "completed": completed,
                "state": "post" if completed else "pre",
                "shortDetail": "Final" if completed else "7:00 PM",
            }},
        }],
    }


def test_parse_event_normalizes_home_team_and_detects_winner():
    game = ns._parse_event(_event("WSH", "DAL", 24, 17, completed=True), week=1)
    assert game["home"] == "WAS"
    assert game["winner"] == "WAS"
    assert not game["tie"]


def test_parse_event_detects_tie():
    game = ns._parse_event(_event("BUF", "NYJ", 20, 20, completed=True), week=1)
    assert game["tie"]
    assert game["winner"] is None


def test_parse_event_leaves_future_game_unscored():
    game = ns._parse_event(_event("BUF", "NYJ"), week=5)
    assert not game["completed"]
    assert game["home_score"] is None
    assert game["winner"] is None
    assert game["week"] == 5


def test_parse_event_returns_none_without_both_sides():
    event = {"competitions": [{"competitors": [
        {"homeAway": "home", "team": {"abbreviation": "BUF"}, "score": None},
    ]}]}
    assert ns._parse_event(event, week=1) is None


def test_parse_event_returns_none_without_competitions():
    assert ns._parse_event({"competitions": []}, week=1) is None


# --------------------------------------------------------------------------- _weeks_needing_refresh
#
# This is the function behind the bug where the season projection collapsed to
# near-banked-points totals: it used to cap its range at `through_week`, so a
# week's schedule was never fetched until the season had already reached it,
# leaving the projection with no future games to simulate.

def test_weeks_needing_refresh_pulls_never_fetched_future_weeks():
    cached = [
        {"week": 1, "completed": True},
        {"week": 2, "completed": True},
    ]
    weeks = ns._weeks_needing_refresh(cached, through_week=2)
    assert set(range(3, ns.WEEKS + 1)) <= set(weeks)


def test_weeks_needing_refresh_skips_settled_past_weeks():
    cached = [{"week": w, "completed": True} for w in range(1, ns.WEEKS + 1) for _ in range(2)]
    assert ns._weeks_needing_refresh(cached, through_week=ns.WEEKS) == []


def test_weeks_needing_refresh_refetches_the_in_progress_current_week():
    cached = [
        {"week": 1, "completed": True},
        {"week": 2, "completed": True},
        {"week": 2, "completed": False},
    ]
    assert 2 in ns._weeks_needing_refresh(cached, through_week=2)


def test_weeks_needing_refresh_does_not_repeatedly_refetch_cached_future_schedules():
    """Once a future week's schedule is known, it shouldn't be re-requested on
    every poll just because none of its games have been played yet. The current
    week is a different story: it's in progress, so it stays in the list."""
    cached = [{"week": w, "completed": False} for w in range(1, ns.WEEKS + 1)]
    weeks = ns._weeks_needing_refresh(cached, through_week=1)
    assert weeks == [1]


def test_weeks_needing_refresh_with_empty_cache_wants_every_week():
    assert ns._weeks_needing_refresh([], through_week=1) == list(range(1, ns.WEEKS + 1))


# --------------------------------------------------------------------------- describe

def test_describe_completed_game():
    game = {"completed": True, "tie": False, "winner": "BUF", "home": "BUF", "away": "NYJ",
            "home_score": 24, "away_score": 17}
    assert ns.describe(game) == "BUF beat NYJ 24-17"


def test_describe_tie():
    game = {"completed": True, "tie": True, "home": "BUF", "away": "NYJ",
            "home_score": 20, "away_score": 20, "winner": None}
    assert ns.describe(game) == "BUF and NYJ tied 20-20"


def test_describe_future_game():
    game = {"completed": False, "home": "BUF", "away": "NYJ", "status": "7:00 PM"}
    assert ns.describe(game) == "NYJ at BUF (7:00 PM)"


# --------------------------------------------------------------------------- completed_games

def test_completed_games_filters_out_unplayed():
    data = {"games": [{"completed": True}, {"completed": False}]}
    assert ns.completed_games(data) == [{"completed": True}]


# --------------------------------------------------------------------------- load/save results

def test_save_and_load_results_roundtrip(tmp_path):
    path = tmp_path / "results.json"
    data = {"season": 2026, "fetched_at": "now", "games": [{"id": "1"}]}
    ns.save_results(data, path)
    assert ns.load_results(path) == data


def test_load_results_missing_file_returns_empty_shell(tmp_path):
    path = tmp_path / "missing.json"
    assert ns.load_results(path) == {"season": None, "fetched_at": None, "games": []}
