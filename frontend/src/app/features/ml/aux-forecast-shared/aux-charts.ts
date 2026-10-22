import { TooltipItem } from 'chart.js';

import { AuxMethod } from '../../../core/models/aux-forecast.model';
import { AnyConfig, axis, legend, originLinePlugin, plantLabel, timeAxis, tooltip } from '../price-forecast-shared/pf-charts';

/* Methods: persistence / seasonal = neutral references, grey-box = blue, hybrid = orange (palette slots 1-2); each has
   its own dash too, so they stay apart without colour. */
export const A_COLORS: Record<AuxMethod, string> = { persistence: '#8a8f98', seasonal: '#8a8f98', greybox: '#2a78d6', hybrid: '#eb6834' };
export const A_DASH: Record<AuxMethod, number[]> = { persistence: [4, 4], seasonal: [2, 3], greybox: [7, 4], hybrid: [] };
export const A_LABELS: Record<AuxMethod, string> = {
  persistence: 'Persistence',
  seasonal: 'Same time yesterday',
  greybox: 'Grey-box',
  hybrid: 'Hybrid (grey-box + LightGBM)'
};
export const A_ORDER: AuxMethod[] = ['persistence', 'seasonal', 'greybox', 'hybrid'];
export const ACTUAL = '#1e232a';
export const HVAC = '#1baf7a';

export function rgba(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

export interface XY {
  x: number;
  y: number | null;
}

export interface SeriesLine {
  label: string;
  color: string;
  dash?: number[];
  width?: number;
  points: XY[];
}

export interface BandChartInput {
  unit: string;
  digits?: number;
  /** Measured values: solid dark line. */
  actual?: XY[];
  band?: { label: string; color: string; points: { x: number; lo: number | null; hi: number | null }[] };
  lines: SeriesLine[];
  originMs?: number;
  beginAtZero?: boolean;
}

/** One quantity over time: the measured line, the P10-P90 band, P50 / reference lines and the "now" marker. */
export function bandChart(f: BandChartInput): AnyConfig {
  const d = f.digits ?? 1;
  const ds: any[] = [];
  if (f.actual?.length) {
    ds.push({ label: 'Actual', data: f.actual, borderColor: ACTUAL, borderWidth: 1.6, pointRadius: 0, order: 2 });
  }
  if (f.band) {
    ds.push(
      { label: `${f.band.label} P90`, data: f.band.points.map((p) => ({ x: p.x, y: p.hi })), borderColor: 'transparent', pointRadius: 0, fill: false, order: 5 },
      {
        label: `${f.band.label} P10–P90`,
        data: f.band.points.map((p) => ({ x: p.x, y: p.lo })),
        borderColor: 'transparent',
        backgroundColor: rgba(f.band.color, 0.2),
        pointRadius: 0,
        fill: '-1',
        order: 5
      }
    );
  }
  for (const l of f.lines) {
    ds.push({ label: l.label, data: l.points, borderColor: l.color, backgroundColor: l.color, borderDash: l.dash ?? [], borderWidth: l.width ?? 2, pointRadius: 0, order: 1 });
  }
  const all = [...(f.actual ?? []), ...f.lines.flatMap((l) => l.points)];
  const xs = all.map((p) => p.x);
  const plugins: any[] = f.originMs !== undefined ? [originLinePlugin] : [];
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
          filter: (item: TooltipItem<'line'>) => !(item.dataset.label ?? '').endsWith(' P90'),
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => {
              const label = ctx.dataset.label ?? '';
              if (label.endsWith('P10–P90')) {
                const top = (ctx.chart.data.datasets[ctx.datasetIndex - 1].data[ctx.dataIndex] as any)?.y;
                return `${label}: ${(ctx.parsed.y as number)?.toFixed(d)} – ${Number(top).toFixed(d)} ${f.unit}`;
              }
              return `${label}: ${(ctx.parsed.y as number)?.toFixed(d)} ${f.unit}`;
            }
          }
        },
        originLine: f.originMs !== undefined ? { x: f.originMs, label: 'now →' } : undefined
      } as any,
      scales: { x: timeAxis(Math.min(...xs), Math.max(...xs)), y: axis(f.unit, { beginAtZero: f.beginAtZero ?? false }) }
    },
    plugins
  } as AnyConfig;
}

export interface EnergyBar {
  label: string;
  values: (number | null)[];
  color: string;
}

/** Daily aux energy (kWh): grouped bars per day (actual + methods). */
export function energyBars(days: string[], bars: EnergyBar[], unit = 'kWh'): AnyConfig {
  return {
    type: 'bar',
    data: {
      labels: days,
      datasets: bars.map((b) => ({ label: b.label, data: b.values, backgroundColor: b.color, borderRadius: 3, maxBarThickness: 16 }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: legend(),
        tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(0)} ${unit}` } }
      },
      scales: { x: axis(undefined, { grid: { display: false } }), y: axis(unit, { beginAtZero: false }) }
    }
  } as AnyConfig;
}
