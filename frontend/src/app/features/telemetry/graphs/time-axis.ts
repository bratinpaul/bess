import { Scale } from 'chart.js';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

// Fixed axis widths keep the plot areas of every stacked chart aligned on the time axis.
export const LEFT_AXIS_WIDTH = 64;
export const RIGHT_AXIS_WIDTH = 64;

// candidate tick spacings, smallest first
const TICK_STEPS = [
  5 * MINUTE_MS, 15 * MINUTE_MS, 30 * MINUTE_MS,
  HOUR_MS, 2 * HOUR_MS, 3 * HOUR_MS, 6 * HOUR_MS, 12 * HOUR_MS,
  DAY_MS, 2 * DAY_MS, 7 * DAY_MS, 14 * DAY_MS, 30 * DAY_MS
];
const MAX_TICKS = 9;

export function fixWidth(width: number) {
  return (scale: Scale) => {
    scale.width = width;
  };
}

/** Tick positions on round local-clock boundaries (midnight, whole hours, ...). */
export function niceTimeTicks(min: number, max: number): { ticks: number[]; step: number } {
  const span = Math.max(max - min, 1);
  const step = TICK_STEPS.find((s) => span / s <= MAX_TICKS) ?? TICK_STEPS[TICK_STEPS.length - 1];
  const start = new Date(min);
  // align to local midnight, then walk forward in whole steps
  start.setHours(0, 0, 0, 0);
  let t = start.getTime();
  while (t < min) {
    t += step;
  }
  const ticks: number[] = [];
  for (; t <= max; t += step) {
    ticks.push(t);
  }
  return { ticks, step };
}

export function formatTick(ms: number, step: number, spanMs: number): string {
  const d = new Date(ms);
  const day = d.toLocaleDateString([], { day: '2-digit', month: 'short' });
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  if (step >= DAY_MS) {
    return day;
  }
  if (spanMs <= DAY_MS) {
    return time;
  }
  return `${day} ${time}`;
}

export function formatFull(ms: number): string {
  return new Date(ms).toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

export function formatDuration(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export function timeAxis(xMin: number, xMax: number) {
  const { ticks, step } = niceTimeTicks(xMin, xMax);
  const span = xMax - xMin;
  return {
    type: 'linear' as const,
    min: xMin,
    max: xMax,
    // bar datasets would otherwise pad the axis and break alignment with the line charts
    offset: false,
    afterBuildTicks: (scale: Scale) => {
      scale.ticks = ticks.map((value) => ({ value }));
    },
    ticks: {
      autoSkip: false,
      maxRotation: 0,
      callback: (value: string | number) => formatTick(Number(value), step, span)
    },
    grid: { color: 'rgba(0,0,0,0.05)' }
  };
}

/**
 * Right-hand axis reserved on every chart (hidden when unused) so the plot areas
 * end at the same x position whether or not a chart has a secondary axis.
 */
export function rightAxis(visible: boolean, title: string | undefined) {
  return {
    type: 'linear' as const,
    position: 'right' as const,
    display: true,
    title: { display: visible && !!title, text: title ?? '' },
    ticks: { display: visible },
    border: { display: visible },
    grid: { drawOnChartArea: false, display: visible },
    afterFit: fixWidth(RIGHT_AXIS_WIDTH)
  };
}
