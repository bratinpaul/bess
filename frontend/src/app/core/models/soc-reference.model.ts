/** SOC reference (battery_master.soc_reference): independent ground-truth SOC per plant battery system and moment. */

export type SocMethod = 'FULL_CHARGE' | 'FULL_DISCHARGE' | 'LAB_RPT' | 'REST_OCV';

export interface SocReferenceValues {
  soc_true_pct: number;
  method: SocMethod | null;
  note: string | null;
}

export interface SocReference extends SocReferenceValues {
  system_id: number;
  system_name: string | null;
  ts: string;
  /** Read-only: the system's telemetry at that moment and the estimators' error (reference - estimate). */
  bms_soc_pct: number | null;
  coulomb_soc_pct: number | null;
  error_vs_bms: number | null;
  error_vs_coulomb: number | null;
  mode_code: string | null;
}

export interface SocRefSystem {
  system_id: number;
  system_name: string;
  site_name: string | null;
  points: number;
  first_ts: string | null;
  last_ts: string | null;
}

export interface SocRefOptions {
  systems: SocRefSystem[];
  methods: SocMethod[];
}
