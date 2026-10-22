import { TooltipItem } from 'chart.js';

import { SocMethod } from '../../../core/models/soc-forecast.model';
import { AnyConfig, axis, legend, originLinePlugin, plantLabel, timeAxis, tooltip } from '../price-forecast-shared/pf-charts';

/* Methods: hold = neutral reference; physics = blue, hybrid = orange (palette slots 1-2, validated); the plan source
   is the dash (schedule solid, typical day dashed) so identity never rests on colour alone. */
export const METHOD_COLORS: Record<SocMethod, string> = {
  hold: '#8a8f98',
  physics_typical: '#2a78d6',
  physics_scheduled: '#2a78d6',
  hybrid_typical: '#eb6834',
  hybrid_scheduled: '#eb6834'
};
export const METHOD_DASH: Record<SocMethod, number[]> = {
  hold: [3, 3],
  physics_typical: [7, 4],
  physics_scheduled: [],
  hybrid_typical: [7, 4],
  hybrid_scheduled: []
};
export const METHOD_LABELS: Record<SocMethod, string> = {
  hold: 'Hold SOC (naïve)',
  physics_typical: 'Physics · typical day',
  physics_scheduled: 'Physics · schedule',
  hybrid_typical: 'Hybrid · typical day',
  hybrid_scheduled: 'Hybrid · schedule'
};
export const METHOD_ORDER: SocMethod[] = ['hold', 'physics_typical', 'physics_scheduled', 'hybrid_typical', 'hybrid_scheduled'];

export const SHORT_COLORS = { hold: '#8a8f98', physics: '#2a78d6', hybrid: '#eb6834' };
export const ACTUAL = '#1e232a';

export function rgba(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** Dashed horizontal lines at the SOC limits (captured in the closure, not plugin options). */
export function limitLinesPlugin(min: number | null, max: number | null) {
  return {
    id: 'socLimits',
    afterDatasetsDraw(chart: any) {
      const { ctx, chartArea, scales } = chart;
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = '#b2471b';
      ctx.fillStyle = '#b2471b';
      ctx.lineWidth = 1;
      ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      for (const [v, label] of [
        [min, 'SOC min'],
        [max, 'SOC max']
      ] as [number | null, string][]) {
        if (v === null || !Number.isFinite(v)) {
          continue;
        }
        const y = scales.y.getPixelForValue(v);
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y);
        ctx.lineTo(chartArea.right, y);
        ctx.stroke();
        ctx.fillText(`${label} ${v.toFixed(1)} %`, chartArea.left + 6, label === 'SOC max' ? y - 4 : y + 12);
      }
      ctx.restore();
    }
  };
}

export interface SocLine {
  label: string;
  color: string;
  dash?: number[];
  width?: number;
  points: { x: number; y: number | null }[];
}

export interface SocChartInput {
  history: { x: number; y: number | null }[];
  actualAfter?: { x: number; y: number | null }[];
  band?: { label: string; color: string; points: { x: number; lo: number | null; hi: number | null }[] };
  lines: SocLine[];
  originMs: number;
  socMin: number | null;
  socMax: number | null;
}

/** SOC (%) history, the P10-P90 band of the main method, P50 lines, the actual after the origin (backtest),
 *  the SOC limits and the origin. One y-axis (SOC %). */
export function socChart(f: SocChartInput): AnyConfig {
  const ds: any[] = [{ label: 'SOC · actual', data: f.history, borderColor: ACTUAL, borderWidth: 2, pointRadius: 0, order: 2 }];
  if (f.actualAfter?.length) {
    ds.push({ label: 'SOC · actual (after origin)', data: f.actualAfter, borderColor: ACTUAL, borderWidth: 2, pointRadius: 0, order: 2 });
  }
  if (f.band) {
    ds.push(
      { label: `${f.band.label} P90`, data: f.band.points.map((p) => ({ x: p.x, y: p.hi })), borderColor: 'transparent', pointRadius: 0, fill: false, order: 5 },
      {
        label: `${f.band.label} P10–P90`,
        data: f.band.points.map((p) => ({ x: p.x, y: p.lo })),
        borderColor: 'transparent',
        backgroundColor: rgba(f.band.color, 0.18),
        pointRadius: 0,
        fill: '-1',
        order: 5
      }
    );
  }
  for (const l of f.lines) {
    ds.push({ label: l.label, data: l.points, borderColor: l.color, borderDash: l.dash ?? [], borderWidth: l.width ?? 2, pointRadius: 0, order: 1 });
  }
  const xs = [...f.history.map((p) => p.x), ...f.lines.flatMap((l) => l.points.map((p) => p.x))];
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
          filter: (item: TooltipItem<'line'>) => !(item.dataset.label ?? '').endsWith(' P90'),
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => {
              const label = ctx.dataset.label ?? '';
              if (label.endsWith('P10–P90')) {
                const hi = (ctx.chart.data.datasets[ctx.datasetIndex - 1].data[ctx.dataIndex] as any)?.y;
                return `${label}: ${(ctx.parsed.y as number)?.toFixed(1)} – ${Number(hi).toFixed(1)} %`;
              }
              return `${label}: ${(ctx.parsed.y as number)?.toFixed(1)} %`;
            }
          }
        },
        originLine: { x: f.originMs, label: 'now →' }
      } as any,
      scales: { x: timeAxis(from, to), y: axis('SOC (%)', { min: 0, max: 100 }) }
    },
    plugins: [limitLinesPlugin(f.socMin, f.socMax), originLinePlugin]
  } as AnyConfig;
}

/** Setpoint (kW, + charge / - discharge): history and the plan ahead, as stepped lines. */
export function planChart(history: { x: number; y: number | null }[], plan: { x: number; y: number | null }[], originMs: number,
  planLabel: string, from: number, to: number): AnyConfig {
  return {
    type: 'line',
    data: {
      datasets: [
        { label: 'Setpoint · actual', data: history, borderColor: ACTUAL, borderWidth: 1.5, pointRadius: 0, stepped: true },
        {
          label: planLabel,
          data: plan,
          borderColor: '#6d5bd0',
          backgroundColor: rgba('#6d5bd0', 0.12),
          borderWidth: 2,
          pointRadius: 0,
          stepped: true,
          fill: 'origin'
        }
      ]
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
            title: (items: TooltipItem<'line'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(0)} kW`
          }
        },
        originLine: { x: originMs, label: '' }
      } as any,
      scales: { x: timeAxis(from, to), y: axis('kW (+ charge / − discharge)') }
    },
    plugins: [originLinePlugin]
  } as AnyConfig;
}
