import { TooltipItem } from 'chart.js';

import { NfModelKey, NfRegressorKey } from '../../../core/models/netload-forecast.model';
import {
  ACTUAL,
  AnyConfig,
  INK_MUTED,
  PLANT_OFFSET_MS,
  axis,
  fmt,
  hexA,
  legend,
  originLinePlugin,
  plantLabel,
  timeAxis,
  tooltip
} from '../price-forecast-shared/pf-charts';

export { ACTUAL, axis, fmt, hexA, legend, plantLabel, tooltip };
export type { AnyConfig };

/* Model colours: the reference categorical palette's slots in fixed order (as on the price forecast); each model
   also has its own dash pattern so lines are never told apart by colour alone. The seasonal naïve is the neutral
   reference. */
export const NF_COLORS: Record<NfModelKey, string> = {
  seasonal_naive: '#8a8f98',
  sarima: '#2a78d6',
  lightgbm: '#eb6834',
  nbeats: '#eda100',
  peak_classifier: '#e87ba4'
};
export const NF_DASH: Record<NfModelKey, number[]> = {
  seasonal_naive: [4, 4],
  sarima: [8, 4],
  lightgbm: [],
  nbeats: [10, 3, 2, 3],
  peak_classifier: []
};
export const NF_LABELS: Record<NfModelKey, string> = {
  seasonal_naive: 'Seasonal naïve',
  sarima: 'SARIMAX',
  lightgbm: 'LightGBM',
  nbeats: 'N-BEATS MLP',
  peak_classifier: 'Peak classifier'
};
export const NF_ORDER: NfRegressorKey[] = ['seasonal_naive', 'sarima', 'lightgbm', 'nbeats'];
export const THRESHOLD = '#c2410c';
export const GROSS = '#64748b';
export const PV = '#d4a017';

export function ms(ts: string): number {
  return new Date(ts).getTime();
}

/** Shades the billing-peak window of every day in view. The window is captured in this closure rather than passed
 *  as plugin options (Chart.js wraps option arrays in resolver proxies; iterating one hung a page before). */
export function windowPlugin(startH: number, endH: number, from: number, to: number) {
  return {
    id: 'billingWindow',
    beforeDatasetsDraw(chart: any) {
      if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return;
      }
      const { ctx, chartArea, scales } = chart;
      const day = 24 * 3600 * 1000;
      const first = Math.floor((from + PLANT_OFFSET_MS) / day) * day - PLANT_OFFSET_MS;
      ctx.save();
      ctx.fillStyle = 'rgba(194, 65, 12, 0.07)';
      for (let d = first; d < to; d += day) {
        const x0 = scales.x.getPixelForValue(Math.max(d + startH * 3600e3, from));
        const x1 = scales.x.getPixelForValue(Math.min(d + endH * 3600e3, to));
        if (x1 > x0) {
          ctx.fillRect(x0, chartArea.top, x1 - x0, chartArea.bottom - chartArea.top);
        }
      }
      ctx.restore();
    }
  };
}

export interface NfFanInput {
  history: { x: number; net: number | null; gross: number | null; gen: number | null }[];
  model: NfRegressorKey;
  forecast: { x: number; p10: number | null; p50: number | null; p90: number | null }[];
  overlays: { model: NfRegressorKey; points: { x: number; y: number | null }[] }[];
  actualAfter?: { x: number; y: number | null }[];
  peaks: { x: number; y: number; label: string }[];
  originMs: number;
  window: number[];
  threshold: number;
  showGross: boolean;
}

/** Net-load history (with gross load and BTM PV when asked), the chosen model's P10-P90 fan and P50, the other
 *  models' P50, the actual load after the origin (backtest), the threshold, the forecast daily peaks and the
 *  billing window. One y-axis (kW). */
