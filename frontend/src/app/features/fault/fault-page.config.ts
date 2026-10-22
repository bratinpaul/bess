import { FaultEnumSource, FaultLookupSource, FaultRow } from '../../core/models/fault.model';
import { TableColumn } from '../telemetry/table/table-column';

export type FaultFieldKind = 'number' | 'int' | 'text' | 'datetime' | 'select' | 'bool';

/** One input of the add / edit dialog. `isKey` fields identify the row: set on add, read-only on edit. */
export interface FaultFieldDef {
  key: string;
  label: string;
  kind: FaultFieldKind;
  required?: boolean;
  isKey?: boolean;
  from?: FaultLookupSource;
  options?: FaultEnumSource;
  step?: string;
  hint?: string;
  wide?: boolean;
}

export interface FaultFilterDef {
  param: string;
  label: string;
  kind: 'select' | 'bool';
  from?: FaultLookupSource;
  options?: FaultEnumSource;
}

export interface FaultPageConfig {
  title: string;
  subtitle: string;
  endpoint: string;
  /** fields joined (in order) as the row's path key */
  keyFields: string[];
  columns: TableColumn[];
  defaultColumns: string[];
  /** ISO timestamp fields shown as plant-time labels in `<field>_label` columns */
  tsFields: string[];
  /** boolean fields shown as Yes / No in `<field>_label` columns */
  boolFields: string[];
  fields: FaultFieldDef[];
  filters: FaultFilterDef[];
  /** label of the date-range filter; none = the table has no date column */
  dateLabel?: string;
  searchLabel?: string;
  defaultOrder: 'asc' | 'desc';
  pageSizes: number[];
  fileName: string;
  uploadColumns: string;
  uploadNote: string;
  noun: string;
  deleteNote?: string;
  describe: (row: FaultRow, label: (iso: unknown) => string) => string;
  defaults?: Record<string, unknown>;
}

const col = (key: string, label: string, group: string, kind: 'text' | 'number' = 'text', locked = false): TableColumn =>
  ({ key, label, kind, group, locked });

const SYSTEM_NOTE = 'system_code is the battery system name (e.g. EESL-BESS-S02); the pack\'s legacy BESS-01 is mapped to EESL-BESS-S02.';

