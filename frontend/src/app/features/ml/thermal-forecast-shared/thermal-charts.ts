import { TooltipItem } from 'chart.js';

import { ThermalMethod } from '../../../core/models/thermal-forecast.model';
import { AnyConfig, axis, legend, originLinePlugin, plantLabel, timeAxis, tooltip } from '../price-forecast-shared/pf-charts';

/* Methods: persistence = neutral reference, seasonal = neutral dotted, RC = blue, hybrid = orange (palette slots 1-2);
   each has its own dash too. */
export const T_COLORS: Record<ThermalMethod, string> = { persistence: '#8a8f98', seasonal: '#8a8f98', rc: '#2a78d6', hybrid: '#eb6834' };
export const T_DASH: Record<ThermalMethod, number[]> = { persistence: [4, 4], seasonal: [2, 3], rc: [7, 4], hybrid: [] };
export const T_LABELS: Record<ThermalMethod, string> = {
  persistence: 'Persistence',
  seasonal: 'Seasonal naïve (24 h)',
  rc: 'RC grey-box',
  hybrid: 'Hybrid (RC + LightGBM)'
};
export const T_ORDER: ThermalMethod[] = ['persistence', 'seasonal', 'rc', 'hybrid'];
export const ACTUAL = '#1e232a';

export function rgba(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** Dashed horizontal lines at the evaluation threshold and the catalog alarm limit (closure, not plugin options). */
export function thresholdPlugin(threshold: number | null, alarm: number | null) {
  return {
    id: 'tempThresholds',
    afterDatasetsDraw(chart: any) {
      const { ctx, chartArea, scales } = chart;
      ctx.save();
      ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      for (const [v, label, color] of [
        [threshold, 'pre-alarm', '#c47a00'],
        [alarm, 'alarm', '#b2471b']
      ] as [number | null, string, string][]) {
        if (v === null || !Number.isFinite(v)) {
          continue;
        }
        const y = scales.y.getPixelForValue(v);
        if (y < chartArea.top || y > chartArea.bottom) {
          continue;
        }
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y);
        ctx.lineTo(chartArea.right, y);
        ctx.stroke();
        ctx.fillText(`${label} ${v.toFixed(0)} °C`, chartArea.left + 6, y - 4);
      }
      ctx.restore();
    }
  };
}

export interface TempLine {
  label: string;
  color: string;
  dash?: number[];
  width?: number;
  points: { x: number; y: number | null }[];
  pointRadius?: number;
}

export interface TempChartInput {
  history: { x: number; y: number | null }[];
  ambient?: { x: number; y: number | null }[];
  band?: { label: string; color: string; points: { x: number; lo: number | null; hi: number | null }[] };
  lines: TempLine[];
  originMs?: number;
  threshold: number | null;
  alarm: number | null;
  unitLabel?: string;
}

/** Temperature (°C): history, ambient, the P10-P90 band, P50 lines, thresholds. One y-axis. */
export function tempChart(f: TempChartInput): AnyConfig {
  const ds: any[] = [{ label: 'Actual', data: f.history, borderColor: ACTUAL, borderWidth: 1.8, pointRadius: 0, order: 2 }];
  if (f.ambient?.length) {
    ds.push({ label: 'Ambient', data: f.ambient, borderColor: 'rgba(100, 108, 120, 0.5)', borderWidth: 1, borderDash: [2, 3], pointRadius: 0, order: 4 });
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
    ds.push({
      label: l.label,
      data: l.points,
      borderColor: l.color,
      backgroundColor: l.color,
      borderDash: l.dash ?? [],
      borderWidth: l.width ?? 2,
      pointRadius: l.pointRadius ?? 0,
      order: 1
    });
  }
  const xs = [...f.history.map((p) => p.x), ...f.lines.flatMap((l) => l.points.map((p) => p.x))];
  const ys = [...f.history, ...f.lines.flatMap((l) => l.points)].map((p) => p.y).filter((v): v is number => v !== null);
  const marks = [f.threshold, f.alarm].filter((v): v is number => v !== null);
  const lo = Math.floor(Math.min(...ys) - 2);
  const hi = Math.ceil(Math.max(...ys, ...marks.filter((m) => m < Math.max(...ys) + 12)) + 2);
  const plugins: any[] = [thresholdPlugin(f.threshold, f.alarm)];
  if (f.originMs !== undefined) {
    plugins.push(originLinePlugin);
  }
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
                return `${label}: ${(ctx.parsed.y as number)?.toFixed(1)} – ${Number(top).toFixed(1)} °C`;
              }
              return `${label}: ${(ctx.parsed.y as number)?.toFixed(1)} °C`;
            }
          }
        },
        originLine: f.originMs !== undefined ? { x: f.originMs, label: 'now →' } : undefined
      } as any,
      scales: { x: timeAxis(Math.min(...xs), Math.max(...xs)), y: axis(f.unitLabel ?? '°C', { min: lo, max: hi }) }
    },
    plugins
  } as AnyConfig;
}
