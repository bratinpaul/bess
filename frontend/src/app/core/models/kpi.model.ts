/** Configurable daily KPIs (backend kpi_config/<domain>_kpi.yaml → battery_ml.<domain>_kpi), shared by the BMS
 *  (per battery system), PCS (per PCS unit) and EMS (per EMS controller / plant) Analytics tabs. A domain says which API and entity to use. */

export interface KpiDomain {
  key: 'bms' | 'pcs' | 'ems';
  /** API path under /api */
  apiPath: string;
  /** entity id query / body parameter */
  idParam: 'system_id' | 'pcs_id' | 'ems_id';
  entityLabel: string;
  entityPlural: string;
  configFile: string;
  runTable: string;
  telemetryLabel: string;
  /** localStorage key of the selected group chip */
  storageKey: string;
}

export const BMS_KPI_DOMAIN: KpiDomain = {
  key: 'bms',
  apiPath: 'bms-kpi',
  idParam: 'system_id',
  entityLabel: 'System',
  entityPlural: 'systems',
  configFile: 'bms_kpi.yaml',
  runTable: 'battery_ml.bms_kpi_run',
  telemetryLabel: 'BMS telemetry',
  storageKey: 'bess.bmsKpi.group'
};

export const PCS_KPI_DOMAIN: KpiDomain = {
  key: 'pcs',
  apiPath: 'pcs-kpi',
  idParam: 'pcs_id',
  entityLabel: 'PCS unit',
  entityPlural: 'PCS units',
  configFile: 'pcs_kpi.yaml',
  runTable: 'battery_ml.pcs_kpi_run',
  telemetryLabel: 'PCS telemetry',
  storageKey: 'bess.pcsKpi.group'
};

export const EMS_KPI_DOMAIN: KpiDomain = {
  key: 'ems',
  apiPath: 'ems-kpi',
  idParam: 'ems_id',
  entityLabel: 'EMS controller',
  entityPlural: 'EMS controllers',
  configFile: 'ems_kpi.yaml',
  runTable: 'battery_ml.ems_kpi_run',
  telemetryLabel: 'EMS telemetry',
  storageKey: 'bess.emsKpi.group'
};

export interface KpiEntity {
  id: number;
  name: string;
  /** telemetry rows of the entity */
  samples: number;
}

export interface KpiFilter {
  column: string;
  op: string;
  value: number | string | boolean | (number | string)[];
}

export interface KpiDefinition {
  code: string;
  name: string;
  unit: string | null;
  description: string | null;
  method: 'integrate' | 'aggregate' | 'counter_delta' | 'derived' | 'query';
  group: string;
  query: string | null;
  field: string | null;
  default: number | null;
  column: string | null;
  func: string | null;
  scale: number;
  filter: KpiFilter[];
  formula: string | null;
  formula_text: string;
  decimals: number;
  summary: 'sum' | 'avg' | 'min' | 'max' | 'last' | 'formula';
  color: string | null;
  dashed: boolean;
  enabled: boolean;
}

export interface KpiChart {
  title: string;
  type: 'bar' | 'line';
  kpis: string[];
}

export interface KpiGroup {
  code: string;
  name: string;
  description: string | null;
}

export interface KpiConfig {
  domain: string;
  entity_param: string;
  file_path: string;
  version: number;
  config_hash: string;
  timezone: string;
  interval: { mode: 'fixed' | 'actual'; minutes: number; max_gap_minutes: number };
  expected_samples_per_day: number;
  groups: KpiGroup[];
  params: Record<string, number>;
  system_params: Record<string, { sql: string; unit: string | null; description: string | null }>;
  system_overrides: Record<string, Record<string, number>>;
  queries: Record<string, { description: string | null; sql: string }>;
  kpis: KpiDefinition[];
  charts: KpiChart[];
  /** KPI codes of the rollup row above the groups */
  tiles: string[];
}

export interface KpiDay {
  kpi_date: string;
  sample_count: number;
  coverage_pct: number;
  calculated_at: string;
  /** computed with a different version of the config file than the current one */
  stale: boolean;
  values: Record<string, number | null>;
}

export interface KpiData {
  entity_id: number;
  entity_name: string;
  config_hash: string;
  kpis: { code: string; name: string; unit: string | null; in_config: boolean }[];
  days: KpiDay[];
  /** one value per KPI for the whole range, combined per the config's summary rule */
  summary: Record<string, number | null>;
}

export interface KpiDateRange {
  telemetry_start: string | null;
  telemetry_end: string | null;
  kpi_start: string | null;
  kpi_end: string | null;
  kpi_days: number;
}

export interface KpiCalculateRequest {
  /** null = every entity with telemetry */
  entityId: number | null;
  start_date: string | null;
  end_date: string | null;
  dry_run?: boolean;
}

export interface KpiCalculateResult {
  run_id: number | null;
  status: string;
  dry_run: boolean;
  systems_done: number;
  days: number;
  rows_deleted: number;
  rows_written: number;
  kpi_codes: string[];
  config_version: number;
  config_hash: string;
  duration_ms: number;
}

export interface KpiRun {
  run_id: number;
  status: 'running' | 'success' | 'failed';
  triggered_by: string;
  entity_ids: number[] | null;
  entity_names: string[] | null;
  start_date: string | null;
  end_date: string | null;
  config_version: number;
  config_hash: string;
  kpi_codes: string[];
  entities_done: number | null;
  days: number | null;
  rows_deleted: number | null;
  rows_written: number | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}
