import { TooltipItem } from 'chart.js';

import { RulMethod } from '../../../core/models/rul.model';
import { AnyConfig, axis, legend, tooltip } from '../price-forecast-shared/pf-charts';

/* Methods: physics = blue, hybrid = orange (the two lead methods), GBM = violet, Cox = green, RSF = amber; each with
   its own dash so they stay apart without colour. */
export const R_COLORS: Record<RulMethod, string> = {
  physics: '#2a78d6',
  gbm: '#7c5cd6',
  hybrid: '#eb6834',
  cox: '#1baf7a',
  rsf: '#c47a00'
};
export const R_DASH: Record<RulMethod, number[]> = { physics: [], gbm: [6, 3], hybrid: [], cox: [2, 3], rsf: [8, 3, 2, 3] };
export const R_LABELS: Record<RulMethod, string> = {
  physics: 'Physics fade curve',
  gbm: 'LightGBM quantile',
  hybrid: 'Hybrid (physics + LightGBM)',
  cox: 'Cox PH (survival)',
  rsf: 'Random Survival Forest'
};
export const R_ORDER: RulMethod[] = ['physics', 'hybrid', 'gbm', 'cox', 'rsf'];
export const ACTUAL = '#1e232a';
export const EOL_INK = '#b2471b';

export function rgba(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** A date as a fractional year (2026.5 = early July 2026). */
export function yearOf(iso: string): number {
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00Z' : iso);
  const start = Date.UTC(d.getUTCFullYear(), 0, 1);
  const end = Date.UTC(d.getUTCFullYear() + 1, 0, 1);
  return d.getUTCFullYear() + (d.getTime() - start) / (end - start);
}

export function yearLabel(y: number): string {
  const yr = Math.floor(y);
  const m = Math.min(11, Math.floor((y - yr) * 12));
  return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m]} ${yr}`;
}

/** Linear axis in fractional years with ticks on whole years (half years for short spans) - built in
 *  afterBuildTicks, never with stepSize (that can hang Chart.js on long ranges). */
export function yearAxis(from: number, to: number) {
  const step = to - from <= 3 ? 0.5 : to - from <= 12 ? 1 : 2;
  return axis(undefined, {
    type: 'linear',
    min: from,
    max: to,
    afterBuildTicks: (scale: any) => {
      const ticks = [];
      for (let t = Math.ceil(from / step) * step; t <= to + 1e-9 && ticks.length < 40; t += step) {
        ticks.push({ value: t });
      }
      scale.ticks = ticks;
    },
    ticks: { maxRotation: 0, autoSkip: false, callback: (v: number | string) => (Number(v) % 1 === 0 ? String(v) : yearLabel(Number(v))) }
  });
}

/** Dashed horizontal threshold line with a label (values captured in the closure, not plugin options). */
export function thresholdPlugin(value: number | null, label: string) {
  return {
    id: 'rulThreshold',
    afterDatasetsDraw(chart: any) {
      if (value === null || !Number.isFinite(value)) {
        return;
      }
      const { ctx, chartArea, scales } = chart;
      const y = scales.y.getPixelForValue(value);
      if (y < chartArea.top || y > chartArea.bottom) {
        return;
      }
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = EOL_INK;
      ctx.fillStyle = EOL_INK;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(chartArea.left, y);
      ctx.lineTo(chartArea.right, y);
      ctx.stroke();
      ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      ctx.fillText(label, chartArea.left + 6, y - 4);
      ctx.restore();
    }
  };
}

/** Vertical "now" marker at a fractional year. */
export function nowPlugin(x: number | null, label = 'now') {
  return {
    id: 'rulNow',
    afterDatasetsDraw(chart: any) {
      if (x === null) {
        return;
      }
      const { ctx, chartArea, scales } = chart;
      const px = scales.x.getPixelForValue(x);
      if (px < chartArea.left || px > chartArea.right) {
        return;
      }
      ctx.save();
      ctx.strokeStyle = '#475569';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(px, chartArea.top);
      ctx.lineTo(px, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#475569';
      ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      ctx.fillText(label, px + 5, chartArea.top + 12);
      ctx.restore();
    }
  };
}

export interface XY {
  x: number;
  y: number | null;
}

export interface HealthChartInput {
  unit: string;
  digits: number;
  history: XY[];
  rpt: XY[];
  p50: XY[];
  band: { x: number; lo: number | null; hi: number | null }[];
  eol: number | null;
  eolLabel: string;
  now: number;
  bandColor: string;
}

/** SOH or resistance over time: measured history, RPT checkpoints, the projection (P50 + P10-P90) and the EOL line. */
export function healthChart(f: HealthChartInput): AnyConfig {
  const ds: any[] = [
    { label: 'Measured (monthly snapshot)', data: f.history, borderColor: ACTUAL, borderWidth: 1.8, pointRadius: 0, order: 2 },
    {
      label: 'RPT checkpoint',
      data: f.rpt,
      type: 'scatter',
      showLine: false,
      borderColor: ACTUAL,
      backgroundColor: '#ffffff',
      borderWidth: 1.6,
      pointRadius: 4,
      pointStyle: 'rectRot',
      order: 1
    },
    { label: 'Projection P90', data: f.band.map((p) => ({ x: p.x, y: p.hi })), borderColor: 'transparent', pointRadius: 0, fill: false, order: 5 },
    {
      label: 'Projection P10–P90',
      data: f.band.map((p) => ({ x: p.x, y: p.lo })),
      borderColor: 'transparent',
      backgroundColor: rgba(f.bandColor, 0.18),
      pointRadius: 0,
      fill: '-1',
      order: 5
    },
    { label: 'Projection P50', data: f.p50, borderColor: f.bandColor, borderWidth: 2.2, pointRadius: 0, order: 1 }
  ];
  const xs = [...f.history, ...f.p50].map((p) => p.x);
  const ys = [...f.history, ...f.p50, ...f.rpt].map((p) => p.y).filter((v): v is number => v !== null);
  if (f.eol !== null) {
    ys.push(f.eol);
  }
  const pad = (Math.max(...ys) - Math.min(...ys)) * 0.06 || 1;
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
            title: (items: TooltipItem<'line'>[]) => (items[0] ? yearLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => {
              const label = ctx.dataset.label ?? '';
              if (label.endsWith('P10–P90')) {
                const top = (ctx.chart.data.datasets[ctx.datasetIndex - 1].data[ctx.dataIndex] as any)?.y;
                return `${label}: ${(ctx.parsed.y as number)?.toFixed(f.digits)} – ${Number(top).toFixed(f.digits)} ${f.unit}`;
              }
              return `${label}: ${(ctx.parsed.y as number)?.toFixed(f.digits)} ${f.unit}`;
            }
          }
        }
      } as any,
      scales: {
        x: yearAxis(Math.floor(Math.min(...xs) * 2) / 2, Math.ceil(Math.max(...xs) * 2) / 2),
        y: axis(f.unit, { min: Math.min(...ys) - pad, max: Math.max(...ys) + pad })
      }
    },
    plugins: [thresholdPlugin(f.eol, f.eolLabel), nowPlugin(f.now)]
  } as AnyConfig;
}

/** Survival curves S(t): probability the unit is still within life t days ahead (x in years ahead). */
export function survivalChart(curves: { method: RulMethod; points: { days: number; s: number }[] }[]): AnyConfig {
  const xmax = Math.max(1, ...curves.flatMap((c) => c.points.map((p) => p.days / 365.25)));
  return {
    type: 'line',
    data: {
      datasets: curves.map((c) => ({
        label: R_LABELS[c.method],
        data: c.points.map((p) => ({ x: p.days / 365.25, y: p.s })),
        borderColor: R_COLORS[c.method],
        borderDash: R_DASH[c.method],
        borderWidth: 2,
        pointRadius: 0,
        stepped: c.method === 'rsf' ? 'after' : false
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: legend(),
        tooltip: {
          ...tooltip,
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items[0] ? `${(items[0].parsed.x as number).toFixed(2)} years ahead` : ''),
            label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${Math.round((ctx.parsed.y as number) * 100)} % still within life`
          }
        }
      },
      scales: {
        x: axis('Years ahead', { type: 'linear', min: 0, max: Math.ceil(xmax * 2) / 2 }),
        y: axis('P(still within life)', { min: 0, max: 1, ticks: { callback: (v: number | string) => `${Math.round(Number(v) * 100)} %` } })
      }
    },
    plugins: [thresholdPlugin(0.5, 'median (P50)')]
  } as AnyConfig;
}

