import { AlarmSource } from './alarm-catalog.model';

/** Master-data tables an alarm can be linked to. */
export type LinkedAssetType =
  | 'battery_system'
  | 'battery_container'
  | 'battery_pack'
  | 'battery_module'
  | 'pcs'
  | 'ems_controller'
  | 'hvac_unit';

export const LINKED_ASSET_LABELS: Record<LinkedAssetType, string> = {
  battery_system: 'Battery System',
  battery_container: 'Container',
  battery_pack: 'Pack',
  battery_module: 'Module',
  pcs: 'PCS',
  ems_controller: 'EMS',
  hvac_unit: 'HVAC'
};

/** One alarm occurrence. Times are plant local time ("YYYY-MM-DDTHH:mm:ss+05:30"). */
export interface AlarmEvent {
  alarm_id: string;
  start_time: string;
  end_time: string | null;
  /** Derived: Active while there is no end time. */
  status: 'Active' | 'Cleared';
  duration_min: number | null;
  start_date: string;
  alarm_catalog_id: number;
  source: AlarmSource;
  alarm_code: string;
  alarm_type: string;
  description: string;
  probable_cause: string | null;
  severity_level: number;
  severity_name: string | null;
  /** The linked asset's master-data type and name, e.g. Pack / 01-01-01-PACK-01. */
  asset_type: string | null;
  asset_code: string | null;
  linked_asset_type: LinkedAssetType | null;
  linked_asset_id: number | null;
  linked_asset_name: string | null;
  battery_system_id: number | null;
  system_name: string | null;
  trigger_value: string | number | null;
  threshold_value: string | number | null;
  unit: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlarmEventInput {
  alarm_id?: string | null;
  start_time: string;
  end_time: string | null;
  alarm_catalog_id: number;
  severity_level: number | null;
  asset_type: string | null;
  asset_code: string | null;
  linked_asset_type: LinkedAssetType | null;
  linked_asset_id: number | null;
  trigger_value: number | null;
  threshold_value: number | null;
  unit: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
}

export interface AlarmEventStats {
  total: number;
  active: number;
  acknowledged: number;
  critical: number;
  mean_minutes_to_clear: number | null;
  by_source: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface AlarmEventPage {
  items: AlarmEvent[];
  total: number;
  page: number;
  page_size: number;
  /** Over the whole filtered set, not just this page. */
  stats: AlarmEventStats;
}

export interface AlarmEventFilters {
  source?: string;
  severity_level?: number | null;
  status?: 'active' | 'cleared' | '';
  acknowledged?: boolean | null;
  battery_system_id?: number | null;
  start?: string;
  end?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface AlarmEventLookups {
  catalog: {
    alarm_catalog_id: number;
    source: AlarmSource;
    alarm_code: string;
    alarm_type: string;
    severity_level: number;
    asset_type: string | null;
    threshold: string | number | null;
    unit: string | null;
  }[];
  assets: { asset_type: LinkedAssetType; asset_id: number; name: string; battery_system_id: number | null }[];
  severities: { severity_level: number; severity_name: string }[];
  systems: { battery_system_id: number; system_name: string }[];
}

export interface BulkAlarmEventResult {
  filename: string;
  sheet: string | null;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; alarm_id: string | null; errors: string[] }[];
  /** Rows whose asset was linked to a master-data record. */
  assets_linked: number;
  ignored_columns: string[];
}

/** "2026-08-01T15:50:00+05:30" -> "2026-08-01 15:50" (plant time, no conversion to the browser's zone). */
export function plantTime(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 16).replace('T', ' ') : '';
}

// ---------------------------------------------------------------- analytics (graphical tab)

export interface AlarmCount {
  key: string;
  count: number;
}

export interface AlarmSeverityCount {
  severity_level: number;
  severity_name: string;
  count: number;
  acknowledged: number;
  mean_minutes_to_ack: number | null;
}

export interface AlarmDailyCount {
  date: string;
  /** Alarms started that day, per severity level 0..3. */
  by_severity: number[];
}

export interface AlarmCodeCount {
  source: AlarmSource;
  alarm_code: string;
  description: string | null;
  count: number;
  share_pct: number;
  mean_duration_min: number | null;
}

export interface AlarmAssetCount {
  asset_type: string | null;
  asset_name: string;
  source: AlarmSource;
  count: number;
}

export interface AlarmSourceDuration {
  source: AlarmSource;
  cleared: number;
  mean_duration_min: number | null;
  max_duration_min: number | null;
}

export interface AlarmDurationPoint {
  alarm_id: string;
  start_time: string;
  duration_min: number;
  severity_level: number;
  source: AlarmSource;
  alarm_code: string;
}

export interface AlarmEventAnalytics {
  total: number;
  by_source: AlarmCount[];
  by_severity: AlarmSeverityCount[];
  by_type: AlarmCount[];
  daily: AlarmDailyCount[];
  hour_of_day: number[];
  top_codes: AlarmCodeCount[];
  top_assets: AlarmAssetCount[];
  duration_by_source: AlarmSourceDuration[];
  durations: AlarmDurationPoint[];
}
