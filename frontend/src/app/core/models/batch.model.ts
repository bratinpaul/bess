export type BatchStatusValue = 'SUCCESS' | 'PARTIAL' | 'FAILED';

export interface BatchFeedResult {
  feed: string;
  rows: number;
  csv?: string;
  endpoint?: string;
  http?: number;
  inserted?: number;
  updated?: number;
  skipped?: number;
  errors?: string[];
  error?: string;
  result?: string;
  closed_dispatches?: string[];
  not_in_snapshot?: string[];
}

/** One row of battery_raw.batchlog: a snapshot file the realtime batch processed. */
export interface BatchLog {
  batch_id: number;
  run_id: string;
  file_name: string;
  file_time: string | null;
  snapshot_time: string | null;
  status: BatchStatusValue;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  feeds_total: number;
  feeds_loaded: number;
  feeds_failed: number;
  rows_total: number;
  rows_inserted: number;
  rows_updated: number;
  rows_skipped: number;
  feed_results: BatchFeedResult[];
  warnings: string[];
  id_changes: string[];
  error_message: string | null;
  archive_path: string | null;
}

export interface BatchLogPage {
  items: BatchLog[];
  total: number;
  counts: Record<BatchStatusValue, number>;
}

export interface InboxFile {
  name: string;
  size_bytes: number;
  modified_at: string;
  /** Named YYYY-MM-DD-HH-MM-SS.json; anything else is ignored by the batch. */
  valid_name: boolean;
  /** Not changed in the last few seconds, so the next run takes it. */
  ready: boolean;
}

export interface ScheduleInfo {
  task_name: string;
  installed: boolean;
  status: string | null;
  next_run: string | null;
  last_run: string | null;
  last_result: string | null;
  repeat_every: string | null;
}

export interface BatchStatus {
  inbox: string;
  archive: string;
  files: InboxFile[];
  running: boolean;
  running_since: string | null;
  schedule: ScheduleInfo;
  last_run: BatchLog | null;
}

export interface BatchRunResult {
  started_at: string;
  finished_at: string;
  exit_code: number;
  /** Another run held the lock, so this one did nothing. */
  busy: boolean;
  runs: BatchLog[];
  output: string[];
}

// ---------------------------------------------------------------- snapshot simulator

export interface SimulatorInfo {
  system_name: string;
  /** Historical days with complete BMS, PCS, EMS and HVAC telemetry (sampled from). */
  source_days: string[];
  module_days: string[];
  latest_telemetry: string | null;
  inbox: string;
  max_files: number;
  interval_minutes: number;
}

export interface SimulatorRequest {
  /** Plant local time, "YYYY-MM-DDTHH:mm:00". */
  start: string;
  end: string;
  seed: number | null;
  overwrite: boolean;
  source_from: string | null;
  source_to: string | null;
}

export interface SimulatorResult {
  start: string;
  end: string;
  intervals: number;
  written: number;
  skipped_existing: number;
  already_loaded: number;
  first_file: string | null;
  last_file: string | null;
  /** Simulated day -> the historical day it replays. */
  source_days: Record<string, string>;
  warnings: string[];
  inbox: string;
}

/** The static master data batch (GET /api/batch/static/status). */
export interface StaticBatchStatus {
  inbox: string;
  archive: string;
  files: InboxFile[];
  running: boolean;
  running_since: string | null;
  last_run: BatchLog | null;
}

// ---------------------------------------------------------------- historical telemetry loader

export type HistoricalFeed = 'bms' | 'pcs' | 'ems' | 'hvac' | 'module' | 'alarm' | 'dispatch';

export interface HistoricalSystem {
  battery_system_id: number;
  system_name: string;
  ems_codes: string[];
  hvac_codes: string[];
}

export interface HistoricalSite {
  site_id: number;
  site_name: string;
  site_code: string;
  systems: HistoricalSystem[];
}

export interface HistoricalOptions {
  input_root: string;
  folders: { path: string; files: number }[];
  sites: HistoricalSite[];
  feeds: { key: HistoricalFeed; label: string; endpoint: string }[];
}

export interface HistoricalLoadRequest {
  system_name: string;
  folder: string;
  feeds: HistoricalFeed[];
  recursive: boolean;
  ems_code: string | null;
  hvac_code: string | null;
  /** Files to load (names relative to the folder, as the scan returns them). */
  files?: string[] | null;
}

export interface HistoricalScanFile {
  path: string;
  name: string;
  size: number;
  ok: boolean;
  message: string | null;
  selected: boolean;
}

