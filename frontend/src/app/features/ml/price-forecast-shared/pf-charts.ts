import { ChartConfiguration, TooltipItem } from 'chart.js';

import { PfBand, PfModelKey } from '../../../core/models/price-forecast.model';

export type AnyConfig = ChartConfiguration;

/* Model colours: the reference categorical palette's slots 1-5 in fixed order (adjacent pairs validated, light mode);
   each model also has its own dash pattern so lines are never told apart by colour alone. The seasonal naïve is
   the neutral reference. */
export const PF_COLORS: Record<PfModelKey, string> = {
  sarima: '#2a78d6',
  lightgbm: '#eb6834',
  xgboost: '#1baf7a',
  nbeats: '#eda100',
  spike_hybrid: '#e87ba4',
  seasonal_naive: '#8a8f98'
};
export const PF_DASH: Record<PfModelKey, number[]> = {
  sarima: [8, 4],
  lightgbm: [],
  xgboost: [2, 3],
  nbeats: [10, 3, 2, 3],
  spike_hybrid: [],
  seasonal_naive: [4, 4]
};
export const PF_LABELS: Record<PfModelKey, string> = {
  seasonal_naive: 'Seasonal naïve',
  sarima: 'SARIMA',
  lightgbm: 'LightGBM',
  xgboost: 'XGBoost',
  nbeats: 'N-BEATS MLP',
  spike_hybrid: 'Spike hybrid'
};
export const PF_ORDER: PfModelKey[] = ['seasonal_naive', 'sarima', 'lightgbm', 'xgboost', 'nbeats', 'spike_hybrid'];
export const ACTUAL = '#1e232a';
export const INK_MUTED = '#6b6f76';
export const GRID = 'rgba(0, 0, 0, 0.06)';
export const PLANT_OFFSET_MS = 330 * 60 * 1000; // Asia/Kolkata, UTC+05:30

export function plantLabel(ms: number, withDate = true): string {
  const iso = new Date(ms + PLANT_OFFSET_MS).toISOString(); // plant wall-clock time
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const hm = iso.slice(11, 16);
  return withDate ? `${iso.slice(8, 10)} ${months[Number(iso.slice(5, 7)) - 1]} ${hm}` : hm;
}

export function ms(ts: string): number {
  return new Date(ts).getTime();
}

export function axis(title?: string, extra: Record<string, unknown> = {}) {
  return {
    grid: { color: GRID },
    border: { display: false },
    ticks: { color: INK_MUTED, font: { size: 11 } },
    title: title ? { display: true, text: title, color: INK_MUTED, font: { size: 11 } } : { display: false },
    ...extra
  };
}

const SIX_HOURS = 6 * 3600 * 1000;

/** A linear x-axis over epoch milliseconds with a tick every 6 h of plant time. Chart.js's own `stepSize` is not
 *  used: with millisecond bounds its tick generator can derive a non-terminating decimal step and hang the page;
 *  the ticks are set after Chart.js builds its default ones instead. */
export function timeAxis(from: number, to: number) {
  return axis(undefined, {
    type: 'linear',
    min: from,
    max: to,
    afterBuildTicks: (scale: any) => {
      const ticks = [];
      for (let t = Math.ceil((from + PLANT_OFFSET_MS) / SIX_HOURS) * SIX_HOURS - PLANT_OFFSET_MS; t <= to; t += SIX_HOURS) {
        ticks.push({ value: t });
      }
      scale.ticks = ticks;
    },
    ticks: {
      color: INK_MUTED,
      font: { size: 11 },
      maxRotation: 0,
      autoSkip: true,
      callback: (v: number | string) => plantLabel(Number(v))
    }
  });
}

export const tooltip = { backgroundColor: 'rgba(30, 35, 42, 0.92)', padding: 8, titleFont: { size: 12 }, bodyFont: { size: 12 } };

export function legend(show = true) {
  return { display: show, position: 'bottom' as const, labels: { color: '#475569', boxWidth: 14, boxHeight: 10, font: { size: 11 } } };
}

export interface FanInput {
  history: { x: number; y: number | null }[];
  history5?: { x: number; y: number }[];
  model: PfModelKey;
  forecast: { x: number; p10: number | null; p50: number | null; p90: number | null; mean?: number | null }[];
  overlays?: { model: PfModelKey; points: { x: number; y: number | null }[] }[];
  actualAfter?: { x: number; y: number | null }[];
  originMs: number;
  bands: PfBand[];
  showMean?: boolean;
}

/** History, the P10-P90 fan and P50 of one model, other models' P50 as overlays, the actual price after the origin
 *  (backtest), TOU peak bands shaded and the origin marked. One y-axis ($/MWh). */
