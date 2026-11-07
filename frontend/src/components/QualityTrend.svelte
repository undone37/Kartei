<script lang="ts">
  import { i18n, t } from '../lib/i18n.svelte'

  type Point = { day: string; total: number; reviewed_ok?: number } & Record<string, any>
  let { points, sections, months }: { points: Point[]; sections: string[]; months: Record<string, number> } = $props()

  // one series at a time: the share reviewed within the interval, or one section's count
  const choices = $derived(['reviewed', ...sections.filter((k) => points.some((p) => typeof p[k] === 'number'))])
  let metric = $state('reviewed')
  const value = (p: Point) => metric === 'reviewed'
    ? (p.total ? Math.round(1000 * (p.reviewed_ok ?? 0) / p.total) / 10 : 0)
    : (p[metric] ?? 0)
  const label = (k: string) => k === 'reviewed' ? t('quality.trend_reviewed') : t(`quality.sec_${k}`, months)
  const unit = $derived(metric === 'reviewed' ? ' %' : '')
  const date = (d: string) => new Date(d + 'T00:00').toLocaleDateString(i18n.lang, { day: 'numeric', month: 'short', year: '2-digit' })

  const W = 640, H = 210, L = 48, R = 12, T = 26, B = 26
  const vals = $derived(points.map(value))
  const top = $derived(metric === 'reviewed' ? 100 : nice(Math.max(1, ...vals)))
  // time axis: older points are monthly, recent ones daily – spaced by date, not by index
  const ms = $derived(points.map((p) => Date.parse(p.day)))
  const x = (i: number) => L + (ms.length < 2 ? 0 : ((ms[i] - ms[0]) * (W - L - R)) / (ms.at(-1)! - ms[0]))
  const num = (v: number) => v.toLocaleString(i18n.lang, { maximumFractionDigits: 1 })
  // hover column of each point: halfway to its neighbours
  const edge = (i: number) => i <= 0 ? L : i >= points.length ? W - R : (x(i - 1) + x(i)) / 2
  const y = (v: number) => T + (H - T - B) * (1 - v / top)
  const path = $derived(vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(''))
  let hover = $state<number | null>(null)

  function nice(n: number) {  // 1, 2, 5 × 10^k at or above n
    const p = 10 ** Math.floor(Math.log10(n))
    return [1, 2, 5, 10].map((m) => m * p).find((m) => m >= n)!
  }
</script>

<section class="card trend">
  <div class="head">
    <h2>{t('quality.trend')}</h2>
    <select class="input" bind:value={metric} aria-label={t('quality.trend')}>
      {#each choices as k (k)}<option value={k}>{label(k)}</option>{/each}
    </select>
  </div>
  {#if points.length < 2}
    <p class="muted">{t('quality.trend_empty')}</p>
  {:else}
    <svg viewBox="0 0 {W} {H}" role="img" aria-label="{label(metric)}: {date(points[0].day)} {num(vals[0])}{unit} – {date(points.at(-1)!.day)} {num(vals.at(-1)!)}{unit}"
         onmouseleave={() => (hover = null)}>
      {#each [0, 0.5, 1] as f (f)}
        <line class="grid" x1={L} x2={W - R} y1={y(top * f)} y2={y(top * f)} />
        <text class="axis" x={L - 6} y={y(top * f) + 4} text-anchor="end">{num(top * f)}{unit}</text>
      {/each}
      <text class="axis" x={L} y={H - 6}>{date(points[0].day)}</text>
      <text class="axis" x={W - R} y={H - 6} text-anchor="end">{date(points.at(-1)!.day)}</text>
      <path class="line" d={path} />
      {#if hover !== null}
        <line class="cross" x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} />
        <circle class="dot" cx={x(hover)} cy={y(vals[hover])} r="4.5" />
        <text class="tip" x={Math.min(Math.max(x(hover), L + 60), W - R - 60)} y={T - 10} text-anchor="middle">
          {date(points[hover].day)}: {num(vals[hover])}{unit}
        </text>
      {/if}
      {#each points as _, i (i)}
        <!-- hit targets wider than the line: the whole column around each point -->
        <rect role="presentation" x={edge(i)} y={T} height={H - T - B} width={Math.max(edge(i + 1) - edge(i), 1)}
              fill="transparent" onmouseenter={() => (hover = i)} />
      {/each}
    </svg>
    <details>
      <summary class="muted">{t('quality.trend_table')}</summary>
      <table>
        <thead><tr><th>{t('quality.trend_day')}</th><th>{label(metric)}</th><th>{t('quality.trend_total')}</th></tr></thead>
        <tbody>
          {#each points.toReversed() as p (p.day)}<tr><td>{date(p.day)}</td><td>{num(value(p))}{unit}</td><td>{p.total}</td></tr>{/each}
        </tbody>
      </table>
    </details>
  {/if}
</section>

<style>
  .trend { padding: 12px 16px; display: grid; gap: 8px; }
  .head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  h2 { font-size: 15px; margin: 0; }
  .head select { width: auto; max-width: 100%; margin-left: auto; }
  svg { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .axis { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .line { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .cross { stroke: var(--border-strong); stroke-width: 1; }
  .dot { fill: var(--accent); stroke: var(--panel); stroke-width: 2; }
  .tip { fill: var(--text); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
  details { font-size: 13px; }
  summary { cursor: pointer; }
  table { border-collapse: collapse; margin-top: 6px; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 2px 16px 2px 0; }
  th { color: var(--muted); font-weight: 500; }
</style>