export interface HistoricalScan {
  folder: string;
  site_name: string;
  system_name: string;
  feeds: { key: HistoricalFeed; label: string; endpoint: string; files: HistoricalScanFile[] }[];
  ignored: string[];
  problems: string[];
  ems_code: string | null;
  hvac_code: string | null;
}

export interface HistoricalProgressFile {
  feed: string;
  file: string;
  status: 'PENDING' | 'LOADING' | 'LOADED' | 'PARTIAL' | 'FAILED' | 'SKIPPED' | 'EXCLUDED';
  message?: string | null;
  rows?: number;
  inserted?: number;
  updated?: number;
  skipped?: number;
  seconds?: number;
  errors?: string[];
}

export interface HistoricalStatus {
  running: boolean;
  running_since: string | null;
  progress: {
    run_id: string;
    status: 'RUNNING' | BatchStatusValue;
    started_at: string;
    finished_at?: string;
    folder: string;
    system: string;
    site?: string;
    files: HistoricalProgressFile[];
    current: string | null;
    error: string | null;
    batch_id: number | null;
    totals?: { rows_inserted: number; rows_updated: number; rows_skipped: number; rows_total: number };
  } | null;
}

// ---------------------------------------------------------------- historical generator

export interface GeneratorSystem {
  battery_system_id: number;
  system_name: string;
  site_id: number;
  site_name: string;
  state: string | null;
  rated_power_mw: number;
  rated_energy_mwh: number;
  pcs: number;
  ems: number;
  hvac: number;
  modules: number;
  ready: boolean;
  missing: string[];
  folder: string;
  folder_relative: string;
  climate: string;
  existing_files: number;
  last_generated: { at: string; date_from: string; date_to: string } | null;
}

export interface GeneratorOptions {
  samples_folder: string;
  sample_files: string[];
  missing_samples: string[];
  max_days: number;
  default_from: string;
  default_to: string;
  systems: GeneratorSystem[];
}

/** Scenario days of one site; dates are YYYY-MM-DD, times HH:MM. */
export interface GeneratorCalendar {
  heat: Record<string, number>;
  monsoon: string[];
  low_insulation: string | null;
  maintenance: { date: string; start: string; end: string } | null;
  outage: { date: string; restart: string } | null;
}

export type GeneratorFieldName =
  | 'rated_kw'
  | 'capacity_kwh'
  | 'series_cells'
  | 'ac_voltage'
  | 'soh_start'
  | 'pcs_code'
  | 'ems_code'
  | 'hvac_code'
  | 'climate_key'
  | 'prefix';

export interface GeneratorPreview {
  battery_system_id: number;
  system_name: string;
  site_name: string;
  site_code: string;
  state: string | null;
  packs: number;
  modules: number;
  fields: { name: GeneratorFieldName; label: string; kind: 'float' | 'int' | 'str'; master: number | string }[];
  choices: {
    pcs_code: string[];
    ems_code: string[];
    hvac_code: string[];
    climate_key: { key: string; label: string; heat_amp: [number, number] }[];
  };
  changed: Record<string, { master: unknown; used: unknown }>;
  climate: string;
  heat_amp: [number, number];
  calendar: GeneratorCalendar;
  date_from: string;
  date_to: string;
  module_from: string;
  folder: string;
  folder_relative: string;
  existing_files: number;
  scaling: { power: number; soc_swing: number; ac_voltage: number };
}

export interface GeneratorRunRequest {
  date_from: string;
  date_to: string;
  module_from: string | null;
  sites: {
    battery_system_id: number;
    site_name: string;
    overrides: Partial<Record<GeneratorFieldName, number | string>>;
    calendar: GeneratorCalendar | null;
  }[];
}

export interface GeneratorProgressSite {
  battery_system_id: number;
  site_name: string | null;
  system_name: string | null;
  folder_relative: string | null;
  status: 'PENDING' | 'GENERATING' | 'DONE' | 'FAILED';
  step: string | null;
  seconds: number | null;
  files: number | null;
  rows: number | null;
  error: string | null;
  warnings: string[];
  scenarios: Record<string, number> | null;
  overrides: Record<string, { master: unknown; used: unknown }> | null;
}

export interface GeneratorStatus {
  running: boolean;
  running_since: string | null;
  progress: {
    run_id: string;
    status: 'RUNNING' | BatchStatusValue;
    started_at: string;
    finished_at: string | null;
    date_from: string;
    date_to: string;
    module_from: string | null;
    sites: GeneratorProgressSite[];
    current: string | null;
    error: string | null;
    batch_id: number | null;
  } | null;
}
