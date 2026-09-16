<script>
  // Each player's projected final score as a normal curve (mean = projected
  // final, sd = the Monte Carlo standard deviation the projection already
  // computes), overlaid so the reader can see how much their outcomes could
  // plausibly overlap rather than just comparing single projected numbers.
  let {
    series = [], // [{ id, name, color, mean, sd }]
    title = '',
    xLabel = 'Final points',
  } = $props();

  const HEIGHT = 260;
  const PAD = { top: 12, right: 16, bottom: 30, left: 38 };
  const SAMPLES = 140;
  const TICK_TARGET = 5;

  let width = $state(640);
  let hoverPx = $state(null);

  function gaussian(x, mean, sd) {
    const s = Math.max(sd, 0.5);
    const z = (x - mean) / s;
    return Math.exp(-0.5 * z * z) / (s * Math.sqrt(2 * Math.PI));
  }

  // Round the axis to 1/2/5 x 10^n steps so the labels read as whole numbers.
  function niceStep(range) {
    const raw = range / TICK_TARGET;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const normalized = raw / magnitude;
    const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return step * magnitude;
  }

  const xDomain = $derived.by(() => {
    if (!series.length) return { lo: 0, hi: 1, step: 1 };
    let lo = Math.min(...series.map((s) => s.mean - 3 * s.sd));
    let hi = Math.max(...series.map((s) => s.mean + 3 * s.sd));
    if (hi === lo) hi = lo + 1;
    const step = niceStep(hi - lo);
    return { lo: Math.max(0, Math.floor(lo / step) * step), hi: Math.ceil(hi / step) * step, step };
  });

  const xTicks = $derived.by(() => {
    const { lo, hi, step } = xDomain;
    const out = [];
    for (let v = lo; v <= hi + step / 2; v += step) out.push(Math.round(v / step) * step);
    return out;
  });

  // Reading order matches the other charts: the manager most likely to finish
  // highest leads, so the legend reads like the standings.
  const curves = $derived(
    [...series]
      .sort((a, b) => b.mean - a.mean)
      .map((s) => {
        const { lo, hi } = xDomain;
        const points = Array.from({ length: SAMPLES + 1 }, (_, i) => {
          const x = lo + ((hi - lo) * i) / SAMPLES;
          return { x, y: gaussian(x, s.mean, s.sd) };
        });
        return { ...s, points };
      }),
  );

  // One shared peak across every curve, so height is comparable series to
  // series instead of each curve being independently rescaled to fill the plot.
  const peak = $derived(Math.max(1e-9, ...curves.flatMap((c) => c.points.map((p) => p.y))));

  const plotW = $derived(Math.max(10, width - PAD.left - PAD.right));
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  function sx(x) {
    const { lo, hi } = xDomain;
    return PAD.left + ((x - lo) / (hi - lo)) * plotW;
  }
  function sy(y) {
    return PAD.top + plotH - (y / peak) * plotH;
  }
  function invertX(px) {
    const { lo, hi } = xDomain;
    return lo + ((px - PAD.left) / plotW) * (hi - lo);
  }

  function linePath(points) {
    return points.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ');
  }
  function areaPath(points) {
    const base = PAD.top + plotH;
    const first = points[0];
    const last = points[points.length - 1];
    return `${linePath(points)} L${sx(last.x).toFixed(1)},${base.toFixed(1)} L${sx(first.x).toFixed(1)},${base.toFixed(1)} Z`;
  }

  function onMove(event) {
    const box = event.currentTarget.getBoundingClientRect();
    hoverPx = Math.min(Math.max(event.clientX - box.left, PAD.left), width - PAD.right);
  }

  const hoverX = $derived(hoverPx === null ? null : invertX(hoverPx));

  // Density values are only meaningful relative to one another, so the
  // tooltip reports each curve's height as a share of the tallest point on
  // the whole chart rather than the raw (unitless) density.
  const hoverRows = $derived(
    hoverX === null
      ? []
      : curves
          .map((c) => ({ name: c.name, color: c.color, pct: (gaussian(hoverX, c.mean, c.sd) / peak) * 100 }))
          .sort((a, b) => b.pct - a.pct),
  );

  const tooltipLeft = $derived(
    hoverPx === null ? 0 : Math.min(Math.max(hoverPx + 12, 8), Math.max(8, width - 172)),
  );
</script>

<figure class="chart" bind:clientWidth={width}>
  {#if title}<figcaption>{title}</figcaption>{/if}

  <div class="plot-wrap">
    <svg
      viewBox="0 0 {width} {HEIGHT}"
      height={HEIGHT}
      role="img"
      aria-label="{title || 'Projected final points'} distribution by player"
      onmousemove={onMove}
      onmouseleave={() => (hoverPx = null)}
    >
      {#each [0, 0.5, 1] as frac}
        <line class="grid" x1={PAD.left} x2={width - PAD.right} y1={sy(peak * frac)} y2={sy(peak * frac)} />
        <text class="axis" x={PAD.left - 8} y={sy(peak * frac)} text-anchor="end" dominant-baseline="middle">
          {Math.round(frac * 100)}%
        </text>
      {/each}

      {#each xTicks as tick}
        <text class="axis" x={sx(tick)} y={HEIGHT - 10} text-anchor="middle">{tick}</text>
      {/each}

      {#if hoverX !== null}
        <line class="crosshair" x1={hoverPx} x2={hoverPx} y1={PAD.top} y2={PAD.top + plotH} />
      {/if}

      {#each curves as c (c.id)}
        <path class="area" d={areaPath(c.points)} fill={c.color} />
      {/each}

      {#each curves as c (c.id)}
        <path class="line" d={linePath(c.points)} stroke={c.color} />
      {/each}

      {#if hoverX !== null}
        {#each curves as c (c.id)}
          <circle
            cx={hoverPx}
            cy={sy(gaussian(hoverX, c.mean, c.sd))}
            r="4"
            fill={c.color}
            stroke="var(--panel)"
            stroke-width="2"
          />
        {/each}
      {/if}
    </svg>

    {#if hoverX !== null}
      <div class="tooltip" style="left: {tooltipLeft}px">
        <div class="tip-head">{Math.round(hoverX)} {xLabel.toLowerCase()}</div>
        {#each hoverRows as row}
          <div class="tip-row">
            <span class="swatch" style="background: {row.color}"></span>
            <span class="tip-name">{row.name}</span>
            <span class="tip-val">{row.pct.toFixed(0)}%</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <ul class="legend">
    {#each curves as c (c.id)}
      <li><span class="swatch" style="background: {c.color}"></span>{c.name}</li>
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

  .area {
    fill-opacity: 0.1;
    stroke: none;
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
