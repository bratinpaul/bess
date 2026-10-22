import { TableColumn } from '../table/table-column';

export const BMS_TABLE_COLUMNS: TableColumn[] = [
  // table order: the original default columns first, extra columns after
  { key: 'ts', label: 'Timestamp', kind: 'timestamp', group: 'General', locked: true },
  { key: 'system_name', label: 'System', kind: 'text', group: 'General' },
  { key: 'mode_code', label: 'Mode', kind: 'text', group: 'General' },
  { key: 'soc_bms_pct', label: 'SOC (BMS) %', kind: 'number', group: 'State' },
  { key: 'soh_pct', label: 'SOH %', kind: 'number', group: 'State' },
  { key: 'pack_voltage_v', label: 'Pack Voltage (V)', kind: 'number', group: 'Electrical' },
  { key: 'power_kw', label: 'Power (kW)', kind: 'number', group: 'Electrical' },
  { key: 'cell_temp_avg_c', label: 'Cell Temp Avg (°C)', kind: 'number', group: 'Temperature' },
  { key: 'contactor_state', label: 'Contactor', kind: 'text', group: 'General' },
  { key: 'alarm_level', label: 'Alarm', kind: 'alarm', group: 'General' },

  { key: 'c_rate', label: 'C-Rate', kind: 'number', group: 'State' },
  { key: 'equiv_full_cycles', label: 'Equiv. Full Cycles', kind: 'number', group: 'State' },
  { key: 'pack_current_a', label: 'Pack Current (A)', kind: 'number', group: 'Electrical' },
  { key: 'avail_charge_kw', label: 'Avail. Charge (kW)', kind: 'number', group: 'Electrical' },
  { key: 'avail_discharge_kw', label: 'Avail. Discharge (kW)', kind: 'number', group: 'Electrical' },
  { key: 'insulation_res_kohm', label: 'Insulation (kΩ)', kind: 'number', group: 'Electrical' },
  { key: 'cell_v_avg_v', label: 'Cell V Avg (V)', kind: 'number', group: 'Cell voltage' },
  { key: 'cell_v_min_v', label: 'Cell V Min (V)', kind: 'number', group: 'Cell voltage' },
  { key: 'cell_v_max_v', label: 'Cell V Max (V)', kind: 'number', group: 'Cell voltage' },
  { key: 'cell_v_delta_mv', label: 'Cell V Delta (mV)', kind: 'number', group: 'Cell voltage' },
  { key: 'cell_temp_min_c', label: 'Cell Temp Min (°C)', kind: 'number', group: 'Temperature' },
  { key: 'cell_temp_max_c', label: 'Cell Temp Max (°C)', kind: 'number', group: 'Temperature' },
  { key: 'coolant_temp_c', label: 'Coolant Temp (°C)', kind: 'number', group: 'Temperature' },
  { key: 'ambient_temp_c', label: 'Ambient Temp (°C)', kind: 'number', group: 'Temperature' },
  { key: 'cum_charge_kwh', label: 'Cum. Charge (kWh)', kind: 'number', group: 'Energy' },
  { key: 'cum_discharge_kwh', label: 'Cum. Discharge (kWh)', kind: 'number', group: 'Energy' },
  { key: 'soc_coulomb_pct', label: 'SOC Coulomb %', kind: 'number', group: 'SOC estimation' },
  { key: 'soc_battery_telemetry_pct', label: 'SOC Telemetry %', kind: 'number', group: 'SOC estimation' },
  { key: 'usable_capacity_ah', label: 'Usable Capacity (Ah)', kind: 'number', group: 'SOC estimation' },
  { key: 'coulombic_efficiency', label: 'Coulombic Efficiency', kind: 'number', group: 'SOC estimation' },
  { key: 'measured_current_a', label: 'Measured Current (A)', kind: 'number', group: 'Current sensing' },
  { key: 'current_sensor_offset_a', label: 'Current Sensor Offset (A)', kind: 'number', group: 'Current sensing' },
  { key: 'at_rest_label', label: 'At Rest', kind: 'text', group: 'Rest / OCV' },
  { key: 'rest_duration_min', label: 'Rest Duration (min)', kind: 'number', group: 'Rest / OCV' },
  { key: 'ocv_rested_v', label: 'Rested OCV (V)', kind: 'number', group: 'Rest / OCV' }
];

/** The columns the table showed before the column selector existed. */
export const DEFAULT_COLUMN_KEYS: string[] = [
  'ts',
  'system_name',
  'mode_code',
  'soc_bms_pct',
  'soh_pct',
  'pack_voltage_v',
  'power_kw',
  'cell_temp_avg_c',
  'contactor_state',
  'alarm_level'
];
