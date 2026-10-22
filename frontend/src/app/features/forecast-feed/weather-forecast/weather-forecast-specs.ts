import { ChartSpec, TimelineSpec } from '../../telemetry/graphs/chart-spec';
import { TableColumn } from '../../telemetry/table/table-column';

const BLUE = '#2f6fed';
const RED = '#d62828';
const ORANGE = '#e8830c';
const AMBER = '#f2b705';
const SLATE = '#5b6472';
const GREY = '#9aa1ab';
const GREEN = '#12a37f';
const VIOLET = '#7b5cd6';

/** x = the hour the forecast is for (valid_at). Forecast lines are dashed, measured weather solid. */
export const FORECAST_CHARTS: ChartSpec[] = [
  {
    id: 'temp',
    title: 'Temperature: Forecast vs Measured',
    yLabel: '°C',
    counters: [
      { key: 'temp_fc_min_c', label: 'temp_fc_min_c', color: ORANGE, role: 'bandMin' },
      { key: 'temp_fc_max_c', label: 'temp_fc_max_c', color: ORANGE, role: 'bandMax' },
      { key: 'temp_fc_c', label: 'temp_fc_c', color: ORANGE, dashed: true },
      { key: 'temp_actual_c', label: 'temp_actual_c', color: RED }
    ]
  },
  {
    id: 'ghi',
    title: 'Solar Irradiance (GHI): Forecast vs Measured',
    yLabel: 'W/m²',
    counters: [
      { key: 'ghi_actual_wm2', label: 'ghi_actual_wm2', color: AMBER, role: 'area' },
      { key: 'ghi_fc_min_wm2', label: 'ghi_fc_min_wm2', color: SLATE, role: 'bandMin' },
      { key: 'ghi_fc_max_wm2', label: 'ghi_fc_max_wm2', color: SLATE, role: 'bandMax' },
      { key: 'ghi_fc_wm2', label: 'ghi_fc_wm2', color: SLATE, dashed: true }
    ],
    y: { min: 0 }
  },
  {
    id: 'temp-error',
    title: 'Temperature Forecast Error (forecast − measured)',
    yLabel: '°C',
    counters: [{ key: 'temp_error_c', label: 'temp_error_c', color: RED, role: 'bar', negativeColor: BLUE }],
    refLines: [
      { label: 'MAE', ref: 'tempMae', color: GREY },
      { label: '−MAE', ref: 'tempMae', scale: -1, color: GREY }
    ]
  },
  {
    id: 'ghi-error',
    title: 'GHI Forecast Error (forecast − measured)',
    yLabel: 'W/m²',
    counters: [{ key: 'ghi_error_wm2', label: 'ghi_error_wm2', color: AMBER, role: 'bar', negativeColor: SLATE }],
    refLines: [
      { label: 'MAE (daylight)', ref: 'ghiMae', color: GREY },
      { label: '−MAE', ref: 'ghiMae', scale: -1, color: GREY }
    ]
  },
  {
    id: 'lead',
    title: 'Forecast Lead Time',
    yLabel: 'hours ahead',
    counters: [
      { key: 'lead_h', label: 'lead_h', color: VIOLET, stepped: true },
      { key: 'runs', label: 'runs covering the hour', color: GREEN, stepped: true, dashed: true }
    ],
    y: { min: 0 }
  }
];

export const FORECAST_TIMELINES: TimelineSpec[] = [
  {
    id: 'horizon',
    title: 'Forecast Horizon',
    laneLabel: 'Lead',
    colors: { 'LEAD_0-6H': GREEN, 'LEAD_6-24H': AMBER, 'LEAD_24H+': ORANGE }
  },
  {
    id: 'actuals',
    title: 'Measured Weather Available',
    laneLabel: 'Measured',
    colors: { MEASURED: BLUE, NO_MEASUREMENT: GREY }
  }
];

export const FORECAST_TABLE_COLUMNS: TableColumn[] = [
  { key: 'valid_at', label: 'Valid At', kind: 'timestamp', group: 'Forecast', locked: true },
  { key: 'issued_label', label: 'Issued At', kind: 'text', group: 'Forecast' },
  { key: 'lead_h', label: 'Lead (h)', kind: 'number', group: 'Forecast' },
  { key: 'station_code', label: 'Station', kind: 'text', group: 'Forecast' },
  { key: 'temp_c', label: 'Temp Forecast (°C)', kind: 'number', group: 'Temperature' },
  { key: 'actual_temp_c', label: 'Temp Measured (°C)', kind: 'number', group: 'Temperature' },
  { key: 'temp_error_c', label: 'Temp Error (°C)', kind: 'number', group: 'Temperature' },
  { key: 'ghi_wm2', label: 'GHI Forecast (W/m²)', kind: 'number', group: 'Irradiance' },
  { key: 'actual_ghi_wm2', label: 'GHI Measured (W/m²)', kind: 'number', group: 'Irradiance' },
  { key: 'ghi_error_wm2', label: 'GHI Error (W/m²)', kind: 'number', group: 'Irradiance' }
];

export const DEFAULT_FORECAST_COLUMN_KEYS: string[] = FORECAST_TABLE_COLUMNS.map((c) => c.key);
