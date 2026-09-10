#!/usr/bin/env python3
"""Monte-Carlo auction planner for an NFL team-ownership fantasy league.

No third-party packages are required:
    python3 fantasy_auction_simulator.py --sims 2000

The default season model is a neutral 17-game schedule sampled from the 31
other teams.  For a real schedule, give --schedule either a long CSV containing
``team,opponent,home`` or a 4for4-style weekly schedule grid; that produces
much better estimates of expected wins and variance.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Team, Elo, as supplied by the league manager.  Update this list as ratings move.
RATINGS: Dict[str, int] = {
    "BUF":1602,"DEN":1600,"LAR":1598,"HOU":1588,"SEA":1586,"BAL":1570,
    "KC":1556,"NE":1556,"PHI":1553,"JAX":1552,"DET":1537,"SF":1536,
    "LAC":1529,"MIN":1515,"TB":1510,"GB":1501,"CIN":1501,"IND":1497,
    "DAL":1487,"CHI":1479,"ATL":1463,"PIT":1461,"NYG":1456,"ARI":1447,
    "MIA":1443,"WAS":1437,"LV":1428,"NO":1426,"TEN":1412,"CLE":1405,
    "NYJ":1386,"CAR":1380,
}

PLAYERS, STARTING_BUDGET, GAMES = 9, 100.0, 17
HOME_FIELD_ELO = 55  # change to 0 for fully neutral game simulations
TOTAL_LEAGUE_BUDGET = PLAYERS * STARTING_BUDGET

# Baseline projections default to the league's real schedule shipped alongside this script.
DEFAULT_SCHEDULE_PATH = Path(__file__).resolve().parent / "schedule_2026.csv"


def win_probability(team_elo: float, opponent_elo: float, home: int = 0) -> float:
    """Standard Elo expected score; a draw is not separately modeled."""
    # home is +1 for home, -1 for away, and 0 for a neutral fallback schedule.
    return 1.0 / (1.0 + 10.0 ** (-(team_elo + home * HOME_FIELD_ELO - opponent_elo) / 400.0))


def read_schedule(path: Optional[str]) -> Dict[str, List[Tuple[str, int]]]:
    schedule = {team: [] for team in RATINGS}
    if not path:
        # An empty schedule signals that each simulated game should get a new random,
        # neutral opponent. Do not sample one fixed pseudo-schedule: it would make an
        # accidental easy slate look like a team-strength difference.
        return schedule
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("Schedule CSV is empty")
    # Standard long format: one row per team-game.
    if {"team", "opponent"}.issubset(rows[0]):
        for row in rows:
            team, opp = row["team"].upper(), row["opponent"].upper()
            if team not in RATINGS or opp not in RATINGS:
                raise ValueError(f"Unknown team in schedule: {team}, {opp}")
            schedule[team].append((opp, 1 if int(row.get("home", 0)) else -1))
    # 4for4 grid format: Team,W1,...,W18 with @ indicating an away game.
    elif "Team" in rows[0]:
        for row in rows:
            team = row["Team"].upper()
            if team not in RATINGS:
                raise ValueError(f"Unknown team in schedule: {team}")
            for week, matchup in row.items():
                if not week.startswith("W") or not matchup or matchup.upper() == "BYE":
                    continue
                matchup = matchup.upper()
                away = matchup.startswith("@")
                opponent = matchup.removeprefix("@")
                if opponent not in RATINGS:
                    raise ValueError(f"Unknown opponent for {team}: {matchup}")
                schedule[team].append((opponent, -1 if away else 1))
    else:
        raise ValueError("Schedule needs team/opponent/home columns or a 4for4 Team/W1... grid")
    missing = [t for t, games in schedule.items() if len(games) != GAMES]
    if missing:
        raise ValueError("Each team needs exactly 17 schedule rows; missing: " + ", ".join(missing))
    return schedule


def season_samples(n: int, schedule_path: Optional[str], rng: random.Random) -> Dict[str, List[float]]:
    schedule = read_schedule(schedule_path)
    samples = {t: [] for t in RATINGS}
    # With the supplied schedule, each game is simulated only once and its result
    # is credited to both teams' records. This preserves the zero-sum nature of
    # NFL wins, which matters when comparing fantasy rosters head-to-head.
    if schedule_path:
        for _ in range(n):
            totals = {team: 0.0 for team in RATINGS}
            games_simulated = 0
            for home_team, games in schedule.items():
                for away_team, home_flag in games:
                    if home_flag != 1:
                        continue
                    games_simulated += 1
                    if rng.random() < win_probability(RATINGS[home_team], RATINGS[away_team], 1):
                        totals[home_team] += 1.0
                    else:
                        totals[away_team] += 1.0
            if games_simulated != len(RATINGS) * GAMES // 2:
                raise ValueError("Schedule must contain one home and one away entry per matchup")
            for team, total in totals.items():
                samples[team].append(total)
        return samples

    # The neutral fallback has no shared game list, so it uses independent games.
    for _ in range(n):
        for team, games in schedule.items():
            if not games:
                games = [(rng.choice([x for x in RATINGS if x != team]), 0) for _ in range(GAMES)]
            points = sum(rng.random() < win_probability(RATINGS[team], RATINGS[opp], home)
                         for opp, home in games)
            samples[team].append(float(points))
    return samples


def fair_values(samples: Dict[str, List[float]]) -> Dict[str, float]:
    """A budget-neutral initial board: each $ buys the same expected season point."""
    means = {t: statistics.mean(x) for t, x in samples.items()}
    total = sum(means.values())
    return {t: PLAYERS * STARTING_BUDGET * means[t] / total for t in means}


def build_baseline_board(schedule_path: Optional[Path | str] = DEFAULT_SCHEDULE_PATH,
                         sims: int = 3000, seed: int = 20260909) -> Dict[str, float]:
    """Run the Monte-Carlo season model once and return the budget-neutral fair-value board.

    This is the expensive step (it simulates `sims` seasons) and does not depend on any
    draft picks, so callers should compute it once and reuse it across picks rather than
    calling this for every request.
    """
    rng = random.Random(seed)
    samples = season_samples(sims, str(schedule_path) if schedule_path else None, rng)
    return fair_values(samples)


def market_snapshot(picks: List[Dict[str, object]], baseline_board: Dict[str, float]) -> Dict[str, object]:
    """Recalculate adjusted market values for undrafted teams given completed draft picks.

    This is the cheap, callable core of the live draft board: it takes the array of
    completed picks (each with a team, sale price, and manager) plus the precomputed
    baseline board, and dynamically recalculates an inflation factor from the league's
    total remaining budget. Every undrafted team's adjusted value is its baseline value
    scaled by that inflation factor, so teams get pricier as the room overspends its
    original budget-neutral board and cheaper as it underspends.
    """
    drafted: Dict[str, Dict[str, object]] = {}
    total_spent = 0.0
    for pick in picks:
        team = str(pick["team"]).upper()
        if team not in baseline_board:
            raise ValueError(f"Unknown team in picks: {team}")
        if team in drafted:
            raise ValueError(f"Team drafted more than once: {team}")
        price = float(pick["price"])
        # Carry through any other pick fields (e.g. manager_id) unchanged; this
        # function only owns the team-economics part of a pick.
        extra = {k: v for k, v in pick.items() if k not in ("team", "price")}
        drafted[team] = {"price": price, **extra}
        total_spent += price

    undrafted = [t for t in baseline_board if t not in drafted]
    remaining_budget = TOTAL_LEAGUE_BUDGET - total_spent
    baseline_remaining_value = sum(baseline_board[t] for t in undrafted)
    inflation_factor = (remaining_budget / baseline_remaining_value
                        if baseline_remaining_value > 0 else 0.0)

    # Every team stays in this list at its original fair-value rank, drafted or not,
    # so a client can render a single always-in-order board and just mark drafted
    # rows instead of having them jump out of the table.
    teams = [
        {
            "team": team,
            "baseline_value": round(baseline_board[team], 2),
            "adjusted_value": (round(baseline_board[team] * inflation_factor, 2)
                               if team not in drafted else None),
            "drafted": team in drafted,
            **drafted.get(team, {}),
        }
        for team in sorted(baseline_board, key=lambda t: baseline_board[t], reverse=True)
    ]

    return {
        "inflation_factor": round(inflation_factor, 4),
        "total_league_budget": TOTAL_LEAGUE_BUDGET,
        "total_spent": round(total_spent, 2),
        "remaining_budget": round(remaining_budget, 2),
        "teams": teams,
    }


@dataclass
class Owner:
    cash: float = STARTING_BUDGET
    teams: List[str] = field(default_factory=list)


def auction_once(board: Dict[str, float], rng: random.Random, aggressiveness: float) -> Tuple[List[Owner], Dict[str, float]]:
    """One stylised 32-nomination auction.

    Nomination order starts with a shuffled nine-manager round and repeats. With
    32 teams, five managers receive a fourth nomination and four receive three.

    Bidders have independent noisy opinions and never bid more than their cash.
    This is a planning model, not a claim that the real auction has a unique
    equilibrium.
    """
    owners = [Owner() for _ in range(PLAYERS)]
    clearing_prices: Dict[str, float] = {}
    remaining = list(board)
    nomination_order: List[int] = []
    while len(nomination_order) < len(board):
        round_order = list(range(PLAYERS))
        rng.shuffle(round_order)
        nomination_order.extend(round_order)
    nomination_order = nomination_order[:len(board)]
    for nominator in nomination_order:
        # A manager is likelier to nominate a premium team, but not mechanically so.
        # The best noisy option among the top eight represents nominations, bluffing,
        # and different manager preferences without assuming perfect coordination.
        candidates = sorted(remaining, key=lambda t: board[t], reverse=True)[:8]
        team = max(candidates, key=lambda t: board[t] * rng.lognormvariate(0, .20))
        remaining.remove(team)
        bids = []
        for owner in owners:
            # A team is less useful when this owner already has a deep portfolio.
            portfolio_discount = 1.0 / (1.0 + .06 * max(0, len(owner.teams) - 3))
            perceived = board[team] * aggressiveness * portfolio_discount * rng.lognormvariate(0, .16)
            # Keep enough money to acquire at least one of each of the average remaining teams.
            reserve = max(0.0, (len(remaining) / PLAYERS - len(owner.teams)) * 5.0)
            bids.append(max(0.0, min(owner.cash - reserve, perceived)))
        ranked = sorted(range(PLAYERS), key=lambda i: bids[i], reverse=True)
        winner = ranked[0]
        # An ascending auction settles one increment above the runner-up, never above
        # the winner's own stated maximum.
        price = round(min(bids[winner], bids[ranked[1]] + 0.5), 1)
        owners[winner].cash -= price
        owners[winner].teams.append(team)
        clearing_prices[team] = price
    return owners, clearing_prices


def run_auctions(board: Dict[str, float], sims: int, seed: int, aggressiveness: float) -> Dict[str, List[float]]:
    rng = random.Random(seed + 1)
    prices = {t: [] for t in board}
    for _ in range(sims):
        _, clearing = auction_once(board, rng, aggressiveness)
        for team, price in clearing.items():
            prices[team].append(price)
    return prices


def percentile(values: List[float], pct: float) -> float:
    """Linear percentile without adding a numerical dependency."""
    xs = sorted(values)
    index = (len(xs) - 1) * pct / 100
    low, high = math.floor(index), math.ceil(index)
    return xs[low] + (xs[high] - xs[low]) * (index - low)


def auction_distribution(samples: Dict[str, List[float]], board: Dict[str, float], sims: int,
                         seed: int, aggressiveness: float) -> None:
    """Print roster-size and expected-score outcomes across repeated auctions."""
    means = {team: statistics.mean(points) for team, points in samples.items()}
    rng = random.Random(seed + 2)
    roster_sizes: List[int] = []
    expected_scores: List[float] = []
    lowest_scores: List[float] = []
    highest_scores: List[float] = []
    for _ in range(sims):
        owners, _ = auction_once(board, rng, aggressiveness)
        draft_scores = [sum(means[team] for team in owner.teams) for owner in owners]
        roster_sizes.extend(len(owner.teams) for owner in owners)
        expected_scores.extend(draft_scores)
        lowest_scores.append(min(draft_scores))
        highest_scores.append(max(draft_scores))

    counts = Counter(roster_sizes)
    print(f"\nAuction distribution ({sims:,} simulated {PLAYERS}-manager drafts)")
    print("Teams owned by a representative manager")
    print("  " + "  ".join(f"{n}: {100 * counts[n] / len(roster_sizes):4.1f}%"
                           for n in range(min(counts), max(counts) + 1)))
    print("Expected regular-season score for a representative manager")
    print(f"  mean {statistics.mean(expected_scores):.1f} | "
          f"P10 {percentile(expected_scores, 10):.1f} | "
          f"median {percentile(expected_scores, 50):.1f} | "
          f"P90 {percentile(expected_scores, 90):.1f}")
    print(f"Within one draft, expected-score spread across the {PLAYERS} managers")
    print(f"  lowest roster: mean {statistics.mean(lowest_scores):.1f}; "
          f"highest roster: mean {statistics.mean(highest_scores):.1f}")


def winner_portfolio_distribution(samples: Dict[str, List[float]], board: Dict[str, float], sims: int,
                                  seed: int, aggressiveness: float) -> None:
    """Identify actual season winners after each auction, splitting tied wins."""
    rng = random.Random(seed + 3)
    team_on_winner = Counter()
    winning_roster_sizes = Counter()
    tied_drafts = 0
    season_count = len(next(iter(samples.values())))
    for _ in range(sims):
        owners, _ = auction_once(board, rng, aggressiveness)
        season = rng.randrange(season_count)
        scores = [sum(samples[team][season] for team in owner.teams) for owner in owners]
        best = max(scores)
        winners = [i for i, score in enumerate(scores) if score == best]
        if len(winners) > 1:
            tied_drafts += 1
        credit = 1.0 / len(winners)
        for index in winners:
            portfolio = tuple(sorted(owners[index].teams))
            winning_roster_sizes[len(portfolio)] += credit
            for team in portfolio:
                team_on_winner[team] += credit

    print(f"\nWinning-portfolio analysis ({sims:,} auction + season simulations)")
    print("Chance that the manager owning a team wins the league")
    for team in sorted(RATINGS, key=lambda t: team_on_winner[t], reverse=True):
        print(f"  {team}: {100 * team_on_winner[team] / sims:4.1f}%")
    print("Winning roster size")
    print("  " + "  ".join(f"{size}: {100 * count / sims:4.1f}%"
                           for size, count in sorted(winning_roster_sizes.items())))
    print(f"Tied high score in {100 * tied_drafts / sims:.1f}% of drafts; those wins are split in the results.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sims", type=int, default=3000, help="simulation iterations (default: 3000)")
    p.add_argument("--seed", type=int, default=20260909)
    p.add_argument("--schedule", help="CSV with team,opponent,home columns")
    p.add_argument("--aggression", type=float, default=1.0,
                   help="expected room spending vs fair value (e.g. 1.10)")
    p.add_argument("--auction-sims", type=int, default=0,
                   help="also simulate this many full 32-team auctions")
    p.add_argument("--winner-sims", type=int, default=0,
                   help="simulate this many auctions and seasons; report winning portfolios")
    args = p.parse_args()
    rng = random.Random(args.seed)
    samples = season_samples(args.sims, args.schedule, rng)
    board = fair_values(samples)
    market = run_auctions(board, args.sims, args.seed, args.aggression)

    print("\nNFL team auction board (values are dollars out of a $100 personal budget)")
    print("Team   Elo  ExpPts  SD     Fair$   room price   hard cap")
    for team in sorted(RATINGS, key=lambda t: board[t], reverse=True):
        xs = samples[team]
        fair = board[team]
        projected = statistics.mean(market[team])
        # The pre-draft cap is a small flexibility premium, not permission to chase.
        cap = min(100, fair * 1.10)
        print(f"{team:<5} {RATINGS[team]:>4}  {statistics.mean(xs):>5.2f}  "
              f"{statistics.pstdev(xs):>4.2f}   ${fair:>5.1f}    ${projected:>5.1f}     ${cap:>5.1f}")
    print("\nHow to use the cap: reduce it 6% for each team you already own beyond four;")
    print("raise it only when you have fewer teams than the room average. Never spend your")
    print("last dollars early: later teams become bargains when competitors are cash-poor.")
    if args.schedule:
        print(f"\nSchedule: using regular-season matchups from {args.schedule}.")
    else:
        print("\nImportant: the built-in schedule is random/neutral. Use --schedule with the real")
        print("17-game schedule before treating the numbers as final draft prices.")
    if args.auction_sims:
        auction_distribution(samples, board, args.auction_sims, args.seed, args.aggression)
    if args.winner_sims:
        winner_portfolio_distribution(samples, board, args.winner_sims, args.seed, args.aggression)


if __name__ == "__main__":
    main()
