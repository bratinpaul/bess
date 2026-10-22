import { ChartSpec, TimelineSpec } from '../graphs/chart-spec';

const BLUE = '#2f6fed';
const GREEN = '#12a37f';
const ORANGE = '#e8830c';
const RED = '#d62828';
const PURPLE = '#7c5cdb';
const TEAL = '#0e9fb3';
const SLATE = '#5b6472';
const GREY = '#9aa1ab';

export const HVAC_CHARTS: ChartSpec[] = [
  {
    id: 'coolant-loop',
    title: 'Coolant Loop',
    yLabel: '°C',
    y2Label: 'ΔT °C',
    counters: [
      { key: 'coolant_supply_temp_c', label: 'coolant_supply_temp_c', color: BLUE },
      { key: 'coolant_return_temp_c', label: 'coolant_return_temp_c', color: RED },
      { key: 'coolant_delta_t_c', label: 'coolant_delta_t_c', color: ORANGE, axis: 'y2' }
    ],
    refLines: [{ label: 'Setpoint', ref: 'coolantSetpoint', color: SLATE }],
    y2: { min: 0 }
  },
  {
    id: 'enclosure',
    title: 'Enclosure Climate',
    yLabel: '°C',
    y2Label: 'Humidity %',
    counters: [
      { key: 'enclosure_temp_c', label: 'enclosure_temp_c', color: RED },
      { key: 'ambient_temp_c', label: 'ambient_temp_c', color: ORANGE },
      { key: 'enclosure_humidity_pct', label: 'enclosure_humidity_pct', color: TEAL, axis: 'y2' }
    ],
    y2: { min: 0, max: 100 }
  },
  {
    id: 'thermal-balance',
    title: 'Thermal Power Balance',
    yLabel: 'kW',
    counters: [
      { key: 'battery_heat_load_kw', label: 'battery_heat_load_kw', color: RED },
      { key: 'cooling_capacity_kw', label: 'cooling_capacity_kw', color: BLUE },
      { key: 'heat_rejected_kw', label: 'heat_rejected_kw', color: ORANGE },
      { key: 'hvac_power_kw', label: 'hvac_power_kw', color: PURPLE }
    ],
    y: { min: 0 }
  },
  {
    id: 'cop',
    title: 'Efficiency (COP)',
    yLabel: 'COP',
    // only reported during COOLING, so the line has gaps in IDLE / FREE_COOLING
    counters: [{ key: 'cop', label: 'cop', color: GREEN }]
  },
  {
    id: 'compressor-fans',
    title: 'Compressor & Fans',
    yLabel: '%',
    y2Label: 'Units',
    counters: [
      { key: 'compressor_speed_pct', label: 'compressor_speed_pct', color: BLUE },
      { key: 'condenser_fan_pct', label: 'condenser_fan_pct', color: TEAL },
      { key: 'units_running', label: 'units_running', color: SLATE, axis: 'y2', stepped: true, dashed: true }
    ],
    y: { min: 0, max: 100 },
    y2: { min: 0, suggestedMax: 2, stepSize: 1 }
  },
  {
    id: 'refrigerant',
    title: 'Refrigerant Pressures',
    yLabel: 'Suction bar',
    y2Label: 'Discharge bar',
    // only reported while the compressor runs
    counters: [
      { key: 'refrig_suction_bar', label: 'refrig_suction_bar', color: BLUE },
      { key: 'refrig_discharge_bar', label: 'refrig_discharge_bar', color: RED, axis: 'y2' }
    ]
  },
  {
    id: 'coolant-flow',
    title: 'Coolant Flow',
    yLabel: 'L/min',
    counters: [{ key: 'coolant_flow_lpm', label: 'coolant_flow_lpm', color: TEAL }],
    y: { min: 0 }
  },
  {
    id: 'filter',
    title: 'Filter ΔP',
    yLabel: 'Pa',
    counters: [{ key: 'filter_dp_pa', label: 'filter_dp_pa', color: PURPLE }]
  },
  {
    id: 'energy',
    title: 'HVAC Energy',
    yLabel: 'Cumulative kWh',
    y2Label: 'kWh per interval',
    counters: [
      { key: 'cum_energy_kwh', label: 'cum_energy_kwh', color: PURPLE },
      { key: 'energy_kwh_step', label: 'energy_kwh_step', color: PURPLE, role: 'bar', axis: 'y2' }
    ]
  },
  {
    id: 'runtime',
    title: 'Compressor Runtime',
    yLabel: 'h',
    counters: [{ key: 'compressor_runtime_h', label: 'compressor_runtime_h', color: BLUE }]
  }
];

export const HVAC_TIMELINES: TimelineSpec[] = [
  {
    id: 'cooling_mode',
    title: 'Cooling Mode',
    laneLabel: 'Mode',
    colors: { COOLING: BLUE, FREE_COOLING: GREEN, IDLE: GREY }
  }
];
