export interface HvacUnit {
  hvac_id: number;
  hvac_code: string;
  battery_system_id: number | null;
  /** Name of its battery system (returned by the API). */
  system_name: string | null;
  manufacturer: string | null;
  model: string | null;
  hvac_type: string | null;
  cooling_capacity_kw: number | null;
  status: string | null;
  /** UUID in the source system (static data loader); read-only. */
  source_uuid?: string | null;
}

export interface HvacUnitInput {
  hvac_code: string;
  battery_system_id: number;
  manufacturer: string | null;
  model: string | null;
  hvac_type: string | null;
  cooling_capacity_kw: number | null;
  status: string | null;
}
