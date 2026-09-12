#!/usr/bin/env python3
"""Season-long scoring model: leaderboard, Elo updates, and live title odds.

League scoring is one point per win and half a point per tie, summed across
every NFL team a manager drafted.

The projection conditions on what has actually happened: completed games are
banked as real points, team Elo ratings are updated from those results, and
only the games still on the schedule are simulated. So a manager's projected
final score is `points already banked + simulated wins from here`, and the
title odds move as the season plays out.

Usage:
    python3 season.py                 # leaderboard + projection from the cache
    python3 season.py --refresh       # pull fresh scores from ESPN first
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import nfl_scores
from fantasy_auction_simulator import HOME_FIELD_ELO, RATINGS, percentile

BASE_DIR = Path(__file__).resolve().parent
DRAFT_STATE_PATH = BASE_DIR / "draft_state.json"

# 538-style in-season Elo update. K sets how fast ratings move; the
# margin-of-victory multiplier damps blowouts by heavy favourites so that
# running up the score against a bad team is worth less than beating a peer.
ELO_K = 20.0
DEFAULT_SIMS = 10000
DEFAULT_HISTORY_SIMS = 4000
DEFAULT_SEED = 20260909


# --------------------------------------------------------------------------- league

def load_league(path: Path = DRAFT_STATE_PATH) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (manager_id -> name, team -> owning manager_id) from the draft state."""
    with open(path) as f:
        state = json.load(f)
    managers = {m["id"]: m["name"] for m in state["managers"]}
    team_owner: Dict[str, str] = {}
    for pick in state["picks"]:
        team = pick["team"].upper()
        if team not in RATINGS:
            raise ValueError(f"Unknown team in {path.name}: {team}")
        if pick["manager_id"] not in managers:
            raise ValueError(f"Unknown manager in {path.name}: {pick['manager_id']}")
        team_owner[team] = pick["manager_id"]
    return managers, team_owner


# --------------------------------------------------------------------------- elo

def _expected_home(home_elo: float, away_elo: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(home_elo + HOME_FIELD_ELO - away_elo) / 400.0))


def elo_through(games: Sequence[dict], through_week: Optional[int] = None,
                k: float = ELO_K) -> Dict[str, float]:
    """Ratings after applying every completed game (optionally only up to a week)."""
    elos = {team: float(rating) for team, rating in RATINGS.items()}
    ordered = sorted((g for g in games if g["completed"]),
                     key=lambda g: (g["week"], g["kickoff"] or ""))
    for game in ordered:
        if through_week is not None and game["week"] > through_week:
            break
        home, away = game["home"], game["away"]
        expected = _expected_home(elos[home], elos[away])
        actual = 0.5 if game["tie"] else (1.0 if game["winner"] == home else 0.0)

        margin = abs((game["home_score"] or 0) - (game["away_score"] or 0))
        edge = (elos[home] + HOME_FIELD_ELO) - elos[away]
        # The autocorrelation term is measured from the winner's point of view; a
        # tie has no winner, so its absolute size is used instead.
        if actual == 1.0:
            winner_edge = edge
        elif actual == 0.0:
            winner_edge = -edge
        else:
            winner_edge = abs(edge)
        # max(margin, 1) keeps a tie (margin 0) from collapsing the multiplier to
        # zero: an underdog holding a favourite to a draw is real information.
        mov = math.log(max(margin, 1) + 1) * (2.2 / (winner_edge * 0.001 + 2.2))

        shift = k * mov * (actual - expected)
        elos[home] += shift
        elos[away] -= shift
    return elos


# --------------------------------------------------------------------------- scoring

def team_points(games: Sequence[dict], through_week: Optional[int] = None) -> Dict[str, float]:
    """Banked league points per NFL team: 1 per win, 0.5 per tie."""
    points = {team: 0.0 for team in RATINGS}
    for game in games:
        if not game["completed"]:
            continue
        if through_week is not None and game["week"] > through_week:
            continue
        if game["tie"]:
            points[game["home"]] += 0.5
            points[game["away"]] += 0.5
        else:
            points[game["winner"]] += 1.0
    return points


def team_records(games: Sequence[dict]) -> Dict[str, Dict[str, int]]:
    records = {team: {"w": 0, "l": 0, "t": 0} for team in RATINGS}
    for game in games:
        if not game["completed"]:
            continue
        if game["tie"]:
            records[game["home"]]["t"] += 1
            records[game["away"]]["t"] += 1
        else:
            loser = game["away"] if game["winner"] == game["home"] else game["home"]
            records[game["winner"]]["w"] += 1
            records[loser]["l"] += 1
    return records


