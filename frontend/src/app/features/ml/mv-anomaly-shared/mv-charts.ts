import { ChartConfiguration, Plugin, TooltipItem } from 'chart.js';

type Tip = TooltipItem<any>;

import { MvAlarm, MvContributor, MvModelKey, MvTimelinePoint } from '../../../core/models/mv-anomaly.model';
import { formatFull, formatTick, niceTimeTicks } from '../../telemetry/graphs/time-axis';

/* One colour per detector, in the validated categorical order; the colour follows the model on every chart. */
export const MV_MODEL_COLORS: Record<MvModelKey, string> = {
  pca: '#2f6fed',
  iforest: '#e8830c',
  robust_cov: '#12a37f',
  autoencoder: '#7c5cdb',
  window_ae: '#0e9fb3'
};
export const FLAG = '#e5484d';
export const ALARM_FILL = 'rgba(232, 131, 12, 0.14)';
export const EVAL_LINE = '#6b6f76';
const INK = '#6b6f76';
const GRID = 'rgba(0, 0, 0, 0.06)';

export const MV_REASON_LABELS: Record<string, string> = {
  alarm_event: 'Alarm periods (± pad)',
  alarm_level: 'Alarm level > 0',
  pcs_fault: 'PCS in FAULT',
  sensor_rule: 'Frozen / missing sensor',
  commissioning: 'Commissioning period'
};

