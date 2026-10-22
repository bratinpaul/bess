export type AlarmSource = 'BMS' | 'PCS' | 'HVAC' | 'EMS';

export const ALARM_SOURCES: AlarmSource[] = ['BMS', 'PCS', 'HVAC', 'EMS'];

/** An alarm a source system can raise; unique by (source, alarm_code). */
export interface AlarmCatalogEntry {
  alarm_catalog_id: number;
  alarm_code: string;
  source: AlarmSource;
  alarm_type: string;
  /** 0 Info, 1 Warning, 2 Alarm, 3 Critical (alarm_severity). */
  severity_level: number;
  severity_name: string | null;
  asset_type: string | null;
  description: string;
  probable_cause: string | null;
  /** Numeric, returned as a string by the API. */
  threshold: string | number | null;
  unit: string | null;
  created_at: string;
  updated_at: string;
}

export type AlarmCatalogInput = Omit<AlarmCatalogEntry, 'alarm_catalog_id' | 'severity_name' | 'created_at' | 'updated_at'>;

export interface AlarmSeverity {
  severity_level: number;
  severity_name: string;
}

export interface AlarmCatalogLookups {
  sources: AlarmSource[];
  severities: AlarmSeverity[];
  /** Values already used, offered as suggestions. */
  alarm_types: string[];
  asset_types: string[];
}

export interface BulkAlarmCatalogResult {
  filename: string;
  sheet: string | null;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; errors: string[] }[];
  ignored_columns: string[];
}
