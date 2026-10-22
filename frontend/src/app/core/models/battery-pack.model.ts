export interface BatteryPack {
  pack_id: number;
  container_id: number;
  pack_number: string | null;
  nominal_voltage: number | null;
  nominal_capacity_ah: number | null;
  status: string | null;
  module_count: number | null;
  /** UUID in the source system (static data loader); read-only. */
  source_uuid?: string | null;
}

export type BatteryPackInput = Omit<BatteryPack, 'pack_id'>;