export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)} %`;
}

export function ms(ts: string): number {
  return new Date(ts).getTime();
}

export function ruleLabel(flag: string): string {
  const [kind, col] = flag.split(':');
  return `${kind === 'frozen' ? 'Frozen' : 'Missing'} ${col.replace(/_/g, ' ')}`;
}

/** Line data with a null point inserted where the data has a gap (so the line breaks instead of bridging it). */
function withGaps(pts: { x: number; y: number | null }[], gapMs: number): { x: number; y: number | null }[] {
  const out: { x: number; y: number | null }[] = [];
  for (let i = 0; i < pts.length; i++) {
    if (i > 0 && pts[i].x - pts[i - 1].x > gapMs) {
      out.push({ x: (pts[i].x + pts[i - 1].x) / 2, y: null });
    }
    out.push(pts[i]);
  }
  return out;
}

const GAP_MS = 3 * 3600_000;

function timeScale(from: number, to: number) {
  const span = to - from;
  return {
    type: 'linear' as const,
    min: from,
    max: to,
    grid: { color: GRID },
    afterBuildTicks: (scale: any) => {
      scale.ticks = niceTimeTicks(from, to).ticks.map((value) => ({ value }));
    },
    ticks: {
      color: INK,
      font: { size: 11 },
      maxRotation: 0,
      callback: (v: number | string) => formatTick(Number(v), niceTimeTicks(from, to).step, span)
    }
  };
}

/** Shaded alarm intervals + the evaluation-window boundary, drawn behind the series (data captured in the closure). */
function backdropPlugin(alarms: { s: number; e: number }[], evalFrom: number | null): Plugin {
  return {
    id: 'mvBackdrop',
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const x = scales['x'];
      ctx.save();
      ctx.fillStyle = ALARM_FILL;
      for (let i = 0; i < alarms.length; i++) {
        const a = alarms[i];
        const x0 = Math.max(x.getPixelForValue(a.s), chartArea.left);
        const x1 = Math.min(x.getPixelForValue(a.e), chartArea.right);
        if (x1 > x0) {
          ctx.fillRect(x0, chartArea.top, Math.max(1, x1 - x0), chartArea.bottom - chartArea.top);
        }
      }
      if (evalFrom !== null) {
        const px = x.getPixelForValue(evalFrom);
        if (px > chartArea.left && px < chartArea.right) {
          ctx.strokeStyle = EVAL_LINE;
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(px, chartArea.top);
          ctx.lineTo(px, chartArea.bottom);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = EVAL_LINE;
          ctx.font = '11px -apple-system, Segoe UI, Roboto, sans-serif';
          ctx.fillText('evaluation →', px + 4, chartArea.top + 12);
        }
      }
      ctx.restore();
    }
  };
}

/** Smoothed anomaly score of the primary model (and optionally the other models) vs the limit, alarms shaded. */
export function timelineChart(
  points: MvTimelinePoint[],
  alarms: MvAlarm[],
  primary: MvModelKey,
  limit: number,
  evalFrom: string | null,
  others: MvModelKey[] = [],
  labels: Record<string, string> = {}
): ChartConfiguration {
  const xs = points.map((p) => ms(p.ts));
  const from = Math.min(...xs);
  const to = Math.max(...xs) + 5 * 60_000;
  const cap = (v: number | null) => (v === null ? null : Math.min(v, limit * 8));
  const datasets: any[] = [
    {
      label: `${labels[primary] ?? primary} (smoothed)`,
      data: withGaps(points.map((p) => ({ x: ms(p.ts), y: cap(p.smooth) })), GAP_MS),
      borderColor: MV_MODEL_COLORS[primary],
      backgroundColor: MV_MODEL_COLORS[primary],
      borderWidth: 1.5,
      pointRadius: 0,
      order: 2
    },
    ...others.map((k) => ({
      label: labels[k] ?? k,
      data: withGaps(points.map((p) => ({ x: ms(p.ts), y: cap(p.models?.[k] ?? null) })), GAP_MS),
      borderColor: MV_MODEL_COLORS[k],
      backgroundColor: MV_MODEL_COLORS[k],
      borderWidth: 1,
      borderDash: [4, 3],
      pointRadius: 0,
      order: 3
    })),
    {
      label: 'Flagged',
      type: 'scatter',
      data: points.filter((p) => p.flag).map((p) => ({ x: ms(p.ts), y: cap(p.smooth ?? limit) })),
      backgroundColor: FLAG,
      borderColor: '#ffffff',
      borderWidth: 1,
      pointRadius: 3,
      order: 1
    },
    {
      label: 'Limit',
      data: [
        { x: from, y: limit },
        { x: to, y: limit }
      ],
      borderColor: '#1e232a',
      borderWidth: 1,
      borderDash: [6, 4],
      pointRadius: 0,
      order: 0
    }
  ];
  return {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      interaction: { mode: 'nearest', intersect: false, axis: 'x' },
      plugins: {
        legend: { position: 'bottom', labels: { color: '#475569', boxWidth: 14, boxHeight: 2, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: (items: Tip[]) => (items.length ? formatFull(items[0].parsed.x) : ''),
            label: (item: Tip) => ` ${item.dataset.label}: ${item.parsed.y === null ? '—' : item.parsed.y.toFixed(2)}`
          }
        }
      },
      scales: {
        x: timeScale(from, to),
        y: {
          min: 0,
          grid: { color: GRID },
          ticks: { color: INK, font: { size: 11 } },
          title: { display: true, text: 'score (limit = 1 before tuning)', color: INK, font: { size: 11 } }
        }
      }
    } as any,
    plugins: [backdropPlugin(alarms.map((a) => ({ s: ms(a.start), e: ms(a.end) })), evalFrom ? ms(evalFrom) : null)]
  };
}

/** Horizontal bars: share of each feature in the attribution of the flagged intervals. */
export function contributorChart(items: MvContributor[], color: string): ChartConfiguration {
  return {
    type: 'bar',
    data: {
      labels: items.map((c) => c.label),
      datasets: [{ label: 'Share', data: items.map((c) => +(c.share * 100).toFixed(1)), backgroundColor: color, borderRadius: 4, maxBarThickness: 16 }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (i: Tip) => ` ${i.parsed.x.toFixed(1)} % of the attribution` } },
        valueLabels: { format: (v: number) => `${v.toFixed(0)} %` }
      } as any,
      scales: {
        x: { min: 0, grid: { color: GRID }, ticks: { color: INK, callback: (v: number | string) => `${v} %` } },
        y: { grid: { display: false }, ticks: { color: '#26282b', font: { size: 12 } } }
      }
    }
  };
}

/** One signal over an episode window (its own chart and unit - no second y-axis), the episode shaded. */
export function signalChart(points: Record<string, any>[], key: string, label: string, color: string, episode: { s: number; e: number }): ChartConfiguration {
  const xs = points.map((p) => ms(p['ts']));
  const from = Math.min(...xs);
  const to = Math.max(...xs);
  return {
    type: 'line',
    data: {
      datasets: [
        {
          label,
          data: withGaps(points.map((p) => ({ x: ms(p['ts']), y: p[key] })), 30 * 60_000),
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          pointRadius: 0,
          spanGaps: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      interaction: { mode: 'nearest', intersect: false, axis: 'x' },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items: Tip[]) => (items.length ? formatFull(items[0].parsed.x) : ''),
            label: (item: Tip) => ` ${label}: ${item.parsed.y === null ? '—' : item.parsed.y.toFixed(3)}`
          }
        }
      },
      scales: { x: timeScale(from, to), y: { grid: { color: GRID }, ticks: { color: INK, font: { size: 11 } } } }
    } as any,
    plugins: [
      {
        id: 'mvEpisode',
        beforeDatasetsDraw(chart) {
          const { ctx, chartArea, scales } = chart;
          const x0 = Math.max(scales['x'].getPixelForValue(episode.s), chartArea.left);
          const x1 = Math.min(scales['x'].getPixelForValue(episode.e), chartArea.right);
          ctx.save();
          ctx.fillStyle = 'rgba(229, 72, 77, 0.10)';
          ctx.fillRect(x0, chartArea.top, Math.max(1, x1 - x0), chartArea.bottom - chartArea.top);
          ctx.restore();
        }
      } as Plugin
    ]
  };
}
