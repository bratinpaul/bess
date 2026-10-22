import { ModuleSummaryByModule } from '../../../core/models/module-telemetry.model';

export type MetricKey = Exclude<keyof ModuleSummaryByModule, 'module_id' | 'serial_number' | 'label'>;

/**
 * How a column is shaded in the comparison table:
 * - worse-high: higher values are worse (imbalance, temperature, balancing) → warm shading
 * - spread: no good/bad direction (voltages) → neutral shading showing where a module sits in the spread
 * - none: not shaded (sample counts)
 */
export type Tone = 'worse-high' | 'spread' | 'none';

/** How the Pack row combines the module values. */
export type PackAgg = 'avg' | 'min' | 'max' | 'sum';

export interface ComparisonMetric {
  key: MetricKey;
  label: string;
  unit: string;
  decimals: number;
  tone: Tone;
  pack: PackAgg;
  /** Shown in the compare-chart metric picker. */
  chartable: boolean;
}

/** The ByModule sheet's columns, in its order. */
export const COMPARISON_METRICS: ComparisonMetric[] = [
  { key: 'avg_cell_v', label: 'Avg cell V', unit: 'V', decimals: 4, tone: 'spread', pack: 'avg', chartable: true },
  { key: 'min_cell_v', label: 'Min cell V', unit: 'V', decimals: 4, tone: 'spread', pack: 'min', chartable: true },
  { key: 'max_cell_v', label: 'Max cell V', unit: 'V', decimals: 4, tone: 'spread', pack: 'max', chartable: true },
  { key: 'mean_imbalance_mv', label: 'Mean imb', unit: 'mV', decimals: 2, tone: 'worse-high', pack: 'avg', chartable: true },
  { key: 'max_imbalance_mv', label: 'Max imb', unit: 'mV', decimals: 1, tone: 'worse-high', pack: 'max', chartable: true },
  { key: 'max_temp_c', label: 'Max temp', unit: '°C', decimals: 2, tone: 'worse-high', pack: 'max', chartable: true },
  { key: 'balancing_hours', label: 'Balancing', unit: 'h', decimals: 2, tone: 'worse-high', pack: 'sum', chartable: true },
  { key: 'samples', label: 'Samples', unit: '', decimals: 0, tone: 'none', pack: 'sum', chartable: false }
];

export interface ColumnStats {
  min: number;
  max: number;
  /** Mean of the module values, used for the chart's pack-average line. */
  mean: number;
  pack: number;
}

function values(rows: ModuleSummaryByModule[], key: MetricKey): number[] {
  return rows.map((r) => r[key]).filter((v): v is number => v !== null && v !== undefined);
}

export function columnStats(rows: ModuleSummaryByModule[]): Record<string, ColumnStats | null> {
  const stats: Record<string, ColumnStats | null> = {};
  for (const m of COMPARISON_METRICS) {
    const v = values(rows, m.key);
    if (!v.length) {
      stats[m.key] = null;
      continue;
    }
    const sum = v.reduce((a, b) => a + b, 0);
    const mean = sum / v.length;
    const pack = { avg: mean, min: Math.min(...v), max: Math.max(...v), sum }[m.pack];
    stats[m.key] = { min: Math.min(...v), max: Math.max(...v), mean, pack };
  }
  return stats;
}

/** Background for a table cell: stronger the further the value sits toward the column's high end. */
export function cellShade(value: number | null, metric: ComparisonMetric, stats: ColumnStats | null): string | null {
  if (value === null || !stats || metric.tone === 'none' || stats.max === stats.min) {
    return null;
  }
  const t = (value - stats.min) / (stats.max - stats.min);
  if (metric.tone === 'worse-high') {
    return `rgba(232, 131, 12, ${(0.06 + 0.5 * t).toFixed(3)})`;
  }
  return `rgba(47, 111, 237, ${(0.04 + 0.26 * t).toFixed(3)})`;
}