export interface BacktestInput {
  actual: XY[];
  actualLabel: string;
  oracle?: XY[];
  lines: { method: RulMethod; points: XY[] }[];
  band?: { method: RulMethod; points: { x: number; lo: number | null; hi: number | null }[] };
  unit: string;
}

/** RUL predicted at each snapshot (leave-one-unit-out) vs the true RUL / the known-alive bound. */
export function backtestChart(f: BacktestInput): AnyConfig {
  const ds: any[] = [
    { label: f.actualLabel, data: f.actual, borderColor: ACTUAL, borderWidth: 2.2, pointRadius: 0, order: 2 }
  ];
  if (f.oracle?.length) {
    ds.push({ label: 'Synthetic label (oracle, not trained on)', data: f.oracle, borderColor: '#8a8f98', borderDash: [2, 3], borderWidth: 1.4, pointRadius: 0, order: 3 });
  }
  if (f.band) {
    ds.push(
      { label: `${R_LABELS[f.band.method]} P90`, data: f.band.points.map((p) => ({ x: p.x, y: p.hi })), borderColor: 'transparent', pointRadius: 0, fill: false, order: 5 },
      {
        label: `${R_LABELS[f.band.method]} P10–P90`,
        data: f.band.points.map((p) => ({ x: p.x, y: p.lo })),
        borderColor: 'transparent',
        backgroundColor: rgba(R_COLORS[f.band.method], 0.16),
        pointRadius: 0,
        fill: '-1',
        order: 5
      }
    );
  }
  for (const l of f.lines) {
    ds.push({ label: `${R_LABELS[l.method]} P50`, data: l.points, borderColor: R_COLORS[l.method], borderDash: R_DASH[l.method], borderWidth: 1.8, pointRadius: 0, order: 1 });
  }
  const xs = [...f.actual, ...f.lines.flatMap((l) => l.points)].map((p) => p.x);
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
            title: (items: TooltipItem<'line'>[]) => (items[0] ? `Snapshot ${yearLabel(items[0].parsed.x as number)}` : ''),
            label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${Math.round(ctx.parsed.y as number)} ${f.unit}`
          }
        }
      } as any,
      scales: {
        x: yearAxis(Math.floor(Math.min(...xs) * 2) / 2, Math.ceil(Math.max(...xs) * 2) / 2),
        y: axis(`RUL (${f.unit})`, { beginAtZero: true })
      }
    }
  } as AnyConfig;
}

/** Fleet view: P10-P90 range bars (floating) with the P50 per unit, in years. */
export function fleetChart(units: { code: string; p10: number; p50: number; p90: number; beyond: boolean }[], color: string): AnyConfig {
  const y = (d: number) => d / 365.25;
  return {
    type: 'bar',
    data: {
      labels: units.map((u) => u.code),
      datasets: [
        {
          type: 'bar',
          label: 'P10–P90',
          data: units.map((u) => [y(u.p10), y(u.p90)]),
          backgroundColor: rgba(color, 0.28),
          borderColor: rgba(color, 0.6),
          borderWidth: 1,
          borderRadius: 3,
          barThickness: 14,
          order: 2
        },
        {
          type: 'scatter',
          label: 'P50',
          data: units.map((u, i) => ({ x: y(u.p50), y: i })),
          backgroundColor: color,
          borderColor: '#ffffff',
          borderWidth: 1.5,
          pointRadius: 6,
          order: 1
        }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: legend(),
        tooltip: {
          ...tooltip,
          callbacks: {
            label: (ctx: any) => {
              const u = units[ctx.dataIndex];
              return ctx.dataset.label === 'P50'
                ? `P50 ${Math.round(u.p50)} days (${y(u.p50).toFixed(1)} y)${u.beyond ? ' · beyond follow-up' : ''}`
                : `P10–P90 ${Math.round(u.p10)} – ${Math.round(u.p90)} days`;
            }
          }
        }
      },
      scales: {
        x: axis('Remaining useful life (years)', { beginAtZero: true }),
        y: axis(undefined, { type: 'category', grid: { display: false } })
      }
    }
  } as AnyConfig;
}
