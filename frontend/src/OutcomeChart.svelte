<script>
  // A finish-probability heatmap: rows are players (in leaderboard order),
  // columns are final ranks, and cell intensity is a single-hue sequential
  // wash of --accent (magnitude), so it never competes with the per-manager
  // identity colors used elsewhere on the page.
  let { title = '', entries = [] } = $props();

  const ranks = $derived(entries.length ? Array.from({ length: entries.length }, (_, i) => i + 1) : []);

  function valueAt(entry, rank) {
    return entry.distribution[rank] ?? 0;
  }

  // A shared 0..max domain (rather than 0..100) keeps the gradient legible
  // even in a wide-open race where no single outcome dominates.
  const domainMax = $derived(
    Math.max(1, ...entries.flatMap((e) => ranks.map((r) => valueAt(e, r)))),
  );

  function opacityFor(value) {
    if (value <= 0) return 0.05;
    return 0.08 + (value / domainMax) * 0.82;
  }

  function ordinal(n) {
    const v = n % 100;
    if (v >= 11 && v <= 13) return `${n}th`;
    return n + (['th', 'st', 'nd', 'rd'][n % 10] || 'th');
  }
</script>

<figure class="heatmap">
  {#if title}<figcaption>{title}</figcaption>{/if}

  {#if entries.length}
    <div class="grid-scroll">
      <div class="grid" style="grid-template-columns: minmax(90px, auto) repeat({ranks.length}, 1fr);">
        <div class="corner"></div>
        {#each ranks as rank}
          <div class="col-head">{ordinal(rank)}</div>
        {/each}

        {#each entries as entry (entry.manager_id)}
          <div class="row-head">
            <span class="swatch" style="background: {entry.color}"></span>
            {entry.name}
          </div>
          {#each ranks as rank}
            {@const value = valueAt(entry, rank)}
            <div
              class="cell"
              style="background: rgba(var(--accent-rgb), {opacityFor(value)});"
              title="{entry.name}: {value.toFixed(1)}% to finish {ordinal(rank)}"
            >
              {value >= 1 ? Math.round(value) : value > 0 ? '<1' : '—'}{value > 0 ? '%' : ''}
            </div>
          {/each}
        {/each}
      </div>
    </div>
  {/if}
</figure>

<style>
  .heatmap {
    margin: 0;
  }

  figcaption {
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-bottom: 8px;
  }

  .grid-scroll {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .grid {
    display: grid;
    gap: 3px;
    align-items: center;
  }

  .corner {
    min-width: 90px;
  }

  .col-head {
    text-align: center;
    font-size: 0.7rem;
    color: var(--muted);
    padding-bottom: 4px;
  }

  .row-head {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.8rem;
    white-space: nowrap;
    padding-right: 8px;
  }

  .swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    flex: none;
  }

  .cell {
    text-align: center;
    padding: 7px 4px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
    color: var(--text);
    min-width: 44px;
  }
</style>
