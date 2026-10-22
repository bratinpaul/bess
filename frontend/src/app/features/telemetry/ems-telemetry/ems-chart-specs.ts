import { ChartSpec, TimelineSpec } from '../graphs/chart-spec';

const BLUE = '#2f6fed';
const GREEN = '#12a37f';
const ORANGE = '#e8830c';
const RED = '#d62828';
const PURPLE = '#7c5cdb';
const TEAL = '#0e9fb3';
const SLATE = '#5b6472';
const GREY = '#9aa1ab';

/** Nominal point-of-interconnection voltage (kV). */
export const POI_NOMINAL_KV = 33;

export const EMS_CHARTS: ChartSpec[] = [
  {
    id: 'power-tracking',
    title: 'Power Tracking',
    yLabel: 'kW',
    y2Label: 'Error kW',
    counters: [
      { key: 'p_setpoint_kw', label: 'p_setpoint_kw', color: SLATE, dashed: true, stepped: true },
      { key: 'poi_active_power_kw', label: 'poi_active_power_kw', color: BLUE },
      { key: 'tracking_error_kw', label: 'tracking_error_kw', color: ORANGE, axis: 'y2' }
    ],
    // small errors stay readable next to ±1 MW power swings
    y2: { suggestedMin: -10, suggestedMax: 10 }
  },
  {
    id: 'soc',
    title: 'Plant SOC',
    yLabel: '%',
    counters: [
      { key: 'plant_soc_pct', label: 'plant_soc_pct', color: GREEN },
      { key: 'target_soc_pct', label: 'target_soc_pct', color: SLATE, dashed: true, stepped: true }
    ],
    y: { min: 0, max: 100 }
  },
  {
    id: 'available-power',
    title: 'Available Power',
    yLabel: 'kW',
    counters: [
      // import (charge) is positive and export (discharge) negative, so the envelope straddles zero
      { key: 'avail_charge_kw', label: 'avail_charge_kw', color: GREEN, role: 'area' },
      { key: 'avail_discharge_kw', label: 'avail_discharge_kw', color: ORANGE, role: 'area', negate: true },
      { key: 'poi_active_power_kw', label: 'poi_active_power_kw', color: BLUE }
    ]
  },
  {
    id: 'available-energy',
    title: 'Available Energy',
    yLabel: 'kWh',
    counters: [
      { key: 'avail_charge_energy_kwh', label: 'avail_charge_energy_kwh', color: GREEN },
      { key: 'avail_discharge_energy_kwh', label: 'avail_discharge_energy_kwh', color: ORANGE }
    ],
    y: { min: 0 }
  },
  {
    id: 'market',
    title: 'Market Price & Revenue',
    yLabel: '$/MWh',
    y2Label: '$ per interval',
    counters: [
      { key: 'market_price_mwh', label: 'market_price_mwh', color: PURPLE },
      // earned while exporting (green), spent while charging (red)
      { key: 'revenue_usd_step', label: 'revenue_usd_step', color: GREEN, role: 'bar', axis: 'y2', negativeColor: RED }
    ],
    refLines: [{ label: '$0', value: 0, color: GREY, axis: 'y2' }]
  },
  {
    id: 'frequency-agc',
    title: 'Grid Frequency & AGC',
    yLabel: 'Hz',
    y2Label: 'AGC signal',
    counters: [
      { key: 'grid_frequency_hz', label: 'grid_frequency_hz', color: BLUE },
      { key: 'agc_signal', label: 'agc_signal', color: ORANGE, axis: 'y2' }
    ],
    refLines: [{ label: 'Nominal 50 Hz', value: 50, color: SLATE }],
    refBand: { label: '±0.5 Hz tolerance', from: 49.5, to: 50.5, color: GREEN },
    // 0.05 Hz ticks with the axis fitted to the readings, as on the PCS frequency chart
    y: { suggestedMin: 49.4, suggestedMax: 50.6, stepSize: 0.05, fitToData: true },
    y2: { min: -1, max: 1 }
  },
  {
    id: 'voltage-reactive',
    title: 'POI Voltage & Reactive Power',
    yLabel: 'kV',
    y2Label: 'kvar',
    counters: [
      { key: 'poi_voltage_kv', label: 'poi_voltage_kv', color: TEAL },
      { key: 'poi_reactive_power_kvar', label: 'poi_reactive_power_kvar', color: ORANGE, axis: 'y2' }
    ],
    refLines: [{ label: `Nominal ${POI_NOMINAL_KV} kV`, value: POI_NOMINAL_KV, color: SLATE }]
  },
  {
    id: 'energy',
    title: 'Energy (POI)',
    yLabel: 'Cumulative kWh',
    y2Label: 'kWh per interval',
    counters: [
      { key: 'cum_import_kwh', label: 'cum_import_kwh', color: GREEN },
      { key: 'cum_export_kwh', label: 'cum_export_kwh', color: ORANGE },
      { key: 'import_kwh_step', label: 'import_kwh_step', color: GREEN, role: 'bar', axis: 'y2' },
      { key: 'export_kwh_step', label: 'export_kwh_step', color: ORANGE, role: 'bar', axis: 'y2' }
    ]
  },
  {
    id: 'aux',
    title: 'Aux Load',
    yLabel: 'kW',
    y2Label: '%',
    counters: [
      { key: 'aux_load_kw', label: 'aux_load_kw', color: PURPLE },
      { key: 'aux_load_pct', label: 'aux_load_pct', color: TEAL, axis: 'y2' }
    ],
    y: { min: 0 },
    y2: { min: 0 }
  }
];

export const EMS_TIMELINES: TimelineSpec[] = [
  {
    id: 'dispatch_mode',
    title: 'Dispatch Mode',
    laneLabel: 'Dispatch',
    colors: {
      SCHEDULED_CHARGE: GREEN,
      ENERGY_ARBITRAGE: ORANGE,
      FREQUENCY_REGULATION: PURPLE,
      STANDBY: '#8fb3ef',
      IDLE: GREY
    }
  },
  {
    id: 'grid_service',
    title: 'Grid Service',
    laneLabel: 'Service',
    colors: { NONE: '#d7dadf', ARBITRAGE: ORANGE, FREQ_REG: PURPLE }
  }
];
