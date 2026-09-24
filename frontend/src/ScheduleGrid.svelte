<script>
  // Full-season schedule: one row per NFL team (alphabetical), one column per
  // week. A cell shows the matchup (opponent, @ prefixed for road games) and,
  // once the game is final, the row team's own score first and a soft
  // win/loss wash; a week the team doesn't play is a BYE. Pass `only` to show
  // just those teams (e.g. one manager's roster) instead of the whole league.
  let { games = [], only = null } = $props();

  const teams = $derived(
    only ? [...only].sort() : [...new Set(games.flatMap((g) => [g.home, g.away]))].sort(),
  );
  const weeks = $derived([...new Set(games.map((g) => g.week))].sort((a, b) => a - b));

  const byTeamWeek = $derived.by(() => {
    const map = new Map();
    for (const game of games) {
      for (const team of [game.home, game.away]) {
        if (!map.has(team)) map.set(team, new Map());
        map.get(team).set(game.week, game);
      }
    }
    return map;
  });

  function cellOf(team, week) {
    const game = byTeamWeek.get(team)?.get(week);
    if (!game) return { kind: 'bye' };

    const isHome = game.home === team;
    const opponent = isHome ? game.away : game.home;
    const matchup = (isHome ? '' : '@') + opponent;

    if (!game.completed) return { kind: 'scheduled', matchup };

    const own = isHome ? game.home_score : game.away_score;
    const opp = isHome ? game.away_score : game.home_score;
    const kind = game.tie ? 'tie' : game.winner === team ? 'win' : 'loss';
    return { kind, matchup, score: `${own}-${opp}` };
  }
</script>

<div class="table-scroll">
  <table class="schedule">
    <thead>
      <tr>
        <th class="team-head">Team</th>
        {#each weeks as week}
          <th class="num">{week}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each teams as team (team)}
        <tr>
          <td class="team-cell">{team}</td>
          {#each weeks as week}
            {@const cell = cellOf(team, week)}
            <td class="num">
              <div class="cell {cell.kind}">
                {#if cell.kind === 'bye'}
                  BYE
                {:else}
                  <div class="matchup">{cell.matchup}</div>
                  {#if cell.score}<div class="score">{cell.score}</div>{/if}
                {/if}
              </div>
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  table.schedule {
    font-size: 0.78rem;
  }

  th,
  td {
    padding: 5px !important;
  }

  .team-head,
  .team-cell {
    position: sticky;
    left: 0;
    background: var(--panel);
    padding-right: 10px !important;
  }

  .team-cell {
    font-weight: 700;
  }

  .cell {
    min-width: 44px;
    padding: 4px;
    border-radius: 4px;
    text-align: center;
  }

  .cell.win {
    background: var(--up-soft);
  }

  .cell.loss {
    background: var(--down-soft);
  }

  .cell.tie {
    background: var(--tie-soft);
  }

  .cell.bye {
    color: var(--muted);
    background: rgba(255, 255, 255, 0.04);
  }

  .matchup {
    font-weight: 600;
  }

  .score {
    color: var(--muted);
    font-size: 0.7rem;
    margin-top: 1px;
  }
</style>