def manager_points(team_owner: Dict[str, str], points: Dict[str, float]) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for team, manager_id in team_owner.items():
        totals[manager_id] = totals.get(manager_id, 0.0) + points.get(team, 0.0)
    return totals


# --------------------------------------------------------------------------- projection

def project(games: Sequence[dict], team_owner: Dict[str, str], manager_ids: Sequence[str],
            through_week: Optional[int] = None, sims: int = DEFAULT_SIMS,
            seed: int = DEFAULT_SEED) -> dict:
    """Monte-Carlo the games that have not been played yet.

    Elo is held fixed at its current value across a simulated future rather than
    updated game by game inside each run. That understates how far ratings can
    drift late in a season, but it keeps every simulated game independent given
    the present state, which is what the title odds are conditioning on.
    """
    banked_team = team_points(games, through_week)
    elos = elo_through(games, through_week)

    def is_played(game: dict) -> bool:
        return game["completed"] and (through_week is None or game["week"] <= through_week)

    teams = sorted(RATINGS)
    team_index = {team: i for i, team in enumerate(teams)}
    manager_index = {mid: i for i, mid in enumerate(manager_ids)}
    # Every team is drafted, but guard anyway so a partial draft cannot crash this.
    owner_of = [manager_index.get(team_owner.get(team, ""), -1) for team in teams]

    remaining = [
        (team_index[g["home"]], team_index[g["away"]],
         _expected_home(elos[g["home"]], elos[g["away"]]))
        for g in games if not is_played(g)
    ]

    banked_manager = [0.0] * len(manager_ids)
    for team in teams:
        owner = owner_of[team_index[team]]
        if owner >= 0:
            banked_manager[owner] += banked_team[team]

    rng = random.Random(seed)
    random_float = rng.random
    n_managers = len(manager_ids)
    future_team_wins = [0.0] * len(teams)
    finals: List[List[float]] = [[] for _ in range(n_managers)]
    title_credit = [0.0] * n_managers
    rank_totals = [0.0] * n_managers
    rank_counts = [[0] * (n_managers + 1) for _ in range(n_managers)]

    for _ in range(sims):
        totals = banked_manager[:]
        for home_i, away_i, p_home in remaining:
            winner = home_i if random_float() < p_home else away_i
            future_team_wins[winner] += 1.0
            owner = owner_of[winner]
            if owner >= 0:
                totals[owner] += 1.0

        for i, total in enumerate(totals):
            finals[i].append(total)

        best = max(totals)
        winners = [i for i, total in enumerate(totals) if total == best]
        credit = 1.0 / len(winners)
        for i in winners:
            title_credit[i] += credit

        # Standard competition ranking, so managers tied on points share a rank.
        order = sorted(range(n_managers), key=lambda i: totals[i], reverse=True)
        rank, previous = 0, None
        for position, i in enumerate(order, start=1):
            if totals[i] != previous:
                rank, previous = position, totals[i]
            rank_totals[i] += rank
            rank_counts[i][rank] += 1

    projections = []
    for i, manager_id in enumerate(manager_ids):
        scores = finals[i]
        projections.append({
            "manager_id": manager_id,
            "banked": round(banked_manager[i], 1),
            "projected_final": round(statistics.mean(scores), 2),
            "sd": round(statistics.pstdev(scores), 2),
            "p10": round(percentile(scores, 10), 1),
            "median": round(percentile(scores, 50), 1),
            "p90": round(percentile(scores, 90), 1),
            "title_odds": round(100.0 * title_credit[i] / sims, 2),
            "avg_rank": round(rank_totals[i] / sims, 2),
            "rank_distribution": {
                str(rank): round(100.0 * count / sims, 2)
                for rank, count in enumerate(rank_counts[i]) if rank and count
            },
        })

    team_projection = {
        team: {
            "elo": round(elos[team], 1),
            "banked": round(banked_team[team], 1),
            "projected_wins": round(banked_team[team] + future_team_wins[team_index[team]] / sims, 2),
        }
        for team in teams
    }

    return {
        "sims": sims,
        "games_remaining": len(remaining),
        "managers": projections,
        "teams": team_projection,
    }


# --------------------------------------------------------------------------- assembly

def completed_weeks(games: Sequence[dict]) -> List[int]:
    return sorted({g["week"] for g in games if g["completed"]})


