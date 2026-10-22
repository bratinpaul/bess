import { ChartSpec, TimelineSpec } from '../graphs/chart-spec';

const BLUE = '#2f6fed';
const GREEN = '#12a37f';
const ORANGE = '#e8830c';
const RED = '#e5484d';
const PURPLE = '#7c5cdb';
const TEAL = '#0e9fb3';
const SLATE = '#5b6472';

export const BMS_CHARTS: ChartSpec[] = [
  {
    id: 'soc-soh',
    title: 'SOC & SOH',
    yLabel: '%',
    counters: [
      { key: 'soc_bms_pct', label: 'SOC_BMS_%', color: BLUE },
      { key: 'soh_pct', label: 'SOH_%', color: GREEN }
    ]
  },
  {
    id: 'pack-voltage',
    title: 'Pack Voltage',
    yLabel: 'V',
    counters: [{ key: 'pack_voltage_v', label: 'Pack_Voltage_V', color: PURPLE }]
  },
  {
    id: 'cell-voltage',
    title: 'Cell Voltage',
    yLabel: 'V',
    y2Label: 'mV',
    counters: [
      { key: 'cell_v_min_v', label: 'Cell_V_Min_V', color: PURPLE, role: 'bandMin' },
      { key: 'cell_v_max_v', label: 'Cell_V_Max_V', color: PURPLE, role: 'bandMax' },
      { key: 'cell_v_avg_v', label: 'Cell_V_Avg_V', color: '#4b2fa8' },
      { key: 'cell_v_delta_mv', label: 'Cell_V_Delta_mV', color: ORANGE, axis: 'y2' }
    ]
  },
  {
    id: 'pack-current',
    title: 'Pack Current',
    yLabel: 'A',
    counters: [{ key: 'pack_current_a', label: 'Pack_Current_A', color: TEAL }]
  },
  {
    id: 'c-rate',
    title: 'C-Rate',
    yLabel: 'C',
    counters: [{ key: 'c_rate', label: 'C_Rate', color: BLUE }]
  },
  {
    id: 'cell-temp',
    title: 'Cell Temperature',
    yLabel: '°C',
    counters: [
      { key: 'cell_temp_min_c', label: 'Cell_Temp_Min_C', color: RED, role: 'bandMin' },
      { key: 'cell_temp_max_c', label: 'Cell_Temp_Max_C', color: RED, role: 'bandMax' },
      { key: 'cell_temp_avg_c', label: 'Cell_Temp_Avg_C', color: '#b3262b' }
    ]
  },
  {
    id: 'coolant-ambient',
    title: 'Coolant & Ambient',
    yLabel: '°C',
    counters: [
      { key: 'coolant_temp_c', label: 'Coolant_Temp_C', color: TEAL },
      { key: 'ambient_temp_c', label: 'Ambient_Temp_C', color: ORANGE }
    ]
  },
  {
    id: 'power',
    title: 'Power & Availability',
    yLabel: 'kW',
    counters: [
      { key: 'power_kw', label: 'Power_kW', color: BLUE },
      { key: 'avail_charge_kw', label: 'Avail_Charge_kW', color: GREEN },
      { key: 'avail_discharge_kw', label: 'Avail_Discharge_kW', color: ORANGE }
    ]
  },
  {
    id: 'insulation',
    title: 'Insulation Resistance',
    yLabel: 'kΩ',
    counters: [{ key: 'insulation_res_kohm', label: 'Insulation_Res_kOhm', color: SLATE }]
  },
  {
    id: 'energy',
    title: 'Energy Throughput',
    yLabel: 'Cumulative kWh',
    y2Label: 'kWh per interval',
    counters: [
      { key: 'cum_charge_kwh', label: 'Cum_Charge_kWh', color: GREEN },
      { key: 'cum_discharge_kwh', label: 'Cum_Discharge_kWh', color: ORANGE },
      { key: 'charge_kwh_step', label: 'Charge_kWh_step', color: GREEN, role: 'bar', axis: 'y2' },
      { key: 'discharge_kwh_step', label: 'Discharge_kWh_step', color: ORANGE, role: 'bar', axis: 'y2' }
    ]
  },
  {
    id: 'efc',
    title: 'Equiv. Full Cycles',
    yLabel: 'cycles',
    counters: [{ key: 'equiv_full_cycles', label: 'Equiv_Full_Cycles', color: PURPLE }]
  },
  {
    id: 'soc-estimates',
    title: 'SOC Estimates',
    yLabel: '%',
    counters: [
      { key: 'soc_bms_pct', label: 'SOC_BMS_%', color: BLUE },
      { key: 'soc_coulomb_pct', label: 'SOC_Coulomb_%', color: ORANGE },
      { key: 'soc_battery_telemetry_pct', label: 'SOC_Battery_Telemetry_%', color: GREEN }
    ]
  },
  {
    id: 'current-sensing',
    title: 'Current Sensing',
    yLabel: 'A',
    y2Label: 'Offset A',
    counters: [
      { key: 'pack_current_a', label: 'Pack_Current_A', color: TEAL },
      { key: 'measured_current_a', label: 'Measured_Current_A', color: PURPLE },
      { key: 'current_sensor_offset_a', label: 'Current_Sensor_Offset_A', color: RED, axis: 'y2' }
    ]
  },
  {
    id: 'capacity-efficiency',
    title: 'Usable Capacity & Coulombic Efficiency',
    yLabel: 'Ah',
    y2Label: 'Efficiency',
    counters: [
      { key: 'usable_capacity_ah', label: 'Usable_Capacity_Ah', color: GREEN },
      { key: 'coulombic_efficiency', label: 'Coulombic_Efficiency', color: ORANGE, axis: 'y2' }
    ]
  },
  {
    id: 'rest-ocv',
    title: 'Rest & Rested OCV',
    yLabel: 'V',
    y2Label: 'min',
    counters: [
      { key: 'ocv_rested_v', label: 'OCV_Rested_V', color: PURPLE },
      { key: 'rest_duration_min', label: 'Rest_Duration_min', color: SLATE, axis: 'y2' }
    ]
  }
];

export const BMS_TIMELINES: TimelineSpec[] = [
  {
    // id kept as 'contactor' so saved selections from earlier versions still apply
    id: 'contactor',
    title: 'Contactor Status',
    laneLabel: 'Contactor',
    colors: { Closed: GREEN, Open: '#9aa1ab' }
  },
  {
    id: 'rest',
    title: 'At Rest',
    laneLabel: 'Rest',
    colors: { 'At rest': TEAL, Active: '#9aa1ab' }
  }
];
