import { TableColumn } from '../table/table-column';

export const MODULE_TABLE_COLUMNS: TableColumn[] = [
  { key: 'ts', label: 'Timestamp', kind: 'timestamp', group: 'General', locked: true },
  { key: 'serial_number', label: 'Module', kind: 'text', group: 'General' },
  { key: 'cell_v_avg_v', label: 'Cell V Avg (V)', kind: 'number', group: 'Cell voltage' },
  { key: 'cell_v_min_v', label: 'Cell V Min (V)', kind: 'number', group: 'Cell voltage' },
  { key: 'cell_v_max_v', label: 'Cell V Max (V)', kind: 'number', group: 'Cell voltage' },
  { key: 'imbalance_mv', label: 'Imbalance (mV)', kind: 'number', group: 'Cell voltage' },
  { key: 'cell_temp_min_c', label: 'Cell Temp Min (°C)', kind: 'number', group: 'Temperature' },
  { key: 'cell_temp_max_c', label: 'Cell Temp Max (°C)', kind: 'number', group: 'Temperature' },
  { key: 'balancing_active', label: 'Balancing', kind: 'text', group: 'General' }
];

/** Every column is shown by default; the table is narrow enough. */
export const DEFAULT_MODULE_COLUMN_KEYS: string[] = MODULE_TABLE_COLUMNS.map((c) => c.key);
