import json

import pytest

import season

TEAM_A, TEAM_B, TEAM_C, TEAM_D = "BUF", "KC", "SEA", "DAL"


def make_game(id_, week, home, away, home_score=None, away_score=None, completed=False):
    tie = completed and home_score == away_score
    winner = None
    if completed and not tie:
        winner = home if home_score > away_score else away
    return {
        "id": id_, "week": week, "kickoff": f"2026-09-{week:02d}T13:00Z",
        "home": home, "away": away,
        "home_score": home_score, "away_score": away_score,
        "completed": completed, "winner": winner, "tie": tie,
    }


# --------------------------------------------------------------------------- team_points / team_records

def test_team_points_counts_wins_and_ties():
    games = [
        make_game("1", 1, TEAM_A, TEAM_B, 24, 17, completed=True),
        make_game("2", 1, TEAM_C, TEAM_D, 20, 20, completed=True),
        make_game("3", 2, TEAM_A, TEAM_C, completed=False),
    ]
    points = season.team_points(games)
    assert points[TEAM_A] == 1.0
    assert points[TEAM_B] == 0.0
    assert points[TEAM_C] == 0.5
    assert points[TEAM_D] == 0.5


def test_team_points_respects_through_week():
    games = [
        make_game("1", 1, TEAM_A, TEAM_B, 24, 17, completed=True),
        make_game("2", 2, TEAM_A, TEAM_C, 10, 3, completed=True),
    ]
    assert season.team_points(games, through_week=1)[TEAM_A] == 1.0


def test_team_records_tracks_wins_losses_and_ties():
    games = [
        make_game("1", 1, TEAM_A, TEAM_B, 24, 17, completed=True),
        make_game("2", 1, TEAM_C, TEAM_D, 20, 20, completed=True),
    ]
    records = season.team_records(games)
    assert records[TEAM_A] == {"w": 1, "l": 0, "t": 0}
    assert records[TEAM_B] == {"w": 0, "l": 1, "t": 0}
    assert records[TEAM_C] == {"w": 0, "l": 0, "t": 1}


# --------------------------------------------------------------------------- manager_points

def test_manager_points_sums_across_owned_teams():
    team_owner = {TEAM_A: "m1", TEAM_B: "m1", TEAM_C: "m2"}
    points = {TEAM_A: 2.0, TEAM_B: 1.0, TEAM_C: 3.0}
    assert season.manager_points(team_owner, points) == {"m1": 3.0, "m2": 3.0}


# --------------------------------------------------------------------------- elo_through

def test_elo_through_moves_winner_up_and_loser_down(monkeypatch):
    monkeypatch.setattr(season, "RATINGS", {TEAM_A: 1500, TEAM_B: 1500})
    games = [make_game("1", 1, TEAM_A, TEAM_B, 24, 0, completed=True)]
    elos = season.elo_through(games)
    assert elos[TEAM_A] > 1500
    assert elos[TEAM_B] < 1500


def test_elo_through_ignores_games_after_through_week(monkeypatch):
    monkeypatch.setattr(season, "RATINGS", {TEAM_A: 1500, TEAM_B: 1500})
    games = [make_game("1", 5, TEAM_A, TEAM_B, 24, 0, completed=True)]
    elos = season.elo_through(games, through_week=1)
    assert elos[TEAM_A] == 1500
    assert elos[TEAM_B] == 1500


# --------------------------------------------------------------------------- project

def test_project_with_no_remaining_games_just_returns_banked_points(monkeypatch):
    monkeypatch.setattr(season, "RATINGS", {TEAM_A: 1500, TEAM_B: 1500})
    games = [make_game("1", 1, TEAM_A, TEAM_B, 24, 0, completed=True)]
    team_owner = {TEAM_A: "m1", TEAM_B: "m2"}
    result = season.project(games, team_owner, ["m1", "m2"], sims=50)
    by_manager = {p["manager_id"]: p for p in result["managers"]}
    assert by_manager["m1"]["projected_final"] == 1.0
    assert by_manager["m2"]["projected_final"] == 0.0
    assert result["games_remaining"] == 0


def test_project_favours_the_higher_rated_team_over_many_remaining_games(monkeypatch):
    monkeypatch.setattr(season, "RATINGS", {TEAM_A: 1700, TEAM_B: 1300})
    games = [make_game(str(w), w, TEAM_A, TEAM_B, completed=False) for w in range(1, 9)]
    team_owner = {TEAM_A: "favorite", TEAM_B: "underdog"}
    result = season.project(games, team_owner, ["favorite", "underdog"], sims=4000, seed=1)
    by_manager = {p["manager_id"]: p for p in result["managers"]}
    assert by_manager["favorite"]["projected_final"] > by_manager["underdog"]["projected_final"]
    assert by_manager["favorite"]["title_odds"] > 50


