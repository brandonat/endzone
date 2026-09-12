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
The app has two tabs: **Season** (live standings) and **Draft board** (the auction view above).

## Season tracker

Once the draft is done, the league scores one point per NFL win and half a point per tie,
summed over every team a manager owns.

```sh
python3 nfl_scores.py --refresh --show   # pull results from ESPN into season_results.json
python3 season.py                        # leaderboard, projections, and title odds
```

`nfl_scores.py` reads ESPN's public scoreboard endpoint — no API key, standard library only.
It caches to `season_results.json` and only re-fetches weeks that still have a non-final
game, so polling it is cheap. Exactly one team code differs between the two sources
(ESPN's `WSH` is the board's `WAS`); the bundled `schedule_2026.csv` otherwise agrees with
ESPN on all 272 regular-season games.

`season.py` conditions on what has actually happened rather than re-running the preseason
model. Completed games are banked as real points, team Elo ratings are updated from those
results (538-style, K=20 with a margin-of-victory multiplier), and only the games still on
the schedule are simulated. So a projected final score is `points already banked +
simulated wins from here`, and the title odds move as the season plays out.

The backend exposes the same data to the UI:

- `GET /api/season` — leaderboard, projections, week-by-week history, and every game.
- `POST /api/season/refresh` — pull fresh scores from ESPN, then rebuild the above.

The projection is a few hundred thousand simulated games, so the server computes it once
per distinct set of results and reuses it until a score changes.

## WhatsApp updates

`whatsapp_notify.py` posts an update to a WhatsApp chat after games go final, driving
WhatsApp Web through a headless browser. **Sending is opt-in**: without `--send` it only
prints what it would post.

```sh
pip install -r requirements.txt
python3 -m playwright install chromium
python3 whatsapp_notify.py --login          # one-time: scan the QR in the browser window
python3 whatsapp_notify.py --refresh        # dry run — print the update
python3 whatsapp_notify.py --refresh --send # actually post it
python3 whatsapp_notify.py --watch 300 --send   # poll every 5 minutes
```

`--login` saves a logged-in browser profile to `~/.endzone/whatsapp-profile`, after which
sends run headless against that session. Set the target chat and the link back to the board
in `notify_config.json`; the `chat` value must match the chat title in WhatsApp exactly.
Announced games are recorded in `notify_state.json`, so a repeated run stays quiet until
something new goes final (`--force` re-announces the latest week).

A posted update looks like this:

```
*Endzone · Week 1*

SEA beat NE 13-10; SF beat LAR 27-7

*Leaderboard*
1. Charlie — 1.0 pts (41% title)
1. Martin — 1.0 pts (2% title)
3. Rahim — 0.0 pts (26% title)
...
```


The included `schedule_2026.csv` is the provided 4for4 regular-season grid. Run the simulator against it with:

```sh
python3 fantasy_auction_simulator.py --schedule schedule_2026.csv --sims 10000
```

It starts with the supplied Elo ratings, simulates season results, and converts expected scoring into a budget-neutral fair-value board.  Since the league has 7 x $100 = $700 total purchasing power, the fair board sums to exactly $700.  That is a useful anchor: if a top team costs $65, you need an explicit reason why its portfolio advantage is worth taking $25-plus away from your remaining teams.

## Why this is a better starting point than “buy the best team”

Each team’s fantasy score is its season wins (a tie would be 0.5; the supplied model currently treats NFL games as decisive). A player’s expected total is the sum across owned teams.  The initial fair values therefore allocate the $700 in proportion to expected points.  At an average 8.5 wins per NFL team, each expected season point initially costs about $2.57.

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

Add `--auction-sims` to simulate the actual 32 nominations and report the team-count and expected-score distribution for the seven managers:

```sh
python3 fantasy_auction_simulator.py --schedule schedule_2026.csv --sims 10000 --auction-sims 10000
```

The auction model draws a random seven-manager nomination order and repeats it until all 32 teams are nominated. Four managers therefore nominate five teams and three nominate four. Each manager has a noisy valuation of a team, maintains a cash reserve for later teams, and pays one bid increment above the runner-up. It is a symmetric baseline: its generic “representative manager” should be read as what an evenly skilled room looks like, not a prediction of a particular opponent.

## Which portfolios actually win?

Use `--winner-sims` to simulate an auction followed by a jointly simulated NFL season. The report lists the chance that the manager owning each team wins and the number of teams held by winners.

```sh
python3 fantasy_auction_simulator.py --schedule schedule_2026.csv --sims 10000 --winner-sims 20000
```

The regular-season matchups are simulated once per game, so one team’s win is its opponent’s loss. Tied fantasy high scores split the simulated win credit evenly.
