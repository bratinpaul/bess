import { ChartSpec } from '../graphs/chart-spec';

const PURPLE = '#7c5cdb';
const ORANGE = '#e8830c';
const RED = '#e5484d';

export const MODULE_CHARTS: ChartSpec[] = [
  {
    id: 'cell-voltage',
    title: 'Cell Voltage',
    yLabel: 'V',
    counters: [
      { key: 'cell_v_min_v', label: 'cell_v_min_v', color: PURPLE, role: 'bandMin' },
      { key: 'cell_v_max_v', label: 'cell_v_max_v', color: PURPLE, role: 'bandMax' },
      { key: 'cell_v_avg_v', label: 'cell_v_avg_v', color: '#4b2fa8' }
    ]
  },
  {
    id: 'imbalance',
    title: 'Cell Imbalance',
    yLabel: 'mV',
    counters: [{ key: 'imbalance_mv', label: 'imbalance_mv', color: ORANGE }],
    y: { min: 0 }
  },
  {
    id: 'cell-temperature',
    title: 'Cell Temperature',
    yLabel: '°C',
    y2Label: 'Spread °C',
    counters: [
      { key: 'cell_temp_min_c', label: 'cell_temp_min_c', color: RED, role: 'bandMin' },
      { key: 'cell_temp_max_c', label: 'cell_temp_max_c', color: RED, role: 'bandMax' },
      { key: 'temp_spread_c', label: 'temp_spread_c', color: ORANGE, axis: 'y2' }
    ],
    y2: { min: 0 }
  }
];
