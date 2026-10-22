import { TableColumn } from '../table/table-column';

export const DEMAND_TABLE_COLUMNS: TableColumn[] = [
  { key: 'ts', label: 'Timestamp', kind: 'timestamp', group: 'General', locked: true },
  { key: 'mp_code', label: 'Metering Point', kind: 'text', group: 'General' },
  { key: 'gross_load_kw', label: 'Gross Load (kW)', kind: 'number', group: 'Load' },
  { key: 'behind_meter_gen_kw', label: 'Behind-meter Gen (kW)', kind: 'number', group: 'Load' },
  { key: 'net_load_kw', label: 'Net Load (kW)', kind: 'number', group: 'Load' },
  { key: 'load_reactive_kvar', label: 'Reactive (kvar)', kind: 'number', group: 'Power quality' },
  { key: 'power_factor', label: 'Power Factor', kind: 'number', group: 'Power quality' }
];

export const DEFAULT_DEMAND_COLUMN_KEYS: string[] = DEMAND_TABLE_COLUMNS.map((c) => c.key);
