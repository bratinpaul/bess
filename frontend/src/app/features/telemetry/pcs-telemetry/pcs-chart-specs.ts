import { ChartSpec, TimelineSpec } from '../graphs/chart-spec';

const BLUE = '#2f6fed';
const GREEN = '#12a37f';
const ORANGE = '#e8830c';
const RED = '#d62828';
const PURPLE = '#7c5cdb';
const TEAL = '#0e9fb3';
const SLATE = '#5b6472';
const GREY = '#9aa1ab';

// AC phases share a family so imbalance reads as lines drifting apart
const PHASE_A = '#2f6fed';
const PHASE_B = '#7c5cdb';
const PHASE_C = '#0e9fb3';

/** IGBT warning threshold (°C). The PCS master data has no limit column yet. */
export const IGBT_WARNING_C = 85;

export const PCS_CHARTS: ChartSpec[] = [
  {
    id: 'voltage',
    title: 'Voltage',
    yLabel: 'AC V',
    y2Label: 'DC V',
    counters: [
      { key: 'ac_voltage_ab_v', label: 'ac_voltage_ab_v', color: PHASE_A },
      { key: 'ac_voltage_bc_v', label: 'ac_voltage_bc_v', color: PHASE_B },
      { key: 'ac_voltage_ca_v', label: 'ac_voltage_ca_v', color: PHASE_C },
      { key: 'dc_voltage_v', label: 'dc_voltage_v', color: ORANGE, axis: 'y2' }
    ]
  },
  {
    id: 'current',
    title: 'Current',
    yLabel: 'AC A',
    y2Label: 'DC A',
    counters: [
      { key: 'ac_current_a_a', label: 'ac_current_a_a', color: PHASE_A },
      { key: 'ac_current_b_a', label: 'ac_current_b_a', color: PHASE_B },
      { key: 'ac_current_c_a', label: 'ac_current_c_a', color: PHASE_C },
      { key: 'dc_current_a', label: 'dc_current_a', color: ORANGE, axis: 'y2' }
    ],
    // signed DC current: the zero line separates charge from discharge
    refLines: [{ label: 'DC 0 A', value: 0, color: GREY, axis: 'y2' }]
  },
  {
    id: 'frequency',
    title: 'Frequency',
    yLabel: 'Hz',
    counters: [{ key: 'ac_frequency_hz', label: 'ac_frequency_hz', color: BLUE }],
    refLines: [{ label: 'Nominal 50 Hz', value: 50, color: SLATE }],
    refBand: { label: '±0.5 Hz tolerance', from: 49.5, to: 50.5, color: GREEN },
    // 0.05 Hz ticks, axis fitted to the readings; used if there are no readings
    y: { suggestedMin: 49.4, suggestedMax: 50.6, stepSize: 0.05, fitToData: true }
  },
  {
    id: 'power-factor',
    title: 'Power Factor',
    yLabel: '|PF|',
    counters: [{ key: 'power_factor_abs', label: '|power_factor|', color: PURPLE }],
    refLines: [{ label: 'Min PF limit', ref: 'minPowerFactor', color: RED }],
    y: { suggestedMin: 0.85, max: 1 }
  },
  {
    id: 'power-availability',
    title: 'Power & Availability',
    yLabel: 'kW',
    counters: [
      // charge (import) is positive and discharge (export) negative, so the envelope straddles zero
      { key: 'avail_charge_kw', label: 'avail_charge_kw', color: GREEN, role: 'area' },
      { key: 'avail_discharge_kw', label: 'avail_discharge_kw', color: ORANGE, role: 'area', negate: true },
      { key: 'ac_active_power_kw', label: 'ac_active_power_kw', color: BLUE },
      { key: 'dc_power_kw', label: 'dc_power_kw', color: PURPLE }
    ]
  },
  {
    id: 'percentage',
    title: 'THD & Efficiency',
    yLabel: 'THD %',
    y2Label: 'Efficiency %',
    counters: [
      { key: 'thd_voltage_pct', label: 'thd_voltage_pct', color: PURPLE },
      { key: 'thd_current_pct', label: 'thd_current_pct', color: TEAL },
      { key: 'efficiency_pct', label: 'efficiency_pct', color: GREEN, axis: 'y2' }
    ],
    y: { min: 0, suggestedMax: 10 },
    y2: { suggestedMin: 90, max: 100 }
  },
  {
    id: 'temperature',
    title: 'Temperature',
    yLabel: '°C',
    // warm → cool ramp, hottest component first
    counters: [
      { key: 'igbt_temp_c', label: 'igbt_temp_c', color: RED },
      { key: 'heatsink_temp_c', label: 'heatsink_temp_c', color: ORANGE },
      { key: 'inlet_coolant_temp_c', label: 'inlet_coolant_temp_c', color: TEAL },
      { key: 'ambient_temp_c', label: 'ambient_temp_c', color: BLUE }
    ],
    refLines: [{ label: `IGBT limit ${IGBT_WARNING_C} °C`, value: IGBT_WARNING_C, color: RED }]
  },
  {
    id: 'energy',
    title: 'Energy',
    yLabel: 'Cumulative kWh',
    y2Label: 'kWh per interval',
    counters: [
      { key: 'ac_energy_import_kwh', label: 'ac_energy_import_kwh', color: GREEN },
      { key: 'ac_energy_export_kwh', label: 'ac_energy_export_kwh', color: ORANGE },
      { key: 'import_kwh_step', label: 'import_kwh_step', color: GREEN, role: 'bar', axis: 'y2' },
      { key: 'export_kwh_step', label: 'export_kwh_step', color: ORANGE, role: 'bar', axis: 'y2' }
    ]
  },
  {
    id: 'pqs',
    title: 'P / Q / S Power',
    yLabel: 'kW · kvar · kVA',
    counters: [
      { key: 'ac_active_power_kw', label: 'ac_active_power_kw', color: BLUE },
      { key: 'ac_reactive_power_kvar', label: 'ac_reactive_power_kvar', color: ORANGE },
      { key: 'ac_apparent_power_kva', label: 'ac_apparent_power_kva', color: PURPLE }
    ],
    refLines: [{ label: 'Rated kVA', ref: 'ratedApparentKva', color: RED }]
  }
];

export const PCS_TIMELINES: TimelineSpec[] = [
  {
    id: 'breaker_state',
    title: 'Breaker State',
    laneLabel: 'Breaker',
    colors: { CLOSED: GREEN, OPEN: GREY, TRIPPED: RED }
  },
  {
    id: 'mode_code',
    title: 'Operating Mode',
    laneLabel: 'Mode',
    colors: { GRID_FOLLOWING: GREEN, GRID_FORMING: TEAL, STANDBY: '#8fb3ef', IDLE: GREY, FAULT: RED }
  },
  {
    id: 'grid_service',
    title: 'Grid Service',
    laneLabel: 'Service',
    colors: {
      NONE: '#d7dadf',
      VOLT_VAR: PURPLE,
      FREQ_WATT: ORANGE,
      VOLT_WATT: '#c2549d',
      CONST_PF: BLUE,
      CONST_Q: TEAL,
      PEAK_SHAVE: '#c9a227',
      BLACK_START: '#26282b'
    }
  }
];
