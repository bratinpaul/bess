export interface SystemTelemetry {
  system_id: number;
  ts: string;
  system_name: string | null;
  mode_code: string | null;
  soc_bms_pct: number | null;
  soh_pct: number | null;
  pack_voltage_v: number | null;
  pack_current_a: number | null;
  power_kw: number | null;
  c_rate: number | null;
  cell_v_avg_v: number | null;
  cell_v_min_v: number | null;
  cell_v_max_v: number | null;
  cell_v_delta_mv: number | null;
  cell_temp_avg_c: number | null;
  cell_temp_min_c: number | null;
  cell_temp_max_c: number | null;
  coolant_temp_c: number | null;
  ambient_temp_c: number | null;
  insulation_res_kohm: number | null;
  avail_charge_kw: number | null;
  avail_discharge_kw: number | null;
  cum_charge_kwh: number | null;
  cum_discharge_kwh: number | null;
  equiv_full_cycles: number | null;
  contactor_state: string | null;
  alarm_level: number | null;
  measured_current_a: number | null;
  current_sensor_offset_a: number | null;
  soc_coulomb_pct: number | null;
  soc_battery_telemetry_pct: number | null;
  usable_capacity_ah: number | null;
  coulombic_efficiency: number | null;
  at_rest: boolean | null;
  rest_duration_min: number | null;
  ocv_rested_v: number | null;
}

export interface SystemTelemetryCreateInput {
  system_id: number;
  ts: string;
  mode_code?: string | null;
  soc_bms_pct?: number | null;
  soh_pct?: number | null;
  pack_voltage_v?: number | null;
  pack_current_a?: number | null;
  power_kw?: number | null;
  c_rate?: number | null;
  cell_v_avg_v?: number | null;
  cell_v_min_v?: number | null;
  cell_v_max_v?: number | null;
  cell_v_delta_mv?: number | null;
  cell_temp_avg_c?: number | null;
  cell_temp_min_c?: number | null;
  cell_temp_max_c?: number | null;
  coolant_temp_c?: number | null;
  ambient_temp_c?: number | null;
  insulation_res_kohm?: number | null;
  avail_charge_kw?: number | null;
  avail_discharge_kw?: number | null;
  cum_charge_kwh?: number | null;
  cum_discharge_kwh?: number | null;
  equiv_full_cycles?: number | null;
  contactor_state?: string | null;
  alarm_level?: number | null;
  measured_current_a?: number | null;
  current_sensor_offset_a?: number | null;
  soc_coulomb_pct?: number | null;
  soc_battery_telemetry_pct?: number | null;
  usable_capacity_ah?: number | null;
  coulombic_efficiency?: number | null;
  at_rest?: boolean | null;
  rest_duration_min?: number | null;
  ocv_rested_v?: number | null;
}

export interface SystemTelemetryPage {
  items: SystemTelemetry[];
  total: number;
  page: number;
  page_size: number;
}

export interface TelemetryLookups {
  modes: string[];
  contactor_states: string[];
}

export interface BulkTelemetryRowError {
  row: number;
  errors: string[];
}

export interface BulkTelemetryResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: BulkTelemetryRowError[];
}

export interface TelemetrySeriesPoint {
  ts: string;
  soc_bms_pct: number | null;
  soh_pct: number | null;
  pack_voltage_v: number | null;
  pack_current_a: number | null;
  power_kw: number | null;
  c_rate: number | null;
  cell_v_avg_v: number | null;
  cell_v_min_v: number | null;
  cell_v_max_v: number | null;
  cell_v_delta_mv: number | null;
  cell_temp_avg_c: number | null;
  cell_temp_min_c: number | null;
  cell_temp_max_c: number | null;
  coolant_temp_c: number | null;
  ambient_temp_c: number | null;
  insulation_res_kohm: number | null;
  avail_charge_kw: number | null;
  avail_discharge_kw: number | null;
  cum_charge_kwh: number | null;
  cum_discharge_kwh: number | null;
  charge_kwh_step: number | null;
  discharge_kwh_step: number | null;
  equiv_full_cycles: number | null;
  measured_current_a: number | null;
  current_sensor_offset_a: number | null;
  soc_coulomb_pct: number | null;
  soc_battery_telemetry_pct: number | null;
  usable_capacity_ah: number | null;
  coulombic_efficiency: number | null;
  rest_duration_min: number | null;
  ocv_rested_v: number | null;
}

export type TelemetrySeriesKey = Exclude<keyof TelemetrySeriesPoint, 'ts'>;

export interface StateSegment {
  state: string | null;
  start: string;
  end: string;
}

export interface SystemTelemetrySeries {
  system_id: number;
  system_name: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  points: TelemetrySeriesPoint[];
  contactor_segments: StateSegment[];
  contactor_states: string[];
  rest_segments: StateSegment[];
}
