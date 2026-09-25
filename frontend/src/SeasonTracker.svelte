<script>
  import { onMount } from 'svelte';
  import LineChart from './LineChart.svelte';
  import ScoreDistributionChart from './ScoreDistributionChart.svelte';
  import ScheduleGrid from './ScheduleGrid.svelte';

  // Categorical slots 1-7 of the validated dark-mode palette, assigned in fixed
  // order and keyed to the manager, so a manager keeps their colour as ranks move.
  const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9'];

  let season = $state(null);
  let loading = $state(true);
  let refreshing = $state(false);
  let error = $state('');
  // Manager whose leaderboard row is expanded to show their teams' schedule.
  let selectedId = $state(null);

  function toggleManager(id) {
    selectedId = selectedId === id ? null : id;
  }

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

  const scoreDistribution = $derived(
    season
      ? season.leaderboard.map((entry) => ({
          id: entry.manager_id,
          name: entry.name,
          color: colorOf.get(entry.manager_id),
          mean: entry.projected_final,
          sd: entry.sd,
        }))
      : [],
  );

  function recordOf(team) {
    const { w, l, t } = team.record;
    return t ? `${w}-${l}-${t}` : `${w}-${l}`;
  }

  async function fetchJson(url, options) {
    const res = await fetch(url, options);
    // A gateway timeout or an unhandled server error comes back as plain text
    // or HTML, so parse the body by hand rather than letting res.json() throw
    // a message that says nothing about what actually went wrong.
    const text = await res.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      throw new Error(
        res.ok
          ? 'The server sent a response that was not valid JSON.'
          : `Server responded ${res.status} ${res.statusText}. ${text.slice(0, 200)}`.trim(),
      );
    }
    if (!res.ok) throw new Error(body.detail || `Server responded ${res.status}`);
    return body;
  }

  async function load(refresh = false) {
    error = '';
    if (refresh) refreshing = true;
    try {
      // Refreshing is two calls: the POST answers with a short summary rather
      // than the payload (the scheduled warm-up job that also calls it cannot
      // read a 65 KB response), and the GET then serves the rebuilt payload
      // from the cache the POST just filled.
      if (refresh) await fetchJson('/api/season/refresh', { method: 'POST' });
      season = await fetchJson('/api/season');
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
    <h2>Leaderboard <span class="muted hint">— click a manager to expand their schedule</span></h2>
    <div class="table-scroll">
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
            <tr
              class="clickable"
              class:selected={entry.manager_id === selectedId}
              tabindex="0"
              aria-expanded={entry.manager_id === selectedId}
              onclick={() => toggleManager(entry.manager_id)}
              onkeydown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  toggleManager(entry.manager_id);
                }
              }}
            >
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
            {#if entry.manager_id === selectedId}
              <tr class="expanded">
                <td colspan="7">
                  <!-- width: 0 + min-width: 100% stops the wide grid from
                       stretching the leaderboard; it scrolls inside instead. -->
                  <div class="expanded-body">
                    <ScheduleGrid games={season.games} only={entry.teams.map((t) => t.team)} />
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
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

    <div class="chart-row">
      <div class="card">
        <LineChart
          title="Title odds by week"
          series={oddsSeries}
          format={(v) => `${v.toFixed(0)}%`}
          yMin={0}
        />
      </div>

      <div class="card">
        <ScoreDistributionChart title="Projected final points" series={scoreDistribution} />
      </div>
    </div>
  {/if}

  <div class="card">
    <h2>Schedule</h2>
    <ScheduleGrid games={season.games} />
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

  .hint {
    font-weight: 400;
    font-size: 0.8rem;
  }

  tr.clickable {
    cursor: pointer;
  }

  tr.clickable:hover td {
    background: rgba(255, 255, 255, 0.03);
  }

  tr.selected td {
    background: rgba(var(--accent-rgb), 0.12);
    border-bottom-color: transparent;
  }

  tr.clickable:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  tr.expanded > td {
    padding: 4px 0 14px 12px;
    box-shadow: inset 3px 0 0 var(--accent);
  }

  .expanded-body {
    width: 0;
    min-width: 100%;
  }

  .chart-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }

  @media (max-width: 720px) {
    .chart-row {
      grid-template-columns: 1fr;
    }
  }
</style>
