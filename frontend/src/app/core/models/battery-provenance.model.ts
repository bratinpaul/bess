/** RUL battery provenance (battery_master.battery_provenance): cell provenance, batch and BOL baseline per fleet system. */

export interface BatteryProvenanceValues {
  manufacturer: string | null;
  cell_model: string | null;
  chemistry: string;
  batch_lot: string | null;
  cell_format: string | null;
  build_date: string | null;
  nameplate_kwh: number | null;
  bol_capacity_kwh: number | null;
  bol_resistance_mohm: number | null;
  usage_cycles_per_day: number | null;
  climate_avg_temp_c: number | null;
}

export interface BatteryProvenance extends BatteryProvenanceValues {
  system_id: number;
  system_code: string | null;
  /** Read-only: the system's COMMISSION lifecycle event. */
  commissioned_on: string | null;
  /** Read-only: the chemistry's end-of-life criteria. */
  soh_eol_pct: number | null;
  resistance_eol_pct: number | null;
}

export interface EolCriterion {
  chemistry: string;
  soh_eol_pct: number;
  resistance_eol_pct: number | null;
  description: string | null;
}

export interface ProvenanceOptions {
  chemistries: string[];
  batch_lots: string[];
  manufacturers: string[];
  cell_models: string[];
  cell_formats: string[];
  eol_criteria: EolCriterion[];
}
