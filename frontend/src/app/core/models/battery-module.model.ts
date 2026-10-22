export interface BatteryModule {
  module_id: number;
  pack_id: number;
  serial_number: string | null;
  chemistry: string | null;
  nominal_voltage: number | null;
  capacity_ah: number | null;
  manufacture_date: string | null;
  installation_date: string | null;
  status: string | null;
  cell_count: number | null;
  soh_pct: number | null;
  /** UUID in the source system (static data loader); read-only. */
  source_uuid?: string | null;
}

export type BatteryModuleInput = Omit<BatteryModule, 'module_id'>;
