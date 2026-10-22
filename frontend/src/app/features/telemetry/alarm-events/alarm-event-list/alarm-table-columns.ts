import { TableColumn } from '../../table/table-column';

/** Columns the alarm table can show, in table order; the column selector lists them by group. */
export const ALARM_TABLE_COLUMNS: TableColumn[] = [
  // the columns the table has always shown
  { key: 'alarm_id', label: 'Alarm ID', kind: 'text', group: 'Alarm', locked: true },
  { key: 'start_time', label: 'Start', kind: 'timestamp', group: 'Timing' },
  { key: 'duration', label: 'Duration', kind: 'text', group: 'Timing' },
  { key: 'source', label: 'Source', kind: 'text', group: 'Alarm' },
  { key: 'alarm', label: 'Alarm', kind: 'text', group: 'Alarm' },
  { key: 'severity', label: 'Severity', kind: 'text', group: 'Alarm' },
  { key: 'asset', label: 'Asset', kind: 'text', group: 'Asset' },
  { key: 'trigger_threshold', label: 'Trigger / Threshold', kind: 'number', group: 'Measurement' },
  { key: 'acknowledged', label: 'Acknowledged', kind: 'text', group: 'Acknowledgement' },

  // extra columns
  { key: 'end_time', label: 'Cleared', kind: 'timestamp', group: 'Timing' },
  { key: 'status', label: 'Status', kind: 'text', group: 'Timing' },
  { key: 'start_date', label: 'Start Date', kind: 'text', group: 'Timing' },
  { key: 'alarm_type', label: 'Alarm Type', kind: 'text', group: 'Alarm' },
  { key: 'probable_cause', label: 'Probable Cause', kind: 'text', group: 'Alarm' },
  { key: 'system_name', label: 'Battery System', kind: 'text', group: 'Asset' },
  { key: 'trigger_value', label: 'Trigger Value', kind: 'number', group: 'Measurement' },
  { key: 'threshold_value', label: 'Threshold', kind: 'number', group: 'Measurement' },
  { key: 'unit', label: 'Unit', kind: 'text', group: 'Measurement' },
  { key: 'minutes_to_ack', label: 'Time to Acknowledge', kind: 'number', group: 'Acknowledgement' },
  { key: 'created_at', label: 'Recorded', kind: 'timestamp', group: 'Record' },
  { key: 'updated_at', label: 'Last Updated', kind: 'timestamp', group: 'Record' }
];

/** What the table showed before the column selector existed. */
export const ALARM_DEFAULT_COLUMN_KEYS = [
  'alarm_id', 'start_time', 'duration', 'source', 'alarm', 'severity', 'asset', 'trigger_threshold', 'acknowledged'
];
