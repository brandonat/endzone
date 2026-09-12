<script>
  // A dependency-free multi-series line chart with a crosshair tooltip.
  // `series` is [{ id, name, color, points: [{ x, y }] }]; every series is
  // expected to share the same x values (weeks).
  let {
    series = [],
    title = '',
    yLabel = '',
    xLabel = 'Week',
    format = (v) => v.toFixed(1),
    yMin = null,
    yMax = null,
  } = $props();

  const HEIGHT = 260;
  const PAD = { top: 12, right: 16, bottom: 30, left: 46 };

  let width = $state(640);
  let hoverIndex = $state(null);
  let pointerX = $state(0);

  const xs = $derived(series.length ? series[0].points.map((p) => p.x) : []);
  const allY = $derived(series.flatMap((s) => s.points.map((p) => p.y)));

  const TICK_TARGET = 5;

  // Round the axis to 1/2/5 x 10^n steps so the labels read as whole numbers
  // rather than whatever the data range divides into.
  function niceStep(range) {
    const raw = range / TICK_TARGET;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const normalized = raw / magnitude;
    const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return step * magnitude;
  }

  const domain = $derived.by(() => {
    let lo = yMin ?? Math.min(0, ...allY);
    let hi = yMax ?? Math.max(...allY, lo + 1);
    // A flat series would otherwise collapse to a zero-height plot.
    if (hi === lo) hi = lo + 1;
    const step = niceStep(hi - lo);
    return { lo: Math.floor(lo / step) * step, hi: Math.ceil(hi / step) * step, step };
  });

  const plotW = $derived(Math.max(10, width - PAD.left - PAD.right));
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  function sx(x) {
    if (xs.length < 2) return PAD.left + plotW / 2;
    const [lo, hi] = [xs[0], xs[xs.length - 1]];
    return PAD.left + ((x - lo) / (hi - lo)) * plotW;
  }

  function sy(y) {
    const { lo, hi } = domain;
    return PAD.top + plotH - ((y - lo) / (hi - lo)) * plotH;
  }

  function path(points) {
    return points.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ');
  }

  const ticks = $derived.by(() => {
    const { lo, hi, step } = domain;
    const out = [];
    for (let v = lo; v <= hi + step / 2; v += step) out.push(Math.round(v / step) * step);
    return out;
  });

  function onMove(event) {
    if (!xs.length) return;
    const box = event.currentTarget.getBoundingClientRect();
    pointerX = event.clientX - box.left;
    let best = 0;
    for (let i = 1; i < xs.length; i += 1) {
      if (Math.abs(sx(xs[i]) - pointerX) < Math.abs(sx(xs[best]) - pointerX)) best = i;
    }
    hoverIndex = best;
  }

  const hoverRows = $derived(
    hoverIndex === null
      ? []
      : series
          .map((s) => ({ name: s.name, color: s.color, y: s.points[hoverIndex]?.y ?? 0 }))
          .sort((a, b) => b.y - a.y)
  );

  // Keep the tooltip inside the plot instead of letting it run off the right edge.
  const tooltipLeft = $derived(
    hoverIndex === null ? 0 : Math.min(Math.max(sx(xs[hoverIndex]) + 12, 8), Math.max(8, width - 172))
  );
</script>

<figure class="chart" bind:clientWidth={width}>
  {#if title}<figcaption>{title}</figcaption>{/if}

  <div class="plot-wrap">
    <svg
      viewBox="0 0 {width} {HEIGHT}"
      height={HEIGHT}
      role="img"
      aria-label="{title || yLabel} by {xLabel.toLowerCase()}"
      onmousemove={onMove}
      onmouseleave={() => (hoverIndex = null)}
    >
      {#each ticks as tick}
        <line class="grid" x1={PAD.left} x2={width - PAD.right} y1={sy(tick)} y2={sy(tick)} />
        <text class="axis" x={PAD.left - 8} y={sy(tick)} text-anchor="end" dominant-baseline="middle">
          {format(tick)}
        </text>
      {/each}

      {#each xs as x}
        <text class="axis" x={sx(x)} y={HEIGHT - 10} text-anchor="middle">{x === 0 ? 'Pre' : x}</text>
      {/each}

      {#if hoverIndex !== null && xs.length}
        <line class="crosshair" x1={sx(xs[hoverIndex])} x2={sx(xs[hoverIndex])} y1={PAD.top} y2={PAD.top + plotH} />
      {/if}

      {#each series as s (s.id)}
        <path class="line" d={path(s.points)} stroke={s.color} />
      {/each}

      {#each series as s (s.id)}
        {#each s.points as p, i}
          <!-- A 2px surface ring keeps overlapping markers readable. -->
          <circle
            cx={sx(p.x)}
            cy={sy(p.y)}
            r={hoverIndex === i ? 5 : xs.length < 3 ? 4.5 : 3}
            fill={s.color}
            stroke="var(--panel)"
            stroke-width="2"
          />
        {/each}
      {/each}
    </svg>

    {#if hoverIndex !== null}
      <div class="tooltip" style="left: {tooltipLeft}px">
        <div class="tip-head">{xs[hoverIndex] === 0 ? 'Preseason' : `${xLabel} ${xs[hoverIndex]}`}</div>
        {#each hoverRows as row}
          <div class="tip-row">
            <span class="swatch" style="background: {row.color}"></span>
            <span class="tip-name">{row.name}</span>
            <span class="tip-val">{format(row.y)}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- With seven series, identity is carried by the legend rather than direct labels. -->
  <ul class="legend">
    {#each series as s (s.id)}
      <li><span class="swatch" style="background: {s.color}"></span>{s.name}</li>
    {/each}
  </ul>
</figure>

<style>
  .chart {
    margin: 0;
  }

  figcaption {
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-bottom: 8px;
  }

  .plot-wrap {
    position: relative;
  }

  svg {
    width: 100%;
    display: block;
    overflow: visible;
  }

  .grid {
    stroke: var(--border);
    stroke-width: 1;
  }

  .crosshair {
    stroke: var(--muted);
    stroke-width: 1;
    stroke-dasharray: 3 3;
  }

  .line {
    fill: none;
    stroke-width: 2;
    stroke-linejoin: round;
    stroke-linecap: round;
  }

  text.axis {
    fill: var(--muted);
    font-size: 11px;
  }

  .tooltip {
    position: absolute;
    top: 8px;
    min-width: 160px;
    background: #0d0f14;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 10px;
    pointer-events: none;
    font-size: 0.8rem;
  }

  .tip-head {
    color: var(--muted);
    margin-bottom: 6px;
  }

  .tip-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .tip-name {
    flex: 1;
  }

  .tip-val {
    font-variant-numeric: tabular-nums;
  }

  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    flex: none;
  }

  .legend {
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 14px;
    margin: 10px 0 0;
    padding: 0;
    font-size: 0.8rem;
    color: var(--muted);
  }

  .legend li {
    display: flex;
    align-items: center;
    gap: 6px;
  }
</style>
