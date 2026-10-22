import { Observable } from 'rxjs';

import { StateSegment } from '../../../core/models/system-telemetry.model';

/**
 * How a counter is drawn:
 * - line: a plain line
 * - bandMin / bandMax: edges of a shaded min–max band (the max edge fills down to the min edge)
 * - bar: bars, one per bucket
 * - area: a light shaded area down to zero (e.g. an availability envelope)
 */
export type CounterRole = 'line' | 'bandMin' | 'bandMax' | 'bar' | 'area';

export interface CounterSpec {
  key: string;
  label: string;
  color: string;
  role?: CounterRole;
  /** 'y2' puts the counter on the right-hand axis. */
  axis?: 'y' | 'y2';
  /** Plot the negated value (e.g. discharge headroom drawn below zero). */
  negate?: boolean;
  /** Draw a line dashed, e.g. a setpoint or target next to the measured value. */
  dashed?: boolean;
  /** Hold each value until the next sample (a step line), for setpoints and targets. */
  stepped?: boolean;
  /** Bars only: colour for negative values, e.g. money spent vs earned. */
  negativeColor?: string;
}

/** A horizontal dashed reference line. Give a fixed `value`, or `ref` to read one from the series. */
export interface RefLine {
  label: string;
  color: string;
  value?: number;
  ref?: string;
  /** Multiplier applied to a `ref` value, e.g. -1 for the lagging power-factor limit. */
  scale?: number;
  axis?: 'y' | 'y2';
}

export interface RefBand {
  label: string;
  from: number;
  to: number;
  color: string;
}

export interface AxisRange {
  min?: number;
  max?: number;
  suggestedMin?: number;
  suggestedMax?: number;
  /** Fixed tick spacing, e.g. 0.05 for frequency. */
  stepSize?: number;
  /**
   * Fit the axis to the plotted counters only (ignoring reference lines and bands),
   * rounded out to whole `stepSize` steps with one step of padding.
   */
  fitToData?: boolean;
}

export interface ChartSpec {
  id: string;
  title: string;
  yLabel: string;
  y2Label?: string;
  counters: CounterSpec[];
  refLines?: RefLine[];
  refBand?: RefBand;
  y?: AxisRange;
  y2?: AxisRange;
}

export interface TimelineSpec {
  id: string;
  title: string;
  laneLabel: string;
  colors: Record<string, string>;
}

export type SeriesPoint = { ts: string } & Record<string, number | string | null>;

export interface StateTimeline {
  /** All states the lookup table knows, in display order. */
  states: string[];
  segments: StateSegment[];
}

/** What a graphs page needs from its series endpoint. */
export interface GraphSeries {
  entityName: string | null;
  start: string | null;
  end: string | null;
  bucketSeconds: number;
  rawIntervalSeconds: number | null;
  points: SeriesPoint[];
  timelines: Record<string, StateTimeline>;
  /** Values that reference lines can point at (e.g. rated kVA). */
  refs: Record<string, number | null>;
}

export interface GraphEntity {
  id: string;
  name: string;
}

export type SeriesLoader = (entityId: string, start?: string, end?: string) => Observable<GraphSeries>;

export const UNKNOWN_STATE_COLOR = '#5b6472';
