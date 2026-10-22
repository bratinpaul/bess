import { TableColumn } from '../table/table-column';

export const PCS_TABLE_COLUMNS: TableColumn[] = [
  // table order: the original default columns first, extra columns after
  { key: 'ts', label: 'Timestamp', kind: 'timestamp', group: 'General', locked: true },
  { key: 'pcs_code', label: 'PCS', kind: 'text', group: 'General' },
  { key: 'mode_code', label: 'Mode', kind: 'text', group: 'General' },
  { key: 'ac_active_power_kw', label: 'AC Active Power (kW)', kind: 'number', group: 'Power' },
  { key: 'power_factor', label: 'Power Factor', kind: 'number', group: 'Power' },
  { key: 'ac_frequency_hz', label: 'AC Frequency (Hz)', kind: 'number', group: 'AC side' },
  { key: 'igbt_temp_c', label: 'IGBT Temp (°C)', kind: 'number', group: 'Temperature' },
  { key: 'efficiency_pct', label: 'Efficiency (%)', kind: 'number', group: 'Quality' },
  { key: 'breaker_state', label: 'Breaker', kind: 'text', group: 'General' },
  { key: 'alarm_level', label: 'Alarm', kind: 'alarm', group: 'General' },

  { key: 'grid_service', label: 'Grid Service', kind: 'text', group: 'General' },
  { key: 'ac_reactive_power_kvar', label: 'AC Reactive Power (kvar)', kind: 'number', group: 'Power' },
  { key: 'ac_apparent_power_kva', label: 'AC Apparent Power (kVA)', kind: 'number', group: 'Power' },
  { key: 'dc_power_kw', label: 'DC Power (kW)', kind: 'number', group: 'Power' },
  { key: 'avail_charge_kw', label: 'Avail. Charge (kW)', kind: 'number', group: 'Power' },
  { key: 'avail_discharge_kw', label: 'Avail. Discharge (kW)', kind: 'number', group: 'Power' },
  { key: 'ac_voltage_ab_v', label: 'AC Voltage AB (V)', kind: 'number', group: 'AC side' },
  { key: 'ac_voltage_bc_v', label: 'AC Voltage BC (V)', kind: 'number', group: 'AC side' },
  { key: 'ac_voltage_ca_v', label: 'AC Voltage CA (V)', kind: 'number', group: 'AC side' },
  { key: 'ac_current_a_a', label: 'AC Current A (A)', kind: 'number', group: 'AC side' },
  { key: 'ac_current_b_a', label: 'AC Current B (A)', kind: 'number', group: 'AC side' },
  { key: 'ac_current_c_a', label: 'AC Current C (A)', kind: 'number', group: 'AC side' },
  { key: 'dc_voltage_v', label: 'DC Voltage (V)', kind: 'number', group: 'DC side' },
  { key: 'dc_current_a', label: 'DC Current (A)', kind: 'number', group: 'DC side' },
  { key: 'thd_voltage_pct', label: 'THD Voltage (%)', kind: 'number', group: 'Quality' },
  { key: 'thd_current_pct', label: 'THD Current (%)', kind: 'number', group: 'Quality' },
  { key: 'heatsink_temp_c', label: 'Heatsink Temp (°C)', kind: 'number', group: 'Temperature' },
  { key: 'inlet_coolant_temp_c', label: 'Inlet Coolant Temp (°C)', kind: 'number', group: 'Temperature' },
  { key: 'ambient_temp_c', label: 'Ambient Temp (°C)', kind: 'number', group: 'Temperature' },
  { key: 'ac_energy_import_kwh', label: 'AC Energy Import (kWh)', kind: 'number', group: 'Energy' },
  { key: 'ac_energy_export_kwh', label: 'AC Energy Export (kWh)', kind: 'number', group: 'Energy' }
];

/** The columns the table showed before the column selector existed. */
export const DEFAULT_PCS_COLUMN_KEYS: string[] = [
  'ts',
  'pcs_code',
  'mode_code',
  'ac_active_power_kw',
  'power_factor',
  'ac_frequency_hz',
  'igbt_temp_c',
  'efficiency_pct',
  'breaker_state',
  'alarm_level'
];
