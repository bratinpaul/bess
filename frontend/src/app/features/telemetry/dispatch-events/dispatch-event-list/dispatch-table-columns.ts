import { TableColumn } from '../../table/table-column';

/** Columns the dispatch table can show, in table order; the column selector lists them by group. */
export const DISPATCH_TABLE_COLUMNS: TableColumn[] = [
  // the columns the table has always shown
  { key: 'dispatch_id', label: 'Dispatch ID', kind: 'text', group: 'Dispatch', locked: true },
  { key: 'effective', label: 'Effective', kind: 'text', group: 'Timing' },
  { key: 'duration', label: 'Duration', kind: 'text', group: 'Timing' },
  { key: 'mode', label: 'Mode', kind: 'text', group: 'Dispatch' },
  { key: 'setpoint', label: 'Setpoint', kind: 'text', group: 'Setpoint & SOC' },
  { key: 'soc', label: 'SOC', kind: 'number', group: 'Setpoint & SOC' },
  { key: 'energy', label: 'Import / Export (kWh)', kind: 'number', group: 'Energy & market' },
  { key: 'avg_price_mwh', label: 'Price ($/MWh)', kind: 'number', group: 'Energy & market' },
  { key: 'revenue_usd', label: 'Revenue', kind: 'number', group: 'Energy & market' },
  { key: 'status', label: 'Status', kind: 'text', group: 'Dispatch' },

  // extra columns
  { key: 'issued_at', label: 'Issued At', kind: 'timestamp', group: 'Timing' },
  { key: 'effective_from', label: 'Effective From', kind: 'timestamp', group: 'Timing' },
  { key: 'effective_to', label: 'Effective To', kind: 'timestamp', group: 'Timing' },
  { key: 'issued_date', label: 'Issued Date', kind: 'text', group: 'Timing' },
  { key: 'command_code', label: 'Command', kind: 'text', group: 'Dispatch' },
  { key: 'grid_service', label: 'Grid Service', kind: 'text', group: 'Dispatch' },
  { key: 'source', label: 'Issued By', kind: 'text', group: 'Dispatch' },
  { key: 'accepted', label: 'Accepted', kind: 'text', group: 'Dispatch' },
  { key: 'ems_code', label: 'EMS', kind: 'text', group: 'Asset' },
  { key: 'system_name', label: 'Battery System', kind: 'text', group: 'Asset' },
  { key: 'p_setpoint_kw', label: 'Setpoint (kW)', kind: 'number', group: 'Setpoint & SOC' },
  { key: 'ramp_rate_kw_s', label: 'Ramp Rate (kW/s)', kind: 'number', group: 'Setpoint & SOC' },
  { key: 'soc_start_pct', label: 'SOC Start (%)', kind: 'number', group: 'Setpoint & SOC' },
  { key: 'soc_end_pct', label: 'SOC End (%)', kind: 'number', group: 'Setpoint & SOC' },
  { key: 'target_soc_pct', label: 'Target SOC (%)', kind: 'number', group: 'Setpoint & SOC' },
  { key: 'import_kwh', label: 'Imported (kWh)', kind: 'number', group: 'Energy & market' },
  { key: 'export_kwh', label: 'Exported (kWh)', kind: 'number', group: 'Energy & market' },
  { key: 'net_energy_kwh', label: 'Net Energy (kWh)', kind: 'number', group: 'Energy & market' },
  { key: 'note', label: 'Note', kind: 'text', group: 'Record' },
  { key: 'created_at', label: 'Recorded', kind: 'timestamp', group: 'Record' },
  { key: 'updated_at', label: 'Last Updated', kind: 'timestamp', group: 'Record' }
];

/** What the table showed before the column selector existed. */
export const DISPATCH_DEFAULT_COLUMN_KEYS = [
  'dispatch_id', 'effective', 'duration', 'mode', 'setpoint', 'soc', 'energy', 'avg_price_mwh', 'revenue_usd', 'status'
];
