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
    fingerprint = season_model.results_fingerprint(results)
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


@app.get("/api/season")
def get_season() -> dict:
    """Leaderboard, projections, and week-by-week history from the cached scores.

    The host's disk is ephemeral, so a redeploy or a cold start leaves no cache
    behind. Pulling from ESPN takes a few seconds, which is a far better first
    load than asking the visitor to press a button.
    """
    results = nfl_scores.load_results()
    if not results.get("games"):
        return refresh_season()
    return _season_state(results)


@app.post("/api/season/refresh")
def refresh_season() -> dict:
    """Pull the latest scores from ESPN, then rebuild the season payload."""
    try:
        results = nfl_scores.refresh()
    except nfl_scores.ScoreFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _season_state(results)
