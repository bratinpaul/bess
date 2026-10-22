import { TableColumn } from '../table/table-column';

export const HVAC_TABLE_COLUMNS: TableColumn[] = [
  // table order: the original default columns first, extra columns after
  { key: 'ts', label: 'Timestamp', kind: 'timestamp', group: 'General', locked: true },
  { key: 'hvac_code', label: 'HVAC Unit', kind: 'text', group: 'General' },
  { key: 'cooling_mode', label: 'Cooling Mode', kind: 'text', group: 'General' },
  { key: 'ambient_temp_c', label: 'Ambient Temp (°C)', kind: 'number', group: 'Enclosure' },
  { key: 'coolant_supply_temp_c', label: 'Coolant Supply (°C)', kind: 'number', group: 'Coolant' },
  { key: 'hvac_power_kw', label: 'HVAC Power (kW)', kind: 'number', group: 'Thermal power' },
  { key: 'cop', label: 'COP', kind: 'number', group: 'Thermal power' },
  { key: 'enclosure_temp_c', label: 'Enclosure Temp (°C)', kind: 'number', group: 'Enclosure' },
  { key: 'units_running', label: 'Units Running', kind: 'number', group: 'Compressor' },
  { key: 'alarm_level', label: 'Alarm', kind: 'alarm', group: 'General' },

  { key: 'alarm_flags', label: 'Alarm Flags', kind: 'text', group: 'General' },
  { key: 'coolant_setpoint_c', label: 'Coolant Setpoint (°C)', kind: 'number', group: 'Coolant' },
  { key: 'coolant_return_temp_c', label: 'Coolant Return (°C)', kind: 'number', group: 'Coolant' },
  { key: 'coolant_delta_t_c', label: 'Coolant ΔT (°C)', kind: 'number', group: 'Coolant' },
  { key: 'coolant_flow_lpm', label: 'Coolant Flow (L/min)', kind: 'number', group: 'Coolant' },
  { key: 'enclosure_humidity_pct', label: 'Enclosure Humidity (%)', kind: 'number', group: 'Enclosure' },
  { key: 'filter_dp_pa', label: 'Filter ΔP (Pa)', kind: 'number', group: 'Enclosure' },
  { key: 'battery_heat_load_kw', label: 'Battery Heat Load (kW)', kind: 'number', group: 'Thermal power' },
  { key: 'cooling_capacity_kw', label: 'Cooling Capacity (kW)', kind: 'number', group: 'Thermal power' },
  { key: 'heat_rejected_kw', label: 'Heat Rejected (kW)', kind: 'number', group: 'Thermal power' },
  { key: 'compressor_speed_pct', label: 'Compressor Speed (%)', kind: 'number', group: 'Compressor' },
  { key: 'condenser_fan_pct', label: 'Condenser Fan (%)', kind: 'number', group: 'Compressor' },
  { key: 'refrig_suction_bar', label: 'Refrig. Suction (bar)', kind: 'number', group: 'Compressor' },
  { key: 'refrig_discharge_bar', label: 'Refrig. Discharge (bar)', kind: 'number', group: 'Compressor' },
  { key: 'compressor_runtime_h', label: 'Compressor Runtime (h)', kind: 'number', group: 'Compressor' },
  { key: 'cum_energy_kwh', label: 'Cum. Energy (kWh)', kind: 'number', group: 'Thermal power' }
];

/** The columns the table showed before the column selector existed. */
export const DEFAULT_HVAC_COLUMN_KEYS: string[] = HVAC_TABLE_COLUMNS.slice(0, 10).map((c) => c.key);
