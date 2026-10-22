/** Fault classification / diagnosis use case of the ML service (/fault-diag). */

export interface FdTrainRequest {
  run_name?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  leakage_mode: 'triage' | 'early';
  granularity: 'episode' | 'window';
  lookback_min: number;
  post_min: number;
  step_min: number;
  max_span_min: number;
  n_none: number;
  none_guard_h: number;
  families: string[];
  soft_pct: number;
  folds: number;
  train_frac: number;
  alpha: number;
  calibrate: boolean;
  alert_threshold: number;
  kappa: number;
  absent_penalty: number;
  none_prior: number;
  none_bias: number;
  unknown_penalty: number;
  mute_rate: number;
  prior: 'empirical' | 'uniform';
  algorithm: 'lightgbm' | 'xgboost';
  structure: 'flat' | 'hierarchical';
  n_estimators: number;
  learning_rate: number;
  max_depth: number;
  num_leaves: number;
  min_child_samples: number;
  class_weight_power: number;
  confirmed_boost: number;
  augment: boolean;
  augment_min: number;
  augment_noise: number;
  seed: number;
}

export interface FdClass {
  fault_code: string;
  fault_name: string;
  subsystem: string;
  category: string;
  severity: number | null;
  safety_critical: boolean;
  episodes: number;
  signatures: number;
}

export interface FdSystem {
  system_id: number;
  system_name: string;
  site_name: string | null;
  date_from: string;
  date_to: string;
  alarms: number;
  episodes: number;
}

export interface FdSignature {
  signature_id: number;
  fault_code: string;
  signal: string;
  kind: string;
  operator: string;
  threshold: number | null;
  unit: string | null;
  window_min: number;
  weight: number;
  unavailable: string | null;
}

export interface FdOptions {
  defaults: FdTrainRequest;
  systems: FdSystem[];
  classes: FdClass[];
  families: { key: string; label: string }[];
  episodes: {
    n: number; classes: number; date_from: string | null; date_to: string | null; filed_systems: number[];
    telemetry_systems: number[]; confirmed_by_repair: number;
  };
  signatures: FdSignature[];
  model_versions: string[];
}

export interface FdPerClass {
  fault_code: string;
  subsystem: string;
  support: number;
  precision: number;
  recall: number;
  f1: number;
  top3_recall: number;
  is_safety_critical: boolean;
}

export interface FdCard {
  n: number;
  accuracy: number;
  macro_f1: number;
  top3_accuracy: number;
  subsystem_accuracy: number;
  none_fpr: number | null;
  fault_miss_rate: number | null;
  safety_recall: number | null;
  cost_weighted_error: number;
  log_loss: number;
  ece: number;
  ece_uncalibrated?: number;
  per_class: FdPerClass[];
  confusion: { labels: string[]; matrix: number[][] };
}

export interface FdCards {
  engine: FdCard;
  ml: FdCard;
  fused: FdCard;
}

export interface FdImportance {
  feature: string;
  label: string;
  family: string;
  importance: number;
}

export interface FdSigHealth {
  signature_id: number;
  fault_code: string;
  signal: string;
  operator: string;
  threshold: number | null;
  healthy_match_rate: number;
  muted: boolean;
}

export interface FdTtd {
  episode_id: string;
  fault_code: string;
  alarm_ttd_min: number;
  model_ttd_min?: number;
  lead_vs_alarm_min?: number;
}

export interface FdSummary {
  n_examples: number;
  n_episodes: number;
  n_none: number;
  n_features: number;
  n_classes_trained: number;
  folds: number;
  temperature: number;
  class_support: Record<string, number>;
  telemetry_systems: number[];
  families: Record<string, number>;
  family_importance: Record<string, number>;
  signature_coverage: Record<string, string>;
  signature_health: FdSigHealth[];
  time_to_detect: FdTtd[];
  ttd_summary: { episodes_detected: number; episodes: number; median_lead_vs_alarm_min: number | null } | null;
}

export interface FdMetrics {
  oof: FdCards;
  episode_level: FdCard | null;
  forward: (FdCards & { split_at: string; n_train: number; n_test: number; unseen_classes: string[] }) | null;
  importance: FdImportance[];
  per_class_fused: Record<string, FdPerClass>;
}

export interface FdRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  date_from: string | null;
  date_to: string | null;
  params: FdTrainRequest;
  summary: FdSummary | null;
  metrics?: FdMetrics | null;
  warnings: string[];
  artifact_path: string | null;
  published_at: string | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  macro_f1?: number | null;
  top3_accuracy?: number | null;
  accuracy?: number | null;
}

export interface FdTop {
  fault_code: string;
  p: number;
}

export interface FdContribution {
  feature: string;
  label: string;
  family: string;
  value: number | null;
  contribution: number;
}