def build_history(games: Sequence[dict], team_owner: Dict[str, str], manager_ids: Sequence[str],
                  sims: int = DEFAULT_HISTORY_SIMS, seed: int = DEFAULT_SEED) -> List[dict]:
    """Points and title odds as they stood at the end of each week with results.

    Week 0 is the preseason state: nobody has points yet and the odds come from
    the draft-day Elo ratings, which gives every chart a real starting point.
    """
    history = []
    for week in [0] + completed_weeks(games):
        points = manager_points(team_owner, team_points(games, week))
        odds = project(games, team_owner, manager_ids, through_week=week, sims=sims, seed=seed)
        odds_by_manager = {m["manager_id"]: m["title_odds"] for m in odds["managers"]}
        history.append({
            "week": week,
            "points": {mid: round(points.get(mid, 0.0), 1) for mid in manager_ids},
            "title_odds": {mid: odds_by_manager[mid] for mid in manager_ids},
        })
    return history


def build_season_state(results: Optional[dict] = None, draft_state_path: Path = DRAFT_STATE_PATH,
                       sims: int = DEFAULT_SIMS, history_sims: int = DEFAULT_HISTORY_SIMS,
                       seed: int = DEFAULT_SEED) -> dict:
    """The full payload the API and the WhatsApp notifier both read."""
    results = results if results is not None else nfl_scores.load_results()
    games = results.get("games", [])
    managers, team_owner = load_league(draft_state_path)
    manager_ids = list(managers)

    points = team_points(games)
    records = team_records(games)
    totals = manager_points(team_owner, points)
    projection = project(games, team_owner, manager_ids, sims=sims, seed=seed)
    projection_by_manager = {m["manager_id"]: m for m in projection["managers"]}

    leaderboard = []
    for manager_id in manager_ids:
        owned = sorted((t for t, m in team_owner.items() if m == manager_id),
                       key=lambda t: (-points[t], t))
        entry = dict(projection_by_manager[manager_id])
        entry.update({
            "name": managers[manager_id],
            "points": round(totals.get(manager_id, 0.0), 1),
            "teams": [
                {"team": t, "points": points[t], "record": records[t],
                 "projected_wins": projection["teams"][t]["projected_wins"],
                 "elo": projection["teams"][t]["elo"]}
                for t in owned
            ],
        })
        leaderboard.append(entry)
    leaderboard.sort(key=lambda e: (-e["points"], -e["title_odds"], e["name"]))

    rank, previous = 0, None
    for position, entry in enumerate(leaderboard, start=1):
        if entry["points"] != previous:
            rank, previous = position, entry["points"]
        entry["rank"] = rank

    finished = [g for g in games if g["completed"]]
    return {
        "season": results.get("season"),
        "fetched_at": results.get("fetched_at"),
        "games_played": len(finished),
        "games_total": len(games),
        "weeks_played": completed_weeks(games),
        "leaderboard": leaderboard,
        "history": build_history(games, team_owner, manager_ids, sims=history_sims, seed=seed),
        "games": games,
        "sims": sims,
    }


def results_fingerprint(results: dict) -> str:
    """Identifies a set of completed results, so cached work can be reused."""
    finished = sorted(
        f"{g['id']}:{g['home_score']}-{g['away_score']}"
        for g in results.get("games", []) if g["completed"]
    )
    return f"{results.get('season')}|{len(finished)}|{hash(tuple(finished)) & 0xFFFFFFFF:08x}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--refresh", action="store_true", help="pull fresh scores from ESPN first")
    p.add_argument("--sims", type=int, default=DEFAULT_SIMS)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = p.parse_args()

    results = nfl_scores.refresh() if args.refresh else nfl_scores.load_results()
    if not results.get("games"):
        raise SystemExit("No cached scores. Run: python3 nfl_scores.py --refresh")

    state = build_season_state(results, sims=args.sims, seed=args.seed)

    print(f"Season {state['season']} · {state['games_played']}/{state['games_total']} games played "
          f"· {state['sims']:,} simulated finishes\n")
    header = f"{'#':<3}{'Manager':<10}{'Pts':>6}{'Proj':>8}{'P10':>7}{'P90':>7}{'Title%':>9}"
    print(header)
    print("-" * len(header))
    for entry in state["leaderboard"]:
        print(f"{entry['rank']:<3}{entry['name']:<10}{entry['points']:>6.1f}"
              f"{entry['projected_final']:>8.1f}{entry['p10']:>7.1f}{entry['p90']:>7.1f}"
              f"{entry['title_odds']:>8.1f}%")

    print("\nResults so far:")
    for game in state["games"]:
        if game["completed"]:
            print(f"  W{game['week']:<2} {nfl_scores.describe(game)}")


if __name__ == "__main__":
    main()
