#!/usr/bin/env python3
"""Pull NFL regular-season results from ESPN and cache them on disk.

ESPN's public scoreboard endpoint needs no API key, so this module only uses
the standard library. Results are cached in season_results.json; a refresh
re-fetches the weeks that are not yet fully final and leaves settled weeks
alone, so a polling caller does not hammer ESPN with 18 requests a minute.

Usage:
    python3 nfl_scores.py --refresh        # update the cache, print what changed
    python3 nfl_scores.py --show           # print the cached results
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BASE_DIR / "season_results.json"

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
REGULAR_SEASON = 2
WEEKS = 18

# ESPN spells exactly one team differently from the league's own board.
ESPN_TO_REPO = {"WSH": "WAS"}


class ScoreFetchError(RuntimeError):
    """ESPN could not be reached or returned something unusable."""


def current_season(today: Optional[datetime] = None) -> int:
    """The NFL season year that `today` falls in (a season spans two calendar years)."""
    today = today or datetime.now(timezone.utc)
    return today.year if today.month >= 3 else today.year - 1


def _normalize(abbr: str) -> str:
    return ESPN_TO_REPO.get(abbr.upper(), abbr.upper())


def _get_json(url: str, timeout: float) -> dict:
    # No custom User-Agent: ESPN 403s unrecognised agent strings, and urllib's
    # own default ("Python-urllib/x.y") is one it accepts.
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ScoreFetchError(f"Could not fetch {url}: {exc}") from exc


def _parse_event(event: dict, week: int) -> Optional[dict]:
    """Flatten one ESPN event into the record shape this repo stores."""
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]

    sides: Dict[str, dict] = {}
    for competitor in competition.get("competitors", []):
        sides[competitor.get("homeAway", "")] = competitor
    if "home" not in sides or "away" not in sides:
        return None

    status = (competition.get("status") or {}).get("type") or {}
    completed = bool(status.get("completed"))
    home = _normalize(sides["home"]["team"]["abbreviation"])
    away = _normalize(sides["away"]["team"]["abbreviation"])

    def score(side: str) -> Optional[int]:
        raw = sides[side].get("score")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    home_score, away_score = score("home"), score("away")
    tie = completed and home_score == away_score
    winner = None
    if completed and not tie and home_score is not None and away_score is not None:
        winner = home if home_score > away_score else away

    return {
        "id": str(event.get("id", f"{week}-{away}-{home}")),
        "week": week,
        "kickoff": event.get("date"),
        "home": home,
        "away": away,
        "home_score": home_score if completed else None,
        "away_score": away_score if completed else None,
        "completed": completed,
        "state": status.get("state", "pre"),
        "status": status.get("shortDetail") or status.get("description") or "",
        "winner": winner,
        "tie": tie,
    }


def fetch_week(season: int, week: int, timeout: float = 20.0) -> List[dict]:
    url = f"{SCOREBOARD_URL}?dates={season}&seasontype={REGULAR_SEASON}&week={week}"
    payload = _get_json(url, timeout)
    games = [_parse_event(event, week) for event in payload.get("events", [])]
    return [game for game in games if game]


def fetch_current_week(season: int, timeout: float = 20.0) -> int:
    """Ask ESPN which regular-season week is live right now."""
    payload = _get_json(f"{SCOREBOARD_URL}?dates={season}&seasontype={REGULAR_SEASON}", timeout)
    week = (payload.get("week") or {}).get("number")
    return int(week) if week else 1


def load_results(path: Path = RESULTS_PATH) -> dict:
    if not path.exists():
        return {"season": None, "fetched_at": None, "games": []}
    with path.open() as f:
        return json.load(f)


def save_results(data: dict, path: Path = RESULTS_PATH) -> None:
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(path)


def _weeks_needing_refresh(cached_games: List[dict], through_week: int) -> List[int]:
    """Weeks up to `through_week` that are missing or still have a non-final game.

    Weeks whose games are all final never change again, so they are skipped. That
    keeps an every-few-minutes poll down to one or two requests.
    """
    by_week: Dict[int, List[dict]] = {}
    for game in cached_games:
        by_week.setdefault(game["week"], []).append(game)
    return [
        week for week in range(1, min(through_week, WEEKS) + 1)
        if week not in by_week or not all(g["completed"] for g in by_week[week])
    ]


def refresh(path: Path = RESULTS_PATH, season: Optional[int] = None,
            force_all: bool = False, timeout: float = 20.0) -> dict:
    """Update the cached results and return the new cache.

    Only the weeks that can still change are re-fetched unless `force_all` is set.
    """
    season = season or current_season()
    cached = load_results(path)
    # A season rollover invalidates everything that was cached for the old year.
    games: Dict[str, dict] = {}
    if cached.get("season") == season and not force_all:
        games = {g["id"]: g for g in cached.get("games", [])}

    through_week = WEEKS if force_all else fetch_current_week(season, timeout)
    weeks = range(1, WEEKS + 1) if force_all else _weeks_needing_refresh(list(games.values()), through_week)

    for week in weeks:
        for game in fetch_week(season, week, timeout):
            games[game["id"]] = game

    data = {
        "season": season,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "games": sorted(games.values(), key=lambda g: (g["week"], g["kickoff"] or "", g["home"])),
    }
    save_results(data, path)
    return data


def completed_games(data: dict) -> List[dict]:
    return [g for g in data.get("games", []) if g["completed"]]


def describe(game: dict) -> str:
    """One-line human summary, e.g. 'SEA beat NE 13-10' or 'DET and BAL tied 20-20'."""
    if not game["completed"]:
        return f"{game['away']} at {game['home']} ({game['status']})"
    if game["tie"]:
        return f"{game['home']} and {game['away']} tied {game['home_score']}-{game['away_score']}"
    loser = game["away"] if game["winner"] == game["home"] else game["home"]
    high = max(game["home_score"], game["away_score"])
    low = min(game["home_score"], game["away_score"])
    return f"{game['winner']} beat {loser} {high}-{low}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--refresh", action="store_true", help="fetch updates from ESPN")
    p.add_argument("--all", action="store_true", help="re-fetch every week, not just unsettled ones")
    p.add_argument("--show", action="store_true", help="print cached results")
    p.add_argument("--season", type=int, default=None)
    args = p.parse_args()

    data = refresh(season=args.season, force_all=args.all) if args.refresh else load_results()
    if not args.refresh and not args.show:
        p.error("pass --refresh and/or --show")

    finished = completed_games(data)
    print(f"Season {data.get('season')} · {len(finished)} of {len(data.get('games', []))} "
          f"games final · fetched {data.get('fetched_at')}")
    if args.show:
        for game in finished:
            print(f"  W{game['week']:<2} {describe(game)}")


if __name__ == "__main__":
    main()