export function fanChart(f: FanInput): AnyConfig {
  const c = PF_COLORS[f.model];
  const ds: any[] = [];
  if (f.history5?.length) {
    ds.push({ label: 'Price · 5-min', data: f.history5, borderColor: 'rgba(100, 108, 120, 0.45)', borderWidth: 1, pointRadius: 0, order: 6 });
  }
  ds.push({ label: 'Price · hourly', data: f.history, borderColor: ACTUAL, borderWidth: 2, pointRadius: 0, order: 2 });
  if (f.actualAfter?.length) {
    ds.push({ label: 'Actual (after origin)', data: f.actualAfter, borderColor: ACTUAL, borderWidth: 2, borderDash: [], pointRadius: 2, order: 2 });
  }
  ds.push(
    { label: `${PF_LABELS[f.model]} P90`, data: f.forecast.map((p) => ({ x: p.x, y: p.p90 })), borderColor: 'transparent', pointRadius: 0, fill: false, order: 5 },
    {
      label: `${PF_LABELS[f.model]} P10–P90`,
      data: f.forecast.map((p) => ({ x: p.x, y: p.p10 })),
      borderColor: 'transparent',
      backgroundColor: hexA(c, 0.2),
      pointRadius: 0,
      fill: '-1',
      order: 5
    },
    { label: `${PF_LABELS[f.model]} P50`, data: f.forecast.map((p) => ({ x: p.x, y: p.p50 })), borderColor: c, borderWidth: 2.5, pointRadius: 0, order: 1 }
  );
  if (f.showMean) {
    ds.push({ label: `${PF_LABELS[f.model]} mean (with spike risk)`, data: f.forecast.map((p) => ({ x: p.x, y: p.mean ?? null })), borderColor: c, borderWidth: 1.5, borderDash: [3, 3], pointRadius: 0, order: 1 });
  }
  for (const o of f.overlays ?? []) {
    ds.push({ label: `${PF_LABELS[o.model]} P50`, data: o.points, borderColor: PF_COLORS[o.model], borderWidth: 1.5, borderDash: PF_DASH[o.model], pointRadius: 0, order: 3 });
  }
  const xs = [...f.history.map((p) => p.x), ...(f.history5 ?? []).map((p) => p.x), ...f.forecast.map((p) => p.x)];
  const from = Math.min(...xs);
  const to = Math.max(...xs);
  return {
    type: 'line',
    data: { datasets: ds },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: { ...legend(), labels: { ...legend().labels, filter: (item: any) => !item.text.endsWith(' P90') } },
        tooltip: {
          ...tooltip,
          filter: (item: TooltipItem<'line'>) => !(item.dataset.label ?? '').endsWith(' P90') && !(item.dataset.label ?? '').includes('5-min'),
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => {
              const label = ctx.dataset.label ?? '';
              if (label.endsWith('P10–P90')) {
                const hi = (ctx.chart.data.datasets[ctx.datasetIndex - 1].data[ctx.dataIndex] as any)?.y;
                return `${label}: ${fmt(ctx.parsed.y)} – ${fmt(hi)} $/MWh`;
              }
              return `${label}: ${fmt(ctx.parsed.y)} $/MWh`;
            }
          }
        },
        originLine: { x: f.originMs }
      } as any,
      scales: { x: timeAxis(from, to), y: axis('$/MWh', { beginAtZero: true }) }
    },
    plugins: [touBandsPlugin(f.bands, from, to), originLinePlugin]
  } as AnyConfig;
}

/** Spike probability per forecast hour (bars, one series). */
export function spikeChart(points: { x: number; p: number | null }[], from: number, to: number): AnyConfig {
  return {
    type: 'bar',
    data: {
      datasets: [
        {
          label: 'Spike probability',
          data: points.map((p) => ({ x: p.x, y: p.p === null ? null : p.p * 100 })),
          backgroundColor: PF_COLORS.spike_hybrid,
          borderRadius: 3,
          barPercentage: 0.9,
          categoryPercentage: 1
        } as any
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltip,
          callbacks: {
            title: (items: TooltipItem<'bar'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'bar'>) => `Spike probability ${(ctx.parsed.y as number).toFixed(2)} %`
          }
        }
      },
      scales: { x: timeAxis(from, to), y: axis('Spike %', { beginAtZero: true, suggestedMax: 5 }) }
    }
  } as AnyConfig;
}

/** Shades the PEAK / SHOULDER_HIGH TOU bands of every day in view. The bands are captured here rather than passed
 *  as plugin options: Chart.js wraps array options in resolver proxies, and iterating one with for...of hung the page. */
export function touBandsPlugin(bands: PfBand[], from: number, to: number) {
  const shaded = bands
    .filter((b) => b.price_level === 'PEAK' || b.price_level === 'SHOULDER_HIGH')
    .map((b) => ({ start: b.start_hour, end: b.end_hour, peak: b.price_level === 'PEAK' }));
  return {
    id: 'touBands',
    beforeDatasetsDraw(chart: any) {
      if (!shaded.length || !Number.isFinite(from) || !Number.isFinite(to)) {
        return;
      }
      const { ctx, chartArea, scales } = chart;
      const day = 24 * 3600 * 1000;
      // plant midnight before `from`
      const start = Math.floor((from + PLANT_OFFSET_MS) / day) * day - PLANT_OFFSET_MS;
      ctx.save();
      for (let d = start; d < to; d += day) {
        for (const b of shaded) {
          const x0 = scales.x.getPixelForValue(Math.max(d + b.start * 3600e3, from));
          const x1 = scales.x.getPixelForValue(Math.min(d + b.end * 3600e3, to));
          if (x1 <= x0) {
            continue;
          }
          ctx.fillStyle = b.peak ? 'rgba(235, 104, 52, 0.07)' : 'rgba(235, 104, 52, 0.035)';
          ctx.fillRect(x0, chartArea.top, x1 - x0, chartArea.bottom - chartArea.top);
        }
      }
      ctx.restore();
    }
  };
}

export const originLinePlugin = {
  id: 'originLine',
  afterDatasetsDraw(chart: any, _args: unknown, opts: { x?: number; label?: string }) {
    if (opts?.x === undefined) {
      return;
    }
    const { ctx, chartArea, scales } = chart;
    const x = scales.x.getPixelForValue(opts.x);
    ctx.save();
    ctx.strokeStyle = '#475569';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#475569';
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(opts.label ?? 'forecast from here →', x + 6, chartArea.top + 12);
    ctx.restore();
  }
};

export function hexA(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

export function fmt(v: unknown, d = 1): string {
  const n = Number(v);
  return v === null || v === undefined || !Number.isFinite(n) ? '—' : n.toFixed(d);
}
