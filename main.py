#!/usr/bin/env python3
"""FastAPI backend for the season tracker.

Run with:
    uvicorn main:app --reload

The league roster and every auction pick live in draft_state.json, which is
committed: the draft is over, so that file is now static league data rather
than mutable state. The draft board that wrote it is a separate local-only
app (draft_server.py plus draftboard/).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import nfl_scores
import season as season_model

BASE_DIR = Path(__file__).resolve().parent
DRAFT_STATE_PATH = BASE_DIR / "draft_state.json"

app = FastAPI(title="Endzone Season Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# The season projection is a few hundred thousand simulated games, so it is
# computed once per distinct set of results and reused until a score changes.
_season_lock = threading.Lock()
_season_cache: Dict[str, object] = {"fingerprint": None, "state": None}


def _season_state(results: dict) -> dict:
    """Build (or reuse) the season payload for a given set of fetched results."""
    overrides = season_model.load_elo_overrides()
    fingerprint = season_model.results_fingerprint(results, overrides)
    with _season_lock:
        if _season_cache["fingerprint"] != fingerprint:
            _season_cache["state"] = season_model.build_season_state(
                results, draft_state_path=DRAFT_STATE_PATH)
            _season_cache["fingerprint"] = fingerprint
        return _season_cache["state"]


@app.get("/api/health")
def health() -> dict:
    """Cheap readiness probe that also reports whether the league loaded."""
    managers, team_owner = season_model.load_league(DRAFT_STATE_PATH)
    results = nfl_scores.load_results()
    return {
        "ok": True,
        "managers": len(managers),
        "teams_owned": len(team_owner),
        "games_cached": len(results.get("games", [])),
        "fetched_at": results.get("fetched_at"),
    }


def _fetch_results() -> dict:
    """Pull from ESPN, turning a fetch failure into a 502 rather than a 500."""
    try:
        return nfl_scores.refresh()
    except nfl_scores.ScoreFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/season")
def get_season() -> dict:
    """Leaderboard, projections, and week-by-week history from the cached scores.

    The host's disk is ephemeral, so a redeploy or a cold start leaves no cache
    behind. Pulling from ESPN takes a few seconds, which is a far better first
    load than asking the visitor to press a button.
    """
    results = nfl_scores.load_results()
    if not results.get("games"):
        results = _fetch_results()
    return _season_state(results)


@app.api_route("/api/season/refresh", methods=["GET", "POST"])
def refresh_season() -> dict:
    """Pull the latest scores from ESPN and rebuild the season payload.

    The response is a short summary, not the payload itself. This endpoint is
    what the scheduled warm-up job calls, and a cron service caps how much of a
    response it will read: the full payload is ~65 KB, which ours rejected as
    "Response data too big" on every run until it disabled the job. Whoever
    wants the rebuilt payload reads `GET /api/season`, which serves it straight
    from the cache this call just filled.

    GET is allowed as well as POST because cron services send GET by default,
    and a job pointed here with the default method would otherwise collect 405s
    until it was disabled. Refreshing a cache is safe to repeat, so the two
    methods do the same thing.
    """
    state = _season_state(_fetch_results())
    return {
        "ok": True,
        "season": state["season"],
        "fetched_at": state["fetched_at"],
        "games_played": state["games_played"],
        "games_total": state["games_total"],
        "weeks_played": state["weeks_played"],
    }