def test_missing_future_weeks_collapses_the_projection(monkeypatch):
    """This is the bug the nfl_scores.py fix closes: if a results cache is missing
    every week past the current one, the projection has nothing left to simulate
    and collapses toward whatever is already banked, instead of a full-season
    total built from every game still on the schedule.
    """
    monkeypatch.setattr(season, "RATINGS", {TEAM_A: 1500, TEAM_B: 1500})
    team_owner = {TEAM_A: "m1", TEAM_B: "m2"}
    full_season = [make_game(str(w), w, TEAM_A, TEAM_B, completed=False) for w in range(1, 19)]
    only_fetched_so_far = full_season[:2]  # what a truncated cache used to contain

    full = season.project(full_season, team_owner, ["m1", "m2"], sims=3000, seed=7)
    truncated = season.project(only_fetched_so_far, team_owner, ["m1", "m2"], sims=3000, seed=7)

    full_total = sum(p["projected_final"] for p in full["managers"])
    truncated_total = sum(p["projected_final"] for p in truncated["managers"])
    assert full_total > truncated_total * 4


# --------------------------------------------------------------------------- completed_weeks

def test_completed_weeks_only_lists_weeks_with_a_finished_game():
    games = [
        make_game("1", 1, TEAM_A, TEAM_B, 1, 0, completed=True),
        make_game("2", 3, TEAM_A, TEAM_B, completed=False),
        make_game("3", 2, TEAM_A, TEAM_B, 1, 0, completed=True),
    ]
    assert season.completed_weeks(games) == [1, 2]


# --------------------------------------------------------------------------- results_fingerprint

def test_results_fingerprint_changes_when_a_score_changes():
    base = {"season": 2026, "games": [make_game("1", 1, TEAM_A, TEAM_B, 24, 17, completed=True)]}
    changed = {"season": 2026, "games": [make_game("1", 1, TEAM_A, TEAM_B, 27, 17, completed=True)]}
    assert season.results_fingerprint(base) != season.results_fingerprint(changed)


def test_results_fingerprint_stable_when_nothing_changes():
    results = {"season": 2026, "games": [
        make_game("1", 1, TEAM_A, TEAM_B, 24, 17, completed=True),
        make_game("2", 1, TEAM_C, TEAM_D, completed=False),
    ]}
    assert season.results_fingerprint(results) == season.results_fingerprint(results)


def test_results_fingerprint_is_blind_to_future_weeks_gaining_a_schedule():
    """Documents a real caveat: the fingerprint only hashes completed games, so
    the first refresh that backfills future weeks' schedules (all uncompleted)
    won't by itself invalidate a process's in-memory season cache. Only a change
    to a completed game's score does that.
    """
    with_future_schedule = {"season": 2026, "games": [
        make_game("1", 1, TEAM_A, TEAM_B, 24, 17, completed=True),
        make_game("2", 5, TEAM_C, TEAM_D, completed=False),
    ]}
    without_future_schedule = {"season": 2026, "games": [
        make_game("1", 1, TEAM_A, TEAM_B, 24, 17, completed=True),
    ]}
    assert season.results_fingerprint(with_future_schedule) == season.results_fingerprint(without_future_schedule)


# --------------------------------------------------------------------------- load_league

def test_load_league_builds_manager_and_team_owner_maps(tmp_path):
    state = {
        "managers": [{"id": "m1", "name": "Alice"}, {"id": "m2", "name": "Bob"}],
        "picks": [{"team": "buf", "manager_id": "m1"}, {"team": "KC", "manager_id": "m2"}],
    }
    path = tmp_path / "draft_state.json"
    path.write_text(json.dumps(state))
    managers, team_owner = season.load_league(path)
    assert managers == {"m1": "Alice", "m2": "Bob"}
    assert team_owner == {"BUF": "m1", "KC": "m2"}


def test_load_league_rejects_unknown_team(tmp_path):
    state = {"managers": [{"id": "m1", "name": "Alice"}], "picks": [{"team": "ZZZ", "manager_id": "m1"}]}
    path = tmp_path / "draft_state.json"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        season.load_league(path)


def test_load_league_rejects_unknown_manager(tmp_path):
    state = {"managers": [{"id": "m1", "name": "Alice"}], "picks": [{"team": "BUF", "manager_id": "ghost"}]}
    path = tmp_path / "draft_state.json"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        season.load_league(path)
