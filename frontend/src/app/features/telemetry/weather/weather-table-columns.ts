import { TableColumn } from '../table/table-column';

export const WEATHER_TABLE_COLUMNS: TableColumn[] = [
  { key: 'ts', label: 'Timestamp', kind: 'timestamp', group: 'General', locked: true },
  { key: 'station_code', label: 'Station', kind: 'text', group: 'General' },
  { key: 'temp_c', label: 'Temperature (°C)', kind: 'number', group: 'Air' },
  { key: 'humidity_pct', label: 'Humidity (%)', kind: 'number', group: 'Air' },
  { key: 'dew_point_c', label: 'Dew Point (°C)', kind: 'number', group: 'Air' },
  { key: 'ghi_wm2', label: 'GHI (W/m²)', kind: 'number', group: 'Sun' },
  { key: 'cloud_fraction', label: 'Cloud Fraction', kind: 'number', group: 'Sun' },
  { key: 'wind_ms', label: 'Wind (m/s)', kind: 'number', group: 'Wind' }
];

export const DEFAULT_WEATHER_COLUMN_KEYS: string[] = WEATHER_TABLE_COLUMNS.map((c) => c.key);
