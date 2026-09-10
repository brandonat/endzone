#!/usr/bin/env python3
"""FastAPI backend for the live fantasy-team auction draft board.

Run with:
    uvicorn main:app --reload

Draft state (the fixed manager roster and every completed pick) persists to
draft_state.json (in this directory) on every write, so the draft survives a
server restart. The market board itself is not stored on disk: it is
recomputed from fantasy_auction_simulator.market_snapshot() every time a
client asks for it, using the persisted picks and a baseline board that is
simulated once at startup.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import fantasy_auction_simulator as sim

BASE_DIR = Path(__file__).resolve().parent
DRAFT_STATE_PATH = BASE_DIR / "draft_state.json"

app = FastAPI(title="Endzone Draft Board")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# The baseline board is the expensive Monte-Carlo step; it does not depend on
# draft picks, so it is computed once at startup and reused for every request.
BASELINE_BOARD = sim.build_baseline_board()

# Guards read-modify-write access to draft_state.json across concurrent requests.
_state_lock = threading.Lock()


class PickIn(BaseModel):
    team: str
    price: float = Field(gt=0)
    manager_id: str


class ManagerRename(BaseModel):
    name: str


def _default_managers() -> List[dict]:
    return [{"id": f"m{i + 1}", "name": f"Manager {i + 1}"} for i in range(sim.PLAYERS)]


def _resize_managers(managers: List[dict]) -> List[dict]:
    """Reconcile the persisted roster with the current sim.PLAYERS count.

    Keeps existing manager ids/names in place (so renames survive) and only
    truncates or appends at the tail when the league size changes.
    """
    managers = managers[:sim.PLAYERS]
    while len(managers) < sim.PLAYERS:
        i = len(managers) + 1
        managers.append({"id": f"m{i}", "name": f"Manager {i}"})
    return managers


def _load_state() -> dict:
    if not DRAFT_STATE_PATH.exists():
        return {"managers": _default_managers(), "picks": []}
    with DRAFT_STATE_PATH.open() as f:
        state = json.load(f)
    state["managers"] = _resize_managers(state.get("managers", []))
    state.setdefault("picks", [])
    return state


def _save_state(state: dict) -> None:
    tmp_path = DRAFT_STATE_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(state, f, indent=2)
    tmp_path.replace(DRAFT_STATE_PATH)


def _manager_summaries(managers: List[dict], picks: List[dict]) -> List[dict]:
    picks_by_manager: Dict[str, List[dict]] = {m["id"]: [] for m in managers}
    for pick in picks:
        picks_by_manager.setdefault(pick.get("manager_id"), []).append(pick)

    summaries = []
    for manager in managers:
        owned = picks_by_manager.get(manager["id"], [])
        spent = sum(p["price"] for p in owned)
        summaries.append({
            "id": manager["id"],
            "name": manager["name"],
            "spent": round(spent, 2),
            "remaining_budget": round(sim.STARTING_BUDGET - spent, 2),
            "teams": [{"team": p["team"], "price": p["price"]} for p in owned],
        })
    return summaries


def _full_market(state: dict) -> dict:
    market = sim.market_snapshot(state["picks"], BASELINE_BOARD)
    manager_names = {m["id"]: m["name"] for m in state["managers"]}
    for entry in market["teams"]:
        if entry["drafted"]:
            entry["manager_name"] = manager_names.get(entry.get("manager_id"), "Unassigned")
    market["managers"] = _manager_summaries(state["managers"], state["picks"])
    return market


@app.get("/api/teams")
def get_teams() -> dict:
    return _full_market(_load_state())


@app.put("/api/managers/{manager_id}")
def rename_manager(manager_id: str, body: ManagerRename) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Manager name cannot be empty")

    with _state_lock:
        state = _load_state()
        manager = next((m for m in state["managers"] if m["id"] == manager_id), None)
        if manager is None:
            raise HTTPException(status_code=404, detail=f"Unknown manager: {manager_id}")
        manager["name"] = name
        _save_state(state)
        return {"ok": True, "market": _full_market(state)}


@app.post("/api/pick")
def post_pick(pick: PickIn) -> dict:
    team = pick.team.upper()
    if team not in BASELINE_BOARD:
        raise HTTPException(status_code=400, detail=f"Unknown team: {team}")

    with _state_lock:
        state = _load_state()
        if not any(m["id"] == pick.manager_id for m in state["managers"]):
            raise HTTPException(status_code=400, detail=f"Unknown manager: {pick.manager_id}")
        if any(p["team"] == team for p in state["picks"]):
            raise HTTPException(status_code=409, detail=f"{team} has already been drafted")
        state["picks"].append({"team": team, "price": pick.price, "manager_id": pick.manager_id})
        _save_state(state)
        return {"ok": True, "market": _full_market(state)}


@app.delete("/api/pick/{team}")
def delete_pick(team: str) -> dict:
    team = team.upper()
    with _state_lock:
        state = _load_state()
        remaining = [p for p in state["picks"] if p["team"] != team]
        if len(remaining) == len(state["picks"]):
            raise HTTPException(status_code=404, detail=f"{team} has not been drafted")
        state["picks"] = remaining
        _save_state(state)
        return {"ok": True, "market": _full_market(state)}
