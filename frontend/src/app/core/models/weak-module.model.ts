/** Weak module detection (ML service /weak-module): Isolation Forest + DBSCAN on module V/T deviations. */

export type WeakVerdict = 'WEAK' | 'SUSPECT' | 'NORMAL';

export interface WeakParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float' | 'choice';
  default: number | string;
  min?: number;
  max?: number;
  step?: number;
  help?: string;
  choices?: string[];
}

export interface WeakFeatureMeta {
  key: string;
  label: string;
  unit: string;
}

export interface WeakSystemCoverage {
  battery_system_id: number;
  system_name: string;
  site_name: string;
  date_from: string;
  date_to: string;
  days: number;
  modules: number;
  packs: number;
}

export interface WeakOptions {
  systems: WeakSystemCoverage[];
  feature_groups: { key: string; label: string; features: WeakFeatureMeta[] }[];
  grains: { key: 'day' | 'hour'; label: string }[];
  models: { key: 'isolation_forest' | 'dbscan'; label: string; params: WeakParamSpec[] }[];
  default_min_anomalous_share: number;
}

export interface WeakWindow {
  battery_system_id: number;
  date_from: string | null;
  date_to: string | null;
  grain: 'day' | 'hour';
}

export interface WeakDetectRequest extends WeakWindow {
  feature_groups: string[];
  if_params: Record<string, number | string>;
  db_params: Record<string, number | string>;
  min_anomalous_share: number;
  run_name: string | null;
}

export interface WeakPreview {
  rows: number;
  modules?: number;
  packs?: number;
  from?: string;
  to?: string;
  days?: number;
  rows_per_module?: number;
}

export interface WeakRun {
  run_id: number;
  run_kind: 'train' | 'score';
  parent_run_id: number | null;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  battery_system_id: number;
  system_name: string;
  date_from: string | null;
  date_to: string | null;
  grain: 'day' | 'hour';
  feature_groups: string[];
  features: string[];
  params: {
    isolation_forest?: Record<string, number>;
    dbscan?: Record<string, number | string>;
    min_anomalous_share?: number;
  };
  n_rows: number | null;
  n_modules: number | null;
  n_packs: number | null;
  if_anomalies: number | null;
  db_noise: number | null;
  db_clusters: number | null;
  eps_used: number | null;
  silhouette: number | null;
  n_weak: number | null;
  n_suspect: number | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface WeakReason {
  feature: string;
  label: string;
  value: number;
  z: number;
  text: string;
}

export interface WeakModuleResult {
  module_id: number;
  serial_number: string;
  pack_id: number;
  pack_number: string;
  position: number;
  verdict: WeakVerdict;
  combined_score: number;
  rank: number;
  n_points: number;
  if_score_mean: number;
  if_anomaly_share: number;
  db_noise_share: number;
  if_flag: boolean;
  db_flag: boolean;
  feature_means: Record<string, number>;
  reasons: WeakReason[];
  first_anomaly: string | null;
}

export interface WeakRunDetail extends WeakRun {
  modules: WeakModuleResult[];
  feature_stats: Record<string, { mean: number; std: number; min: number; max: number } | number | null>;
}

export interface WeakPoint {
  module_id: number;
  bucket: string;
  features: Record<string, number>;
  if_score: number;
  if_flag: boolean;
  db_label: number;
}

export interface WeakSeriesPoint {
  bucket: string;
  v_dev_pack_mv: number | null;
  t_dev_pack_c: number | null;
  imbalance_mv: number | null;
  v_p10: number | null;
  v_p90: number | null;
  t_p10: number | null;
  t_p90: number | null;
}
