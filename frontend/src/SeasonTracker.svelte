<script>
  import { onMount } from 'svelte';
  import LineChart from './LineChart.svelte';

  // Categorical slots 1-7 of the validated dark-mode palette, assigned in fixed
  // order and keyed to the manager, so a manager keeps their colour as ranks move.
  const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9'];

  let season = $state(null);
  let loading = $state(true);
  let refreshing = $state(false);
  let error = $state('');

  const colorOf = $derived.by(() => {
    const map = new Map();
    if (season) {
      // Ordered by manager id so the mapping is stable across refreshes.
      const ids = season.leaderboard.map((e) => e.manager_id).sort();
      ids.forEach((id, i) => map.set(id, SERIES_COLORS[i % SERIES_COLORS.length]));
    }
    return map;
  });

  const nameOf = $derived.by(() => {
    const map = new Map();
    if (season) for (const entry of season.leaderboard) map.set(entry.manager_id, entry.name);
    return map;
  });

  function seriesFrom(key) {
    if (!season || !season.history.length) return [];
    return [...colorOf.keys()]
      .map((id) => ({
        id,
        name: nameOf.get(id),
        color: colorOf.get(id),
        points: season.history.map((h) => ({ x: h.week, y: h[key][id] ?? 0 })),
      }))
      // Highest current value first, so the legend reads like the standings.
      .sort((a, b) => b.points.at(-1).y - a.points.at(-1).y);
  }

  const pointsSeries = $derived(seriesFrom('points'));
  const oddsSeries = $derived(seriesFrom('title_odds'));

  const finishedGames = $derived(season ? season.games.filter((g) => g.completed) : []);
  const recentWeeks = $derived.by(() => {
    const byWeek = new Map();
    for (const game of finishedGames) {
      if (!byWeek.has(game.week)) byWeek.set(game.week, []);
      byWeek.get(game.week).push(game);
    }
    return [...byWeek.entries()].sort((a, b) => b[0] - a[0]);
  });

  function describe(game) {
    if (game.tie) return `${game.home} and ${game.away} tied ${game.home_score}-${game.away_score}`;
    const loser = game.winner === game.home ? game.away : game.home;
    const high = Math.max(game.home_score, game.away_score);
    const low = Math.min(game.home_score, game.away_score);
    return `${game.winner} beat ${loser} ${high}-${low}`;
  }

  function recordOf(team) {
    const { w, l, t } = team.record;
    return t ? `${w}-${l}-${t}` : `${w}-${l}`;
  }

  async function load(refresh = false) {
    error = '';
    if (refresh) refreshing = true;
    try {
      const res = await fetch(refresh ? '/api/season/refresh' : '/api/season', {
        method: refresh ? 'POST' : 'GET',
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `Server responded ${res.status}`);
      season = body;
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
      refreshing = false;
    }
  }

  onMount(load);
</script>

{#if error}
  <div class="card error">
    <p>{error}</p>
    <button onclick={() => load(true)} disabled={refreshing}>
      {refreshing ? 'Refreshing…' : 'Refresh scores'}
    </button>
  </div>
{/if}

{#if season}
  <div class="card season-head">
    <div>
      <span class="big">{season.games_played}</span>
      <span class="muted">of {season.games_total} games played</span>
      {#if season.fetched_at}
        <div class="muted small">Scores fetched {new Date(season.fetched_at).toLocaleString()}</div>
      {/if}
    </div>
    <button onclick={() => load(true)} disabled={refreshing}>
      {refreshing ? 'Refreshing…' : 'Refresh scores'}
    </button>
  </div>

  <div class="card">
    <h2>Leaderboard</h2>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Manager</th>
          <th class="num">Points</th>
          <th class="num">Projected</th>
          <th class="num">P10–P90</th>
          <th class="num">Title odds</th>
          <th>Teams</th>
        </tr>
      </thead>
      <tbody>
        {#each season.leaderboard as entry (entry.manager_id)}
          <tr>
            <td>{entry.rank}</td>
            <td>
              <span class="swatch" style="background: {colorOf.get(entry.manager_id)}"></span>
              {entry.name}
            </td>
            <td class="num strong">{entry.points.toFixed(1)}</td>
            <td class="num">{entry.projected_final.toFixed(1)}</td>
            <td class="num muted">{entry.p10.toFixed(0)}–{entry.p90.toFixed(0)}</td>
            <td class="num">{entry.title_odds.toFixed(1)}%</td>
            <td>
              <ul class="chips">
                {#each entry.teams as team (team.team)}
                  <li title="{team.team}: {recordOf(team)}, {team.points} pts, projected {team.projected_wins.toFixed(1)} wins">
                    <span class="team-tag">{team.team}</span>
                    <span class="muted">{recordOf(team)}</span>
                  </li>
                {/each}
              </ul>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if season.history.length}
    <div class="card">
      <LineChart
        title="Points by week"
        series={pointsSeries}
        format={(v) => v.toFixed(1)}
        yMin={0}
      />
    </div>

    <div class="card">
      <LineChart
        title="Title odds by week"
        series={oddsSeries}
        format={(v) => `${v.toFixed(0)}%`}
        yMin={0}
      />
    </div>
  {/if}

  <div class="card">
    <h2>Results</h2>
    {#if !finishedGames.length}
      <p class="empty">No games have gone final yet.</p>
    {:else}
      {#each recentWeeks as [week, games] (week)}
        <h3>Week {week}</h3>
        <ul class="results">
          {#each games as game (game.id)}
            <li>{describe(game)}</li>
          {/each}
        </ul>
      {/each}
    {/if}
  </div>
{:else if loading}
  <p class="empty">Loading season…</p>
{/if}

<style>
  .season-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }

  .error p {
    margin: 0 0 8px;
  }

  .big {
    font-size: 2rem;
    font-weight: 700;
  }

  .muted {
    color: var(--muted);
  }

  .small {
    font-size: 0.8rem;
    margin-top: 4px;
  }

  .strong {
    font-weight: 700;
  }

  .swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    margin-right: 6px;
  }

  .chips {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }

  .chips li {
    display: flex;
    gap: 5px;
    background: #0d0f14;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 9px;
    font-size: 0.75rem;
  }

  .team-tag {
    font-weight: 600;
  }

  h3 {
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin: 14px 0 6px;
  }

  h3:first-of-type {
    margin-top: 0;
  }

  .results {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 0.9rem;
  }
</style>
