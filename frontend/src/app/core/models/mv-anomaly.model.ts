export type MvModelKey = 'pca' | 'iforest' | 'robust_cov' | 'autoencoder' | 'window_ae';
export type MvRunKind = 'train' | 'score' | 'live';

export interface MvParamSpec {
  name: string;
  label: string;
  min?: number;
  max?: number;
  step?: number;
}

export interface MvSystem {
  battery_system_id: number;
  system_name: string;
  site_name: string | null;
  date_from: string;
  date_to: string;
  rows: number;
  has_pcs: boolean;
  has_hvac: boolean;
  has_ems: boolean;
  alarms: number;
}

export interface MvOptions {
  systems: MvSystem[];
  models: { key: MvModelKey; label: string; interpretable: boolean; params: MvParamSpec[]; defaults: Record<string, number> }[];
  feature_groups: { key: string; label: string; features: { key: string; label: string }[] }[];
  regimes: string[];
  soc_bands: string[];
  frozen_signals: { key: string; label: string; only_when_active: boolean }[];
  defaults: {
    models: MvModelKey[];
    primary: MvModelKey;
    regime_strategy: 'feature' | 'separate';
    min_regime_rows: number;
    eval_fraction: number;
    threshold_pct: number;
    threshold_mode: 'percentile' | 'best_f1';
    smooth_window: number;
    debounce: number;
    frozen_intervals: number;
    alarm_pad_min: number;
    commissioning_days: number;
    top_k: number;
  };
}

export interface MvWindow {
  system_id: number;
  date_from: string | null;
  date_to: string | null;
  eval_fraction: number;
  frozen_intervals: number;
  alarm_pad_min: number;
  commissioning_days: number;
  exclude_alarm_level: boolean;
}

export interface MvPreview {
  rows: number;
  train_rows: number;
  eval_rows: number;
  clean_train_rows: number;
  excluded: Record<string, number>;
  eval_from: string;
  regimes: Record<string, number>;
  alarm_events: { train: number; eval: number };
  rule_rows: number;
  subsystems: Record<string, boolean>;
}

export interface MvTrainRequest extends MvWindow {
  models: MvModelKey[];
  primary: MvModelKey;
  model_params: Record<string, Record<string, number>>;
  feature_groups: string[];
  regime_strategy: 'feature' | 'separate';
  min_regime_rows: number;
  threshold_pct: number;
  threshold_mode: 'percentile' | 'best_f1';
  smooth_window: number;
  debounce: number;
  top_k: number;
  run_name: string | null;
  make_default: boolean;
}

export interface MvMetrics {
  precision: number | null;
  recall: number | null;
  f1: number | null;
  tp: number;
  fp: number;
  fn: number;
  auc: number | null;
  alarm_events: number;
  event_recall: number | null;
  episodes: number;
  episode_precision: number | null;
  flag_rate: number | null;
  label_rate: number | null;
}

export interface MvRun {
  run_id: number;
  run_name: string | null;
  run_kind: MvRunKind;
  parent_run_id: number | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  system_id: number;
  system_name: string;
  date_from: string | null;
  date_to: string | null;
  eval_from: string | null;
  params: Partial<MvTrainRequest>;
  summary: Record<string, any> | null;
  metrics: Record<string, MvMetrics> | null;
  warnings: string[] | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  features?: string[];
  thresholds?: { raw: Record<string, Record<string, number>>; limits: Record<string, number> };
  model?: { run_id: number; run_name: string | null; params: Partial<MvTrainRequest>; thresholds: MvRun['thresholds']; metrics: MvRun['metrics'] };
}

export interface MvContributor {
  feature: string;
  label: string;
  share: number;
}

export interface MvTimelinePoint {
  ts: string;
  score: number | null;
  smooth: number | null;
  flag: boolean;
  model_flag: boolean;
  rules: string[];
  models: Record<string, number | null>;
  n_models: number;
  regime: string | null;
  split: string;
}

export interface MvEpisode {
  start: string;
  end: string;
  intervals: number;
  peak_score: number | null;
  mean_score: number | null;
  model_flag: boolean;
  rule_flags: string[];
  regimes: string[];
  top_contributors: MvContributor[];
  alarms: { alarm_code: string; source: string; severity: number | null; start: string }[];
  explained: boolean;
}

export interface MvAlarm {
  alarm_id: number;
  start: string;
  end: string;
  alarm_code: string;
  source: string;
  severity: number | null;
}

export interface MvContributors {
  features: (MvContributor & { count: number })[];
  rules: { flag: string; intervals: number }[];
  flagged_intervals: number;
}

export interface MvSignals {
  features: { key: string; label: string }[];
  points: Record<string, any>[];
}

export interface MvLiveResult {
  system_id: number;
  status: string;
  message?: string;
  model_run_id?: number;
  live_run_id?: number;
  rows?: number;
  flagged_intervals?: number;
  window_start?: string;
  window_end?: string;
  warnings?: string[];
}
