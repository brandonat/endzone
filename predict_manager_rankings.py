#!/usr/bin/env python3
"""Predict manager season scores and rankings from a completed auction draft.

Reads draft_state.json (managers + completed picks) and reuses the Elo season
model from fantasy_auction_simulator.py to simulate the 2026 season many times.
Each manager's score in a simulated season is the total wins across the NFL
teams they drafted; this script reports each manager's expected score,
variance, and rank distribution (including outright and shared title odds).

Usage:
    python3 predict_manager_rankings.py --sims 20000
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Dict, List

from fantasy_auction_simulator import (
    DEFAULT_SCHEDULE_PATH,
    RATINGS,
    percentile,
    season_samples,
)

DRAFT_STATE_PATH = Path(__file__).resolve().parent / "draft_state.json"


def load_draft_state(path: Path) -> Dict[str, object]:
    with open(path) as f:
        state = json.load(f)
    managers = {m["id"]: m["name"] for m in state["managers"]}
    manager_teams: Dict[str, List[str]] = {mid: [] for mid in managers}
    for pick in state["picks"]:
        team = pick["team"].upper()
        if team not in RATINGS:
            raise ValueError(f"Unknown team in draft_state.json: {team}")
        manager_teams[pick["manager_id"]].append(team)
    drafted = {t for teams in manager_teams.values() for t in teams}
    missing = [t for t in RATINGS if t not in drafted]
    if missing:
        raise ValueError("Draft is incomplete; undrafted teams: " + ", ".join(missing))
    return managers, manager_teams


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sims", type=int, default=20000, help="simulated seasons (default: 20000)")
    p.add_argument("--seed", type=int, default=20260909)
    p.add_argument("--schedule", default=str(DEFAULT_SCHEDULE_PATH),
                   help="CSV with team,opponent,home columns, or a 4for4 grid")
    args = p.parse_args()

    managers, manager_teams = load_draft_state(DRAFT_STATE_PATH)

    import random
    rng = random.Random(args.seed)
    samples = season_samples(args.sims, args.schedule, rng)

    manager_ids = sorted(managers, key=lambda mid: mid)
    season_count = len(next(iter(samples.values())))

    scores: Dict[str, List[float]] = {mid: [] for mid in manager_ids}
    for season in range(season_count):
        for mid in manager_ids:
            total = sum(samples[team][season] for team in manager_teams[mid])
            scores[mid].append(total)

    rank_counts: Dict[str, Counter] = {mid: Counter() for mid in manager_ids}
    title_credit = Counter()
    tied_titles = 0
    for season in range(season_count):
        season_scores = {mid: scores[mid][season] for mid in manager_ids}
        best = max(season_scores.values())
        winners = [mid for mid, s in season_scores.items() if s == best]
        if len(winners) > 1:
            tied_titles += 1
        credit = 1.0 / len(winners)
        for mid in winners:
            title_credit[mid] += credit
        ordered = sorted(manager_ids, key=lambda mid: season_scores[mid], reverse=True)
        rank = 0
        prev_score = None
        for pos, mid in enumerate(ordered, start=1):
            if season_scores[mid] != prev_score:
                rank = pos
                prev_score = season_scores[mid]
            rank_counts[mid][rank] += 1

    print(f"Manager score & ranking projection ({args.sims:,} simulated seasons)")
    print(f"Schedule: {args.schedule}\n")

    header = f"{'Manager':<10}{'Teams':<7}{'Mean':>7}{'SD':>6}{'P10':>7}{'Median':>8}{'P90':>7}{'AvgRank':>9}{'Title%':>8}"
    print(header)
    print("-" * len(header))
    summary = []
    for mid in manager_ids:
        s = scores[mid]
        mean = statistics.mean(s)
        sd = statistics.pstdev(s)
        avg_rank = sum(rank * count for rank, count in rank_counts[mid].items()) / args.sims
        title_pct = 100 * title_credit[mid] / args.sims
        summary.append((mid, mean, sd, avg_rank, title_pct))

    for mid, mean, sd, avg_rank, title_pct in sorted(summary, key=lambda row: row[1], reverse=True):
        name = managers[mid]
        n_teams = len(manager_teams[mid])
        s = scores[mid]
        print(f"{name:<10}{n_teams:<7}{mean:>7.1f}{sd:>6.2f}{percentile(s, 10):>7.1f}"
              f"{percentile(s, 50):>8.1f}{percentile(s, 90):>7.1f}{avg_rank:>9.2f}{title_pct:>7.1f}%")

    print(f"\nTied for the top score in {100 * tied_titles / args.sims:.1f}% of seasons; those titles are split above.")

    print("\nRosters:")
    for mid in sorted(manager_ids, key=lambda mid: managers[mid]):
        teams = sorted(manager_teams[mid], key=lambda t: RATINGS[t], reverse=True)
        print(f"  {managers[mid]:<10} {', '.join(teams)}")


if __name__ == "__main__":
    main()
