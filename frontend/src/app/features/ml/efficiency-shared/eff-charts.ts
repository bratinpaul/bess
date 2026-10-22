import { ChartConfiguration, TooltipItem } from 'chart.js';

import { EffCurves, EffDirection, EffModelKey } from '../../../core/models/efficiency.model';

/* Model colours (checked with the dataviz palette validator, light mode): grey-box, GAM, hybrid.
   Measured readings are neutral grey; the hybrid is also drawn thicker so identity isn't colour alone. */
export const MODEL_COLORS: Record<EffModelKey, string> = { greybox: '#2a78d6', gam: '#2aa198', hybrid: '#d9480f' };
export const MODEL_LABELS: Record<EffModelKey, string> = {
  greybox: 'Grey-box loss model',
  gam: 'GAM',
  hybrid: 'Hybrid (grey-box + boosting)'
};
export const MODEL_KEYS: EffModelKey[] = ['greybox', 'gam', 'hybrid'];
export const MEASURED = 'rgba(100, 108, 120, 0.35)';
export const MEASURED_TEST = 'rgba(71, 85, 105, 0.7)';
export const INK = '#475569';
export const INK_MUTED = '#6b6f76';
export const GRID = 'rgba(0, 0, 0, 0.06)';
export const SERIES = ['#2a78d6', '#2aa198', '#d9480f', '#6d5bd0', '#b7791f', '#475569'];

export type AnyConfig = ChartConfiguration;

export function axis(title?: string, extra: Record<string, unknown> = {}) {
  return {
    grid: { color: GRID },
    border: { display: false },
    ticks: { color: INK_MUTED, font: { size: 11 } },
    title: title ? { display: true, text: title, color: INK_MUTED, font: { size: 11 } } : { display: false },
    ...extra
  };
}

export function legend(show = true) {
  return { display: show, position: 'bottom' as const, labels: { color: INK, boxWidth: 12, boxHeight: 12, font: { size: 11 } } };
}

export const tooltip = { backgroundColor: 'rgba(30, 35, 42, 0.92)', padding: 8, titleFont: { size: 12 }, bodyFont: { size: 12 } };

/** η vs load: one line per model (from a run's or an estimate's curves), optional measured readings and a marker. */
export function curveChart(
  curves: EffCurves,
  direction: EffDirection,
  measured: { x: number; y: number; test?: boolean }[] = [],
  marker?: { x: number; y: number; label: string }
): AnyConfig {
  const c = curves[direction];
  const datasets: any[] = [];
  if (measured.length) {
    datasets.push({
      type: 'scatter',
      label: 'Measured',
      data: measured.map((m) => ({ x: m.x * 100, y: m.y })),
      backgroundColor: measured.map((m) => (m.test ? MEASURED_TEST : MEASURED)),
      pointRadius: 2.5,
      pointHoverRadius: 5,
      order: 5
    });
  }
  for (const k of MODEL_KEYS) {
    datasets.push({
      type: 'line',
      label: MODEL_LABELS[k],
      data: c.points.map((p) => ({ x: p.load_frac * 100, y: p[k] })),
      borderColor: MODEL_COLORS[k],
      backgroundColor: MODEL_COLORS[k],
      borderWidth: k === 'hybrid' ? 3 : 2,
      borderDash: k === 'gam' ? [6, 4] : [],
      pointRadius: 0,
      tension: 0.25,
      order: 1
    });
  }
  if (marker) {
    datasets.push({
      type: 'scatter',
      label: marker.label,
      data: [{ x: marker.x * 100, y: marker.y }],
      backgroundColor: '#1e232a',
      borderColor: '#ffffff',
      borderWidth: 2,
      pointRadius: 7,
      pointStyle: 'rectRot',
      order: 0
    });
  }
  const ys = [...c.points.flatMap((p) => MODEL_KEYS.map((k) => p[k])), ...measured.map((m) => m.y)];
  const lo = Math.max(85, Math.floor(Math.min(...ys) - 0.3));
  const observed = c.observed;
  return {
    type: 'scatter',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: legend(),
        tooltip: {
          ...tooltip,
          callbacks: {
            label: (ctx: TooltipItem<'scatter'>) =>
              `${ctx.dataset.label}: ${(ctx.parsed.y as number).toFixed(2)} % at ${(ctx.parsed.x as number).toFixed(0)} % load`
          }
        },
        // shades the load range the unit actually ran at (outside it the curves extrapolate)
        observedBand: observed ? { from: observed[0] * 100, to: observed[1] * 100 } : undefined
      } as any,
      scales: {
        x: axis('Load |P| / rated (%)', { min: 0, max: 100 }),
        y: axis('Conversion efficiency η (%)', { min: lo, max: 100 })
      }
    },
    plugins: [observedBandPlugin]
  } as AnyConfig;
}

/** Light band behind the load range the readings cover. */
export const observedBandPlugin = {
  id: 'observedBand',
  beforeDatasetsDraw(chart: any, _args: unknown, opts: { from?: number; to?: number }) {
    if (opts?.from === undefined || opts?.to === undefined) {
      return;
    }
    const { ctx, chartArea, scales } = chart;
    const x0 = scales.x.getPixelForValue(opts.from);
    const x1 = scales.x.getPixelForValue(opts.to);
    ctx.save();
    ctx.fillStyle = 'rgba(99, 248, 186, 0.12)';
    ctx.fillRect(x0, chartArea.top, x1 - x0, chartArea.bottom - chartArea.top);
    ctx.fillStyle = INK_MUTED;
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('operating range in the data', x0 + 6, chartArea.top + 14);
    ctx.restore();
  }
};

/** Horizontal bars (one series), largest first; values formatted by `fmt`. */
export function hbar(labels: string[], values: number[], color: string | string[], fmt: (v: number) => string, title?: string): AnyConfig {
  return {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: color, borderRadius: 4, borderSkipped: false, barThickness: 14 }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      layout: { padding: { right: 48 } },
      plugins: {
        legend: { display: false },
        tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => fmt(ctx.parsed.x as number) } },
        valueLabels: { format: (v: number) => fmt(v) }
      } as any,
      scales: { x: axis(title), y: axis(undefined, { grid: { display: false } }) }
    }
  } as AnyConfig;
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v) ? '—' : `${v.toFixed(digits)} %`;
}

export function fmtNum(v: number | null | undefined, digits = 3): string {
  return v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(digits);
}