export function netloadFan(f: NfFanInput): AnyConfig {
  const c = NF_COLORS[f.model];
  const ds: any[] = [];
  if (f.showGross) {
    ds.push(
      { label: 'Gross load', data: f.history.map((p) => ({ x: p.x, y: p.gross })), borderColor: GROSS, borderWidth: 1.2, borderDash: [3, 3], pointRadius: 0, order: 6 },
      { label: 'Behind-the-meter PV', data: f.history.map((p) => ({ x: p.x, y: p.gen })), borderColor: PV, backgroundColor: hexA(PV, 0.15), borderWidth: 1, fill: 'origin', pointRadius: 0, order: 7 }
    );
  }
  ds.push({ label: 'Net load', data: f.history.map((p) => ({ x: p.x, y: p.net })), borderColor: ACTUAL, borderWidth: 1.6, pointRadius: 0, order: 2 });
  if (f.actualAfter?.length) {
    ds.push({ label: 'Actual (after origin)', data: f.actualAfter, borderColor: ACTUAL, borderWidth: 1.6, pointRadius: 0, order: 2 });
  }
  ds.push(
    { label: `${NF_LABELS[f.model]} P90`, data: f.forecast.map((p) => ({ x: p.x, y: p.p90 })), borderColor: 'transparent', pointRadius: 0, fill: false, order: 5 },
    {
      label: `${NF_LABELS[f.model]} P10–P90`,
      data: f.forecast.map((p) => ({ x: p.x, y: p.p10 })),
      borderColor: 'transparent',
      backgroundColor: hexA(c, 0.2),
      pointRadius: 0,
      fill: '-1',
      order: 5
    },
    { label: `${NF_LABELS[f.model]} P50`, data: f.forecast.map((p) => ({ x: p.x, y: p.p50 })), borderColor: c, borderWidth: 2.2, pointRadius: 0, order: 1 }
  );
  for (const o of f.overlays) {
    ds.push({ label: `${NF_LABELS[o.model]} P50`, data: o.points, borderColor: NF_COLORS[o.model], borderWidth: 1.4, borderDash: NF_DASH[o.model], pointRadius: 0, order: 3 });
  }
  const xs = [...f.history.map((p) => p.x), ...f.forecast.map((p) => p.x)];
  const from = Math.min(...xs);
  const to = Math.max(...xs);
  ds.push({ label: `Threshold ${fmt(f.threshold, 0)} kW`, data: [{ x: from, y: f.threshold }, { x: to, y: f.threshold }], borderColor: THRESHOLD, borderWidth: 1.2, borderDash: [6, 4], pointRadius: 0, order: 4 });
  if (f.peaks.length) {
    ds.push({
      label: 'Forecast daily peak',
      data: f.peaks.map((p) => ({ x: p.x, y: p.y, label: p.label })),
      type: 'scatter',
      borderColor: '#ffffff',
      backgroundColor: c,
      borderWidth: 2,
      pointRadius: 6,
      pointHoverRadius: 8,
      pointStyle: 'triangle',
      order: 0
    });
  }
  return {
    type: 'line',
    data: { datasets: ds },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: { ...legend(), labels: { ...legend().labels, filter: (item: any) => !item.text.endsWith(' P90') } },
        tooltip: {
          ...tooltip,
          filter: (item: TooltipItem<'line'>) => !(item.dataset.label ?? '').endsWith(' P90') && !(item.dataset.label ?? '').startsWith('Threshold'),
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => {
              const label = ctx.dataset.label ?? '';
              if (label.endsWith('P10–P90')) {
                const hi = (ctx.chart.data.datasets[ctx.datasetIndex - 1].data[ctx.dataIndex] as any)?.y;
                return `${label}: ${fmt(ctx.parsed.y, 0)} – ${fmt(hi, 0)} kW`;
              }
              if (label === 'Forecast daily peak') {
                return `${(ctx.raw as any)?.label ?? 'Peak'}: ${fmt(ctx.parsed.y, 0)} kW`;
              }
              return `${label}: ${fmt(ctx.parsed.y, 0)} kW`;
            }
          }
        },
        originLine: { x: f.originMs }
      } as any,
      scales: { x: timeAxis(from, to), y: axis('kW') }
    },
    plugins: [windowPlugin(f.window[0], f.window[1], from, to), originLinePlugin]
  } as AnyConfig;
}

/** One weather input as the models saw it: solid where it came from a forecast run, dashed grey where the run
 *  didn't reach (recent measured days used instead). */
export function inputChart(points: { x: number; y: number | null; fc: boolean }[], label: string, unit: string, color: string,
                           from: number, to: number, window: number[]): AnyConfig {
  const fcPts = points.map((p) => ({ x: p.x, y: p.fc ? p.y : null }));
  const fbPts = points.map((p, i) => ({ x: p.x, y: !p.fc || (points[i + 1] && !points[i + 1].fc) ? p.y : null }));
  return {
    type: 'line',
    data: {
      datasets: [
        { label: `${label} · forecast run`, data: fcPts, borderColor: color, borderWidth: 2, pointRadius: 0, spanGaps: false },
        { label: `${label} · recent days (no forecast)`, data: fbPts, borderColor: INK_MUTED, borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, spanGaps: false }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: legend(),
        tooltip: {
          ...tooltip,
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${fmt(ctx.parsed.y, 1)} ${unit}`
          }
        }
      },
      scales: { x: timeAxis(from, to), y: axis(unit) }
    },
    plugins: [windowPlugin(window[0], window[1], from, to)]
  } as AnyConfig;
}

export function pct(v: number | null | undefined, d = 0): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(d)} %` : '—';
}

export function hhmm(ts: string | null | undefined): string {
  return ts ? plantLabel(ms(ts), false) : '—';
}
