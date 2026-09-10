# Fantasy football team-auction simulator

## Live draft board (FastAPI + Svelte)

A live draft board sits on top of the simulator: a FastAPI backend serves market values that
re-inflate as picks come in, and a Svelte frontend gives you a rapid pick-entry form and a
reactive valuation table.

Backend (from the repo root):

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

This computes a baseline board once at startup (from `schedule_2026.csv`) and persists every
pick to `draft_state.json`, so the draft survives a server restart. Endpoints:

- `GET /api/teams` — current inflation factor and each undrafted team's baseline/adjusted value.
- `POST /api/pick` — body `{"team": "BUF", "price": 92.5, "manager": "Brandon"}`; appends the pick.

Frontend (in a second terminal):

```sh
cd frontend
npm install
npm run dev
```

Open the printed localhost URL; its dev server proxies `/api/*` to the backend on port 8000.


The included `schedule_2026.csv` is the provided 4for4 regular-season grid. Run the simulator against it with:

```sh
python3 fantasy_auction_simulator.py --schedule schedule_2026.csv --sims 10000
```

It starts with the supplied Elo ratings, simulates season results, and converts expected scoring into a budget-neutral fair-value board.  Since the league has 8 x $100 = $800 total purchasing power, the fair board sums to exactly $800.  That is a useful anchor: if a top team costs $65, you need an explicit reason why its portfolio advantage is worth taking $25-plus away from your remaining teams.

## Why this is a better starting point than “buy the best team”

Each team’s fantasy score is its season wins (a tie would be 0.5; the supplied model currently treats NFL games as decisive). A player’s expected total is the sum across owned teams.  The initial fair values therefore allocate the $800 in proportion to expected points.  At an average 8.5 wins per NFL team, each expected season point initially costs about $2.94.

The printed “hard cap” is a deliberately small (10%) premium over fair value.  Paying substantially over it gives up too many future expected points; your stated format rewards a portfolio of good teams much more often than one elite team plus near-zero budget. “Room price” is an auction simulation—not a guarantee—and is useful for seeing which teams are likely to be contested.

## Schedule input

The default fallback creates a random neutral 17-game slate. It is fine for testing auction tactics but not final valuation—NFL schedules differ materially. The bundled 4for4 grid is parsed directly: `@` means an away game, an unprefixed opponent is a home game, and `BYE` is skipped.

The script also accepts a long-format CSV like this (there must be 17 rows for every team):

```csv
team,opponent,home
BUF,NE,1
BUF,NYJ,0
```

Then run:

```sh
python3 fantasy_auction_simulator.py --schedule schedule.csv --sims 10000
```

`home` is 1 for home games and 0 for away games. The model gives home sides a 55-Elo advantage; change `HOME_FIELD_ELO` if your league wants a different assumption.

## Draft rule of thumb

1. Bring the printed fair value and cap for every team.
2. First 10–15 nominations: bid fair value at most; let others pay emotional premiums for marquee teams.
3. Track every manager’s remaining cash and team count. A manager with $15 left cannot credibly force you over a $20 cap.
4. Once you have four teams, use the 6% per-extra-team cap reduction. If you have only two or three while the room averages four, a modest 5–10% premium is reasonable.

The simulator deliberately separates **objective fair values** from a price forecast. Auction prices depend heavily on how enthusiastic your seven opponents are, so update `--aggression 1.10` if your room typically overpays by roughly 10%.

## Simulate entire auctions

Add `--auction-sims` to simulate the actual 32 nominations and report the team-count and expected-score distribution for the eight managers:

```sh
python3 fantasy_auction_simulator.py --schedule schedule_2026.csv --sims 10000 --auction-sims 10000
```

The auction model draws a random eight-manager nomination order and repeats it until all 32 teams are nominated, so each manager nominates exactly four. Each manager has a noisy valuation of a team, maintains a cash reserve for later teams, and pays one bid increment above the runner-up. It is a symmetric baseline: its generic “representative manager” should be read as what an evenly skilled room looks like, not a prediction of a particular opponent.

## Which portfolios actually win?

Use `--winner-sims` to simulate an auction followed by a jointly simulated NFL season. The report lists the chance that the manager owning each team wins and the number of teams held by winners.

```sh
python3 fantasy_auction_simulator.py --schedule schedule_2026.csv --sims 10000 --winner-sims 20000
```

The regular-season matchups are simulated once per game, so one team’s win is its opponent’s loss. Tied fantasy high scores split the simulated win credit evenly.
