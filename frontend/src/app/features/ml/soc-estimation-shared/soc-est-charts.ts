import { TooltipItem } from 'chart.js';

import { SocEstMethod, SocEstPoint, SocEstScope } from '../../../core/models/soc-estimation.model';
import { ACTUAL, AnyConfig, axis, fmt, hexA, legend, ms, originLinePlugin, plantLabel, timeAxis, tooltip } from '../price-forecast-shared/pf-charts';

/* Estimators carry the hue (validated: blue / orange / aqua / violet, light surface); the two raw baselines are
   neutral greys told apart by dash, so identity never rests on colour alone. Truth is ink. */
export const EST_COLORS: Record<SocEstMethod, string> = {
  coulomb: '#8a8f98',
  bms: '#5b6270',
  ocv_lookup: '#6d5bd0',
  ekf: '#2a78d6',
  gbm: '#1f9e89',
  hybrid: '#eb6834'
};
export const EST_DASH: Record<SocEstMethod, number[]> = {
  coulomb: [6, 4],
  bms: [2, 3],
  ocv_lookup: [1, 3],
  ekf: [],
  gbm: [8, 3],
  hybrid: []
};
export const EST_LABELS: Record<SocEstMethod, string> = {
  coulomb: 'Coulomb counting (raw)',
  ocv_lookup: 'OCV lookup (naïve)',
  bms: 'BMS reported',
  ekf: 'EKF',
  gbm: 'Coulomb + LightGBM',
  hybrid: 'EKF + LightGBM (hybrid)'
};
export const EST_ORDER: SocEstMethod[] = ['coulomb', 'ocv_lookup', 'bms', 'ekf', 'gbm', 'hybrid'];
export const BANDED: SocEstMethod[] = ['ekf', 'gbm', 'hybrid'];
export const SCOPE_LABELS: Record<SocEstScope, string> = {
  anchors: 'Anchors · all',
  anchors_rest: 'Anchors · REST_OCV',
  anchors_full: 'Anchors · FULL_CHARGE',
  dense: 'Dense truth · all rows',
  dense_flat: 'Dense truth · flat 25–80 %',
  dense_active: 'Dense truth · under current'
};
export const SCOPE_ORDER: SocEstScope[] = ['dense_flat', 'anchors', 'anchors_rest', 'anchors_full', 'dense', 'dense_active'];

export interface TimelineInput {
  points: SocEstPoint[];
  methods: SocEstMethod[];
  band: SocEstMethod | null;
  showTruth: boolean;
  markerFrom?: number | null; // e.g. the start of the test period
  markerLabel?: string;
}

function series(points: SocEstPoint[], key: keyof SocEstPoint) {
  return points.map((p) => ({ x: ms(p.ts), y: (p[key] as number | null | undefined) ?? null }));
}

/** SOC over time: the chosen estimators, the P10-P90 band of one, the dense truth, and the anchors as markers
 *  (triangle = FULL_CHARGE, circle = REST_OCV). One y-axis (SOC %). */
export function timelineChart(t: TimelineInput): AnyConfig {
  const ds: any[] = [];
  const pts = t.points;
  if (t.band) {
    const c = EST_COLORS[t.band];
    ds.push(
      { label: `${EST_LABELS[t.band]} P90`, data: series(pts, `${t.band}_p90` as keyof SocEstPoint), borderColor: 'transparent', pointRadius: 0, fill: false, order: 9 },
      {
        label: `${EST_LABELS[t.band]} P10–P90`,
        data: series(pts, `${t.band}_p10` as keyof SocEstPoint),
        borderColor: 'transparent',
        backgroundColor: hexA(c, 0.18),
        pointRadius: 0,
        fill: '-1',
        order: 9
      }
    );
  }
  if (t.showTruth && pts.some((p) => p.truth !== null && p.truth !== undefined)) {
    ds.push({ label: 'True SOC (sample)', data: series(pts, 'truth'), borderColor: ACTUAL, borderWidth: 1.5, pointRadius: 0, order: 3 });
  }
  for (const m of t.methods) {
    const key = (m === 'ocv_lookup' && !pts.some((p) => p.ocv_lookup !== undefined) ? 'ocv_soc' : m) as keyof SocEstPoint;
    ds.push({
      label: EST_LABELS[m],
      data: series(pts, key),
      borderColor: EST_COLORS[m],
      backgroundColor: EST_COLORS[m],
      borderDash: EST_DASH[m],
      borderWidth: m === 'hybrid' || m === 'ekf' ? 2 : 1.5,
      pointRadius: 0,
      spanGaps: m !== 'ocv_lookup',
      order: m === 'hybrid' ? 1 : 2
    });
  }
  const anchors = pts.filter((p) => p.anchor !== null && p.anchor !== undefined);
  if (anchors.length) {
    ds.push({
      type: 'scatter',
      label: 'Anchors (soc_reference)',
      data: anchors.map((p) => ({ x: ms(p.ts), y: p.anchor, method: p.anchor_method })),
      backgroundColor: ACTUAL,
      borderColor: '#fcfcfb',
      borderWidth: 2,
      pointRadius: 6,
      pointHoverRadius: 8,
      pointStyle: anchors.map((p) => (p.anchor_method === 'FULL_CHARGE' ? 'triangle' : 'circle')),
      order: 0
    });
  }
  const xs = pts.map((p) => ms(p.ts));
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
                return `${label}: ${fmt(ctx.parsed.y, 2)} – ${fmt(hi, 2)} %`;
              }
              if (label.startsWith('Anchors')) {
                return `Anchor ${(ctx.raw as any)?.method ?? ''}: ${fmt(ctx.parsed.y, 2)} %`;
              }
              return `${label}: ${fmt(ctx.parsed.y, 2)} %`;
            }
          }
        },
        originLine: t.markerFrom ? { x: t.markerFrom, label: t.markerLabel ?? '' } : {}
      } as any,
      scales: { x: timeAxis(from, to), y: axis('SOC (%)', { min: 0, max: 100 }) }
    },
    plugins: [originLinePlugin]
  } as unknown as AnyConfig;
}

/** One measure over time (drift correction, error vs truth, EKF bias ...) - its own chart, its own axis. */
export function measureChart(
  lines: { label: string; color: string; dash?: number[]; points: { x: number; y: number | null }[] }[],
  unit: string,
  title: string,
  zeroLine = true
): AnyConfig {
  const xs = lines.flatMap((l) => l.points.map((p) => p.x));
  const from = Math.min(...xs);
  const to = Math.max(...xs);
  return {
    type: 'line',
    data: {
      datasets: lines.map((l) => ({
        label: l.label,
        data: l.points,
        borderColor: l.color,
        backgroundColor: l.color,
        borderDash: l.dash ?? [],
        borderWidth: 2,
        pointRadius: 0,
        spanGaps: true
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: legend(lines.length > 1),
        tooltip: {
          ...tooltip,
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
            label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${fmt(ctx.parsed.y, 2)} ${unit}`
          }
        }
      },
      scales: {
        x: timeAxis(from, to),
        y: axis(title, zeroLine ? { grid: { color: (c: any) => (c.tick?.value === 0 ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.06)') } } : {})
      }
    }
  } as AnyConfig;
}