export interface FdEvidence {
  signature_id: number;
  fault_code: string;
  signal: string;
  kind: string;
  operator: string;
  threshold: number | null;
  unit: string | null;
  weight: number;
  value: number | null;
  match: number | null;
}

export interface FdExample {
  example_key: string;
  group_key: string;
  kind: 'episode' | 'none';
  episode_id: string | null;
  system_id: number;
  window_start: string;
  window_end: string;
  label: string;
  predicted: string;
  probability: number;
  correct: boolean;
  fold: number;
  top3: FdTop[];
  asset_code: string | null;
  detected_ts: string | null;
  onset_ts: string | null;
  severity_level: number | null;
  root_cause_confirmed: string | null;
}

export interface FdExampleDetail extends Omit<FdExample, 'top3'> {
  detail: { top3: FdTop[]; top3_ml: FdTop[]; top3_engine: FdTop[]; contributions: FdContribution[]; evidence: FdEvidence[] };
  episode?: {
    episode_id: string; fault_code: string; asset_type: string | null; asset_code: string | null; onset_ts: string;
    detected_ts: string; resolved_ts: string | null; severity_level: number | null; label_confidence: number | null;
    root_cause_confirmed: string | null; operating_context: string | null; alarms: string[]; primary_alarms: string[];
    component: string | null; fault_confirmed: boolean | null; telemetry_system_id: number;
  };
}

export interface FdCompare {
  run: FdCards;
  episode_level: FdCard | null;
  logged: { model_version: string; card: FdCard } | null;
  scoring: { model_version: string; n: number; n_correct: number; accuracy: number; avg_confidence: number }[];
}

export interface FdScanResult {
  windows: number;
  candidates: number;
  from: string;
  to: string;
  by_fault: Record<string, number>;
  flagged_windows: number;
}

export interface FdScanPoint {
  ts: string;
  predicted: string;
  probability: number;
  p_none: number;
  top3: FdTop[];
  alarms: string[];
}

export interface FdCandidate {
  candidate_id: number;
  run_id: number;
  system_id: number;
  system_name: string | null;
  first_ts: string;
  peak_ts: string;
  last_ts: string;
  fault_code: string;
  fault_name: string;
  subsystem: string;
  is_safety_critical: boolean;
  default_severity: number | null;
  recommended_action: string | null;
  probability: number;
  n_windows: number;
  top3: FdTop[];
  contributions: FdContribution[];
  evidence: FdEvidence[];
  alarms: string[];
  asset_code: string | null;
  episode_id: string | null;
  actual_fault_code: string | null;
  prediction_id: number | null;
  status: 'NEW' | 'CONFIRMED' | 'REJECTED';
}

export interface FdOverview {
  episodes: number;
  classes: number;
  catalog_classes: number;
  safety_critical: number;
  ongoing: number;
  downtime_min: number;
  energy_lost_kwh: number;
  repair_cost_usd: number;
  work_orders: number;
  mttr_h: number | null;
  mean_lead_min: number | null;
  median_lead_min: number | null;
  confirmed_by_repair: number;
  date_from: string | null;
  date_to: string | null;
  by_subsystem: { subsystem: string; episodes: number; classes: number; downtime_min: number; energy_lost_kwh: number; safety_critical: number }[];
  daily: { days: string[]; series: Record<string, number[]> };
}

export interface FdParetoItem {
  key: string;
  label: string;
  value: number;
  share: number;
  cum_share: number;
  vital_few: boolean;
  episodes: number;
  subsystem: string | null;
  safety_critical: boolean;
  faults: string[];
}

export interface FdPareto {
  measure: string;
  measure_label: string;
  unit: string;
  group_by: string;
  group_label: string;
  total: number;
  cutoff: number;
  items: FdParetoItem[];
  vital_few: number;
  n_groups: number;
}

export interface FdCause {
  bone: string;
  cause: string;
  episodes: number;
  sources: string[];
  faults: string[];
  downtime_min: number;
  energy_lost_kwh: number;
}

export interface FdFishbone {
  effect: string;
  title: string;
  subtitle: string;
  stats: { episodes: number; downtime_min: number; energy_lost_kwh: number; repair_cost_usd: number; classes_seen: number; classes: number; mean_lead_min: number | null };
  bones: { bone: string; hint: string; episodes: number; causes: FdCause[] }[];
  symptoms: { fault_code: string; signal: string; kind: string | null; operator: string; threshold: number | null; unit: string | null; weight: number; available: boolean }[];
  actions: { fault_code: string; fault_name: string; action: string | null; symptoms: string | null; standard: string | null; safety_critical: boolean }[];
  model: { run_id: number; features: { label: string; mean_abs: number }[]; n: number; recall: number | null } | null;
}

export interface FdEffect {
  key: string;
  label: string;
  episodes: number;
  subsystem?: string;
}