export const FAULT_PAGES: Record<string, FaultPageConfig> = {
  'fault-catalog': {
    title: 'Fault Catalog',
    subtitle: 'The labelled fault classes - the taxonomy the fault classifier predicts - with subsystem, failure mode, default severity, typical cause, symptoms and recommended action',
    endpoint: 'fault-catalog',
    keyFields: ['fault_code'],
    columns: [
      col('fault_code', 'Fault Code', 'Fault', 'text', true),
      col('fault_name', 'Name', 'Fault'),
      col('subsystem', 'Subsystem', 'Fault'),
      col('category', 'Category', 'Fault'),
      col('failure_mode', 'Failure Mode', 'Fault'),
      col('default_severity', 'Default Severity', 'Risk', 'number'),
      col('is_safety_critical_label', 'Safety Critical', 'Risk'),
      col('typical_root_cause', 'Typical Root Cause', 'Guidance'),
      col('typical_symptoms', 'Typical Symptoms', 'Guidance'),
      col('recommended_action', 'Recommended Action', 'Guidance'),
      col('standard_ref', 'Standard', 'Guidance')
    ],
    defaultColumns: ['fault_code', 'fault_name', 'subsystem', 'category', 'failure_mode', 'default_severity', 'is_safety_critical_label', 'recommended_action'],
    tsFields: [],
    boolFields: ['is_safety_critical'],
    fields: [
      { key: 'fault_code', label: 'Fault code', kind: 'text', required: true, isKey: true },
      { key: 'fault_name', label: 'Name', kind: 'text', required: true, wide: true },
      { key: 'subsystem', label: 'Subsystem', kind: 'select', options: 'subsystems', required: true },
      { key: 'category', label: 'Category', kind: 'text', required: true },
      { key: 'failure_mode', label: 'Failure mode', kind: 'text', wide: true },
      { key: 'default_severity', label: 'Default severity (0–3)', kind: 'select', options: 'severities' },
      { key: 'is_safety_critical', label: 'Safety critical', kind: 'bool' },
      { key: 'typical_root_cause', label: 'Typical root cause', kind: 'text', wide: true },
      { key: 'typical_symptoms', label: 'Typical symptoms', kind: 'text', wide: true },
      { key: 'recommended_action', label: 'Recommended action', kind: 'text', wide: true },
      { key: 'standard_ref', label: 'Standard reference', kind: 'text' }
    ],
    filters: [
      { param: 'subsystem', label: 'Subsystem', kind: 'select', options: 'subsystems' },
      { param: 'category', label: 'Category', kind: 'select', from: 'categories' }
    ],
    searchLabel: 'Code / name / mode',
    defaultOrder: 'asc',
    pageSizes: [25, 50, 100],
    fileName: 'fault_catalog.csv',
    uploadColumns: 'fault_code, fault_name, subsystem, category, failure_mode, default_severity, is_safety_critical, typical_root_cause, typical_symptoms, recommended_action, standard_ref',
    uploadNote: 'An existing fault_code is updated. Checks: subsystem BMS / PCS / EMS / HVAC / PLANT, severity 0–3, true / false flags. Load the catalog before signatures, episodes and predictions that use its codes.',
    noun: 'fault class',
    deleteNote: 'Its signatures are deleted with it; it cannot be deleted while episodes or predictions use it.',
    describe: (r) => `${r['fault_code']} (${r['fault_name']})`,
    defaults: { subsystem: 'BMS', default_severity: 1, is_safety_critical: false }
  },
  'fault-signatures': {
    title: 'Fault Signature',
    subtitle: 'The diagnostic signature library - which symptom (alarm, telemetry or engineered feature) beyond which threshold, over which window and with which weight, points to which fault',
    endpoint: 'fault-signatures',
    keyFields: ['signature_id'],
    columns: [
      col('signature_id', 'Id', 'Signature', 'number', true),
      col('fault_code', 'Fault Code', 'Signature'),
      col('fault_name', 'Fault', 'Signature'),
      col('fault_subsystem', 'Subsystem', 'Signature'),
      col('signal', 'Signal', 'Rule'),
      col('signal_kind', 'Signal Kind', 'Rule'),
      col('operator', 'Operator', 'Rule'),
      col('threshold', 'Threshold', 'Rule', 'number'),
      col('unit', 'Unit', 'Rule'),
      col('window_min', 'Window (min)', 'Rule', 'number'),
      col('weight', 'Weight', 'Rule', 'number'),
      col('note', 'Note', 'Rule')
    ],
    defaultColumns: ['signature_id', 'fault_code', 'signal', 'signal_kind', 'operator', 'threshold', 'unit', 'window_min', 'weight', 'note'],
    tsFields: [],
    boolFields: [],
    fields: [
      { key: 'fault_code', label: 'Fault', kind: 'select', from: 'faults', required: true },
      { key: 'signal', label: 'Signal', kind: 'text', required: true, hint: 'a telemetry column, an engineered feature or an alarm code' },
      { key: 'signal_kind', label: 'Signal kind', kind: 'select', options: 'signal_kinds' },
      { key: 'operator', label: 'Operator', kind: 'select', options: 'operators' },
      { key: 'threshold', label: 'Threshold', kind: 'number', hint: 'needed for > < >= <= == !=' },
      { key: 'unit', label: 'Unit', kind: 'text' },
      { key: 'window_min', label: 'Window (min)', kind: 'int' },
      { key: 'weight', label: 'Weight', kind: 'number', step: '0.1' },
      { key: 'note', label: 'Note', kind: 'text', wide: true }
    ],
    filters: [
      { param: 'fault_code', label: 'Fault', kind: 'select', from: 'faults' },
      { param: 'signal_kind', label: 'Signal kind', kind: 'select', options: 'signal_kinds' }
    ],
    searchLabel: 'Signal / note',
    defaultOrder: 'asc',
    pageSizes: [25, 50, 100],
    fileName: 'fault_signature.csv',
    uploadColumns: 'fault_code, signal, signal_kind, operator, threshold, unit, window_min, weight, note',
    uploadNote: 'One rule per fault and signal: an existing (fault_code, signal) is updated. Checks: a known fault code, signal kind ALARM / TELEMETRY / FEATURE, a known operator and a threshold for the comparison operators.',
    noun: 'signature',
    describe: (r) => `${r['fault_code']} · ${r['signal']}`,
    defaults: { signal_kind: 'FEATURE', operator: '>', weight: 1 }
  },
  'fault-episodes': {
    title: 'Fault Episode',
    subtitle: 'Engineer-confirmed fault instances - the ground-truth labels: which asset, which fault, when it began, was detected and resolved, how it was found, its impact and the confirmed root cause',
    endpoint: 'fault-episodes',
    keyFields: ['episode_id'],
    columns: [
      col('episode_id', 'Episode', 'Episode', 'text', true),
      col('system_code', 'System', 'Episode'),
      col('asset_type', 'Asset Type', 'Episode'),
      col('asset_code', 'Asset', 'Episode'),
      col('fault_code', 'Fault Code', 'Fault'),
      col('fault_name', 'Fault', 'Fault'),
      col('fault_subsystem', 'Subsystem', 'Fault'),
      col('severity_level', 'Severity', 'Fault', 'number'),
      col('onset_ts_label', 'Onset', 'Timeline'),
      col('detected_ts_label', 'Detected', 'Timeline'),
      col('resolved_ts_label', 'Resolved', 'Timeline'),
      col('is_ongoing_label', 'Ongoing', 'Timeline'),
      col('detection_method', 'Detection', 'Label'),
      col('confirmed_by', 'Confirmed By', 'Label'),
      col('label_confidence', 'Confidence', 'Label', 'number'),
      col('root_cause_confirmed', 'Root Cause', 'Label'),
      col('operating_context', 'Operating Context', 'Label'),
      col('downtime_min', 'Downtime (min)', 'Impact', 'number'),
      col('energy_lost_kwh', 'Energy Lost (kWh)', 'Impact', 'number'),
      col('note', 'Note', 'Label')
    ],
    defaultColumns: ['episode_id', 'system_code', 'asset_type', 'asset_code', 'fault_code', 'severity_level', 'detected_ts_label', 'resolved_ts_label', 'detection_method', 'label_confidence', 'root_cause_confirmed'],
    tsFields: ['onset_ts', 'detected_ts', 'resolved_ts'],
    boolFields: ['is_ongoing'],
    fields: [
      { key: 'episode_id', label: 'Episode id', kind: 'text', required: true, isKey: true },
      { key: 'system_id', label: 'System', kind: 'select', from: 'systems', required: true },
      { key: 'asset_type', label: 'Asset type', kind: 'select', options: 'asset_types' },
      { key: 'asset_code', label: 'Asset code', kind: 'text' },
      { key: 'fault_code', label: 'Fault', kind: 'select', from: 'faults', required: true },
      { key: 'severity_level', label: 'Severity (0–3)', kind: 'select', options: 'severities' },
      { key: 'onset_ts', label: 'Onset', kind: 'datetime' },
      { key: 'detected_ts', label: 'Detected', kind: 'datetime', required: true },
      { key: 'resolved_ts', label: 'Resolved', kind: 'datetime', hint: 'blank = still ongoing' },
      { key: 'is_ongoing', label: 'Ongoing', kind: 'bool' },
      { key: 'detection_method', label: 'Detection method', kind: 'select', options: 'detection_methods' },
      { key: 'confirmed_by', label: 'Confirmed by', kind: 'text' },
      { key: 'label_confidence', label: 'Label confidence (0–1)', kind: 'number', step: '0.01' },
      { key: 'root_cause_confirmed', label: 'Confirmed root cause', kind: 'text', wide: true },
      { key: 'operating_context', label: 'Operating context', kind: 'text', wide: true },
      { key: 'downtime_min', label: 'Downtime (min)', kind: 'number' },
      { key: 'energy_lost_kwh', label: 'Energy lost (kWh)', kind: 'number' },
      { key: 'note', label: 'Note', kind: 'text', wide: true }
    ],
    filters: [
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'fault_code', label: 'Fault', kind: 'select', from: 'faults' },
      { param: 'asset_type', label: 'Asset type', kind: 'select', options: 'asset_types' },
      { param: 'severity_level', label: 'Severity', kind: 'select', options: 'severities' }
    ],
    dateLabel: 'Detected',
    searchLabel: 'Episode / asset / cause',
    defaultOrder: 'desc',
    pageSizes: [25, 50, 100],
    fileName: 'fault_episode.csv',
    uploadColumns: 'episode_id, system_code, asset_type, asset_code, fault_code, onset_ts, detected_ts, resolved_ts, detection_method, severity_level, confirmed_by, label_confidence, root_cause_confirmed, operating_context, downtime_min, energy_lost_kwh, is_ongoing, note',
    uploadNote: `An existing episode_id is updated. ${SYSTEM_NOTE} Checks: a known fault code, resolved after detected, detection ALARM / MODEL / INSPECTION / MAINTENANCE / OPERATOR, severity 0–3, confidence 0–1. Load episodes before their alarm links, maintenance actions and predictions.`,
    noun: 'episode',
    deleteNote: 'Its alarm links are deleted with it; maintenance actions and predictions keep their rows but lose the link.',
    describe: (r, label) => `${r['episode_id']} (${r['fault_code']}, detected ${label(r['detected_ts'])})`,
    defaults: { detection_method: 'ALARM', severity_level: 1, asset_type: 'System', is_ongoing: false }
  },
  'fault-alarm-links': {
    title: 'Fault–Alarm Link',
    subtitle: 'Which alarms were symptoms of which confirmed fault episode, and their role - many alarms can point to one fault',
    endpoint: 'fault-alarm-links',
    keyFields: ['episode_id', 'alarm_id'],
    columns: [
      col('episode_id', 'Episode', 'Link', 'text', true),
      col('alarm_id', 'Alarm', 'Link', 'text', true),
      col('role', 'Role', 'Link')
    ],
    defaultColumns: ['episode_id', 'alarm_id', 'role'],
    tsFields: [],
    boolFields: [],
    fields: [
      { key: 'episode_id', label: 'Episode', kind: 'select', from: 'episodes', required: true, isKey: true },
      { key: 'alarm_id', label: 'Alarm id', kind: 'text', required: true, isKey: true, hint: 'an alarm of Telemetry → Alarm events, e.g. ALM-00009' },
      { key: 'role', label: 'Role', kind: 'select', options: 'roles' }
    ],
    filters: [
      { param: 'episode_id', label: 'Episode', kind: 'select', from: 'episodes' },
      { param: 'role', label: 'Role', kind: 'select', options: 'roles' }
    ],
    searchLabel: 'Alarm id',
    defaultOrder: 'asc',
    pageSizes: [25, 50, 100],
    fileName: 'fault_alarm_link.csv',
    uploadColumns: 'episode_id, alarm_id, role',
    uploadNote: 'An existing (episode_id, alarm_id) is updated. Checks: a known episode (load episodes first), a known alarm in the alarm events, role PRIMARY / CONTRIBUTING / CONSEQUENTIAL.',
    noun: 'link',
    describe: (r) => `${r['alarm_id']} → ${r['episode_id']}`,
    defaults: { role: 'PRIMARY' }
  },
  'maintenance-actions': {
    title: 'Maintenance Action',
    subtitle: 'Work orders against fault episodes - the component, parts, labour and cost, who did it, and whether the fault was confirmed and the fix effective',
    endpoint: 'maintenance-actions',
    keyFields: ['action_id'],
    columns: [
      col('action_id', 'Work Order', 'Action', 'text', true),
      col('episode_id', 'Episode', 'Action'),
      col('system_code', 'System', 'Action'),
      col('fault_code', 'Fault Code', 'Action'),
      col('action_type', 'Action', 'Action'),
      col('component', 'Component', 'Repair'),
      col('part_number', 'Part Number', 'Repair'),
      col('part_replaced_label', 'Part Replaced', 'Repair'),
      col('labor_hours', 'Labour (h)', 'Cost', 'number'),
      col('cost_usd', 'Cost (USD)', 'Cost', 'number'),
      col('performed_by', 'Performed By', 'Action'),
      col('performed_at_label', 'Performed At', 'Action'),
      col('resolution', 'Resolution', 'Outcome'),
      col('fault_confirmed_label', 'Fault Confirmed', 'Outcome'),
      col('effective_label', 'Effective', 'Outcome'),
      col('note', 'Note', 'Outcome')
    ],
    defaultColumns: ['action_id', 'episode_id', 'system_code', 'action_type', 'component', 'part_replaced_label', 'labor_hours', 'cost_usd', 'performed_by', 'performed_at_label', 'effective_label'],
    tsFields: ['performed_at'],
    boolFields: ['part_replaced', 'fault_confirmed', 'effective'],
    fields: [
      { key: 'action_id', label: 'Work order id', kind: 'text', required: true, isKey: true },
      { key: 'episode_id', label: 'Episode', kind: 'select', from: 'episodes' },
      { key: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { key: 'action_type', label: 'Action type', kind: 'select', options: 'action_types' },
      { key: 'component', label: 'Component', kind: 'text' },
      { key: 'part_number', label: 'Part number', kind: 'text' },
      { key: 'part_replaced', label: 'Part replaced', kind: 'bool' },
      { key: 'labor_hours', label: 'Labour (h)', kind: 'number', step: '0.1' },
      { key: 'cost_usd', label: 'Cost (USD)', kind: 'number', step: '0.01' },
      { key: 'performed_by', label: 'Performed by', kind: 'text' },
      { key: 'performed_at', label: 'Performed at', kind: 'datetime' },
      { key: 'resolution', label: 'Resolution', kind: 'text', wide: true },
      { key: 'fault_confirmed', label: 'Fault confirmed', kind: 'bool' },
      { key: 'effective', label: 'Effective', kind: 'bool' },
      { key: 'note', label: 'Note', kind: 'text', wide: true }
    ],
    filters: [
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'action_type', label: 'Action type', kind: 'select', options: 'action_types' },
      { param: 'episode_id', label: 'Episode', kind: 'select', from: 'episodes' }
    ],
    dateLabel: 'Performed',
    searchLabel: 'Work order / component / tech',
    defaultOrder: 'desc',
    pageSizes: [25, 50, 100],
    fileName: 'maintenance_action.csv',
    uploadColumns: 'action_id, episode_id, system_code, action_type, component, part_number, part_replaced, labor_hours, cost_usd, performed_by, performed_at, resolution, fault_confirmed, effective, note',
    uploadNote: `An existing action_id is updated. ${SYSTEM_NOTE} Checks: a known episode when given (load episodes first), action INSPECT / REPAIR / REPLACE / RESET / CALIBRATE / CLEAN / FIRMWARE / NO_ACTION, non-negative hours and cost, true / false flags.`,
    noun: 'work order',
    describe: (r, label) => `${r['action_id']} (${r['action_type'] ?? 'action'}, ${label(r['performed_at'])})`,
    defaults: { action_type: 'INSPECT', part_replaced: false, fault_confirmed: true, effective: true }
  },
  'fault-predictions': {
    title: 'Fault Prediction',
    subtitle: 'The fault classifier\'s scoring log - predicted fault, probability and top-3 per asset and time, against the confirmed episode label',
    endpoint: 'fault-predictions',
    keyFields: ['prediction_id'],
    columns: [
      col('prediction_id', 'Id', 'Prediction', 'number', true),
      col('model_version', 'Model', 'Prediction'),
      col('system_code', 'System', 'Prediction'),
      col('asset_type', 'Asset Type', 'Prediction'),
      col('asset_code', 'Asset', 'Prediction'),
      col('predicted_at_label', 'Predicted At', 'Prediction'),
      col('predicted_fault_code', 'Predicted Fault', 'Score'),
      col('fault_name', 'Predicted Fault Name', 'Score'),
      col('probability', 'Probability', 'Score', 'number'),
      col('top3', 'Top 3', 'Score'),
      col('episode_id', 'Episode', 'Label'),
      col('actual_fault_code', 'Actual Fault', 'Label'),
      col('is_correct_label', 'Correct', 'Label'),
      col('note', 'Note', 'Label')
    ],
    defaultColumns: ['prediction_id', 'model_version', 'asset_type', 'asset_code', 'predicted_at_label', 'predicted_fault_code', 'probability', 'episode_id', 'actual_fault_code', 'is_correct_label'],
    tsFields: ['predicted_at'],
    boolFields: ['is_correct'],
    fields: [
      { key: 'model_version', label: 'Model version', kind: 'text', required: true },
      { key: 'system_id', label: 'System', kind: 'select', from: 'systems', required: true },
      { key: 'asset_type', label: 'Asset type', kind: 'select', options: 'asset_types' },
      { key: 'asset_code', label: 'Asset code', kind: 'text' },
      { key: 'predicted_at', label: 'Predicted at', kind: 'datetime', required: true },
      { key: 'predicted_fault_code', label: 'Predicted fault', kind: 'select', from: 'faults', required: true },
      { key: 'probability', label: 'Probability (0–1)', kind: 'number', step: '0.0001' },
      { key: 'top3', label: 'Top 3 (code:p|code:p|code:p)', kind: 'text', wide: true },
      { key: 'episode_id', label: 'Episode', kind: 'select', from: 'episodes' },
      { key: 'actual_fault_code', label: 'Actual fault', kind: 'select', from: 'faults' },
      { key: 'is_correct', label: 'Correct', kind: 'bool' },
      { key: 'note', label: 'Note', kind: 'text', wide: true }
    ],
    filters: [
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'model_version', label: 'Model', kind: 'select', from: 'model_versions' },
      { param: 'predicted_fault_code', label: 'Predicted fault', kind: 'select', from: 'faults' },
      { param: 'is_correct', label: 'Correct', kind: 'bool' }
    ],
    dateLabel: 'Predicted',
    searchLabel: 'Asset / top 3',
    defaultOrder: 'desc',
    pageSizes: [25, 50, 100],
    fileName: 'fault_prediction.csv',
    uploadColumns: 'model_version, system_code, asset_type, asset_code, predicted_at, predicted_fault_code, probability, top3, episode_id, actual_fault_code, is_correct, note',
    uploadNote: `One score per model, system, asset and time: an existing one is updated. ${SYSTEM_NOTE} Checks: known predicted / actual fault codes, a known episode when given (load episodes first), probability 0–1; a warning when is_correct disagrees with predicted vs actual.`,
    noun: 'prediction',
    describe: (r, label) => `${r['model_version']} · ${r['asset_code']} at ${label(r['predicted_at'])}`,
    defaults: { model_version: 'xgb-fault-v1', asset_type: 'System' }
  }
};
