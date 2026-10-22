import { TableColumn } from '../table/table-column';

export const EMS_TABLE_COLUMNS: TableColumn[] = [
  // table order: the original default columns first, extra columns after
  { key: 'ts', label: 'Timestamp', kind: 'timestamp', group: 'General', locked: true },
  { key: 'ems_code', label: 'EMS', kind: 'text', group: 'General' },
  { key: 'dispatch_mode', label: 'Dispatch Mode', kind: 'text', group: 'General' },
  { key: 'grid_service', label: 'Grid Service', kind: 'text', group: 'General' },
  { key: 'poi_active_power_kw', label: 'POI Power (kW)', kind: 'number', group: 'Power' },
  { key: 'grid_frequency_hz', label: 'Grid Freq (Hz)', kind: 'number', group: 'Grid' },
  { key: 'plant_soc_pct', label: 'Plant SOC (%)', kind: 'number', group: 'State' },
  { key: 'market_price_mwh', label: 'Market Price ($/MWh)', kind: 'number', group: 'Market' },
  { key: 'plant_available', label: 'Available', kind: 'text', group: 'General' },
  { key: 'alarm_level', label: 'Alarm', kind: 'alarm', group: 'General' },

  { key: 'p_setpoint_kw', label: 'P Setpoint (kW)', kind: 'number', group: 'Power' },
  { key: 'tracking_error_kw', label: 'Tracking Error (kW)', kind: 'number', group: 'Power' },
  { key: 'poi_reactive_power_kvar', label: 'POI Reactive (kvar)', kind: 'number', group: 'Power' },
  { key: 'avail_charge_kw', label: 'Avail. Charge (kW)', kind: 'number', group: 'Power' },
  { key: 'avail_discharge_kw', label: 'Avail. Discharge (kW)', kind: 'number', group: 'Power' },
  { key: 'poi_voltage_kv', label: 'POI Voltage (kV)', kind: 'number', group: 'Grid' },
  { key: 'agc_signal', label: 'AGC Signal', kind: 'number', group: 'Grid' },
  { key: 'target_soc_pct', label: 'Target SOC (%)', kind: 'number', group: 'State' },
  { key: 'avail_charge_energy_kwh', label: 'Avail. Charge Energy (kWh)', kind: 'number', group: 'State' },
  { key: 'avail_discharge_energy_kwh', label: 'Avail. Discharge Energy (kWh)', kind: 'number', group: 'State' },
  { key: 'units_online', label: 'Units Online', kind: 'number', group: 'State' },
  { key: 'revenue_cum_usd', label: 'Cum. Revenue ($)', kind: 'number', group: 'Market' },
  { key: 'cum_import_kwh', label: 'Cum. Import (kWh)', kind: 'number', group: 'Energy' },
  { key: 'cum_export_kwh', label: 'Cum. Export (kWh)', kind: 'number', group: 'Energy' },
  { key: 'aux_load_kw', label: 'Aux Load (kW)', kind: 'number', group: 'Energy' },
  { key: 'aux_load_pct', label: 'Aux Load (%)', kind: 'number', group: 'Energy' }
];

/** The columns the table showed before the column selector existed. */
export const DEFAULT_EMS_COLUMN_KEYS: string[] = EMS_TABLE_COLUMNS.slice(0, 10).map((c) => c.key);
