export interface Pcs {
  pcs_id: number;
  system_id: number;
  pcs_code: string;
  manufacturer: string | null;
  model: string | null;
  serial_number: string | null;
  topology: string | null;
  cooling: string | null;
  rated_power_kw: number | null;
  rated_apparent_kva: number | null;
  max_charge_kw: number | null;
  max_discharge_kw: number | null;
  rated_ac_voltage_v: number | null;
  ac_frequency_hz: number | null;
  phases: number;
  dc_voltage_min_v: number | null;
  dc_voltage_max_v: number | null;
  dc_voltage_nom_v: number | null;
  min_power_factor: number | null;
  grid_code: string | null;
  firmware: string | null;
  commissioned_on: string | null;
  created_at: string | null;
  efficiency_pct: number | null;
  grid_mode: string | null;
  /** UUID in the source system (static data loader); read-only. */
  source_uuid?: string | null;
}

export type PcsInput = Omit<Pcs, 'pcs_id' | 'created_at'>;
