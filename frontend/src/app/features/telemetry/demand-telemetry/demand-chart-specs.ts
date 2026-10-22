import { ChartSpec, TimelineSpec } from '../graphs/chart-spec';

const BLUE = '#2f6fed';
const GREEN = '#12a37f';
const ORANGE = '#e8830c';
const RED = '#d62828';
const PURPLE = '#7c5cdb';
const TEAL = '#0e9fb3';
const SLATE = '#5b6472';
const GREY = '#9aa1ab';

export const DEMAND_CHARTS: ChartSpec[] = [
  {
    id: 'demand-profile',
    title: 'Demand Profile',
    yLabel: 'kW',
    // net = gross load - behind-the-meter generation; the peak lines come from the selected window
    counters: [
      { key: 'gross_load_kw', label: 'gross_load_kw', color: RED },
      { key: 'net_load_kw', label: 'net_load_kw', color: BLUE },
      { key: 'behind_meter_gen_kw', label: 'behind_meter_gen_kw', color: GREEN, role: 'area' }
    ],
    refLines: [
      { label: 'Peak net', ref: 'peakNet', color: SLATE },
      { label: 'Billing-window peak', ref: 'billingPeak', color: RED }
    ],
    y: { min: 0 }
  },
  {
    id: 'net-peak-band',
    title: 'Net Load Range per Interval',
    yLabel: 'kW',
    // min-max band of the 5-min net load inside each bucket, average line, demand-charge ratchet
    counters: [
      { key: 'net_load_min_kw', label: 'net_load_min_kw', color: BLUE, role: 'bandMin' },
      { key: 'net_load_max_kw', label: 'net_load_max_kw', color: BLUE, role: 'bandMax' },
      { key: 'net_load_kw', label: 'net_load_kw', color: BLUE }
    ],
    refLines: [
      { label: 'Billing-window peak', ref: 'billingPeak', color: RED },
      { label: 'Ratchet', ref: 'ratchet', color: ORANGE }
    ],
    y: { min: 0 }
  },
  {
    id: 'generation',
    title: 'Behind-the-meter Generation',
    yLabel: 'kW',
    y2Label: 'Share of gross load %',
    counters: [
      { key: 'behind_meter_gen_kw', label: 'behind_meter_gen_kw', color: GREEN, role: 'area' },
      { key: 'gen_share_pct', label: 'gen_share_pct', color: TEAL, axis: 'y2', dashed: true }
    ],
    y: { min: 0 },
    y2: { min: 0, max: 100 }
  },
  {
    id: 'reactive',
    title: 'Reactive Power & Power Factor',
    yLabel: 'kvar / kVA',
    y2Label: 'Power factor',
    counters: [
      { key: 'load_reactive_kvar', label: 'load_reactive_kvar', color: PURPLE },
      { key: 'apparent_kva', label: 'apparent_kva', color: SLATE, dashed: true },
      { key: 'power_factor', label: 'power_factor', color: ORANGE, axis: 'y2' }
    ],
    refLines: [{ label: 'PF 0.9', value: 0.9, color: RED, axis: 'y2' }],
    y: { min: 0 },
    y2: { suggestedMin: 0.8, max: 1 }
  },
  {
    id: 'energy',
    title: 'Energy per Interval',
    yLabel: 'kWh',
    counters: [
      { key: 'gross_energy_kwh', label: 'gross_energy_kwh', color: RED, role: 'bar' },
      { key: 'net_energy_kwh', label: 'net_energy_kwh', color: BLUE, role: 'bar' },
      { key: 'gen_energy_kwh', label: 'gen_energy_kwh', color: GREEN, role: 'bar' }
    ],
    y: { min: 0 }
  }
];

export const DEMAND_TIMELINES: TimelineSpec[] = [
  {
    id: 'billing_window',
    title: 'Demand-charge Window',
    laneLabel: 'Tariff',
    colors: { PEAK_WINDOW: RED, OFF_PEAK: GREY, NO_TARIFF: GREY }
  }
];
