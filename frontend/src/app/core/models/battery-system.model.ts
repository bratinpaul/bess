export interface BatterySystem {
  battery_system_id: number;
  site_id: number;
  system_name: string;
  manufacturer: string | null;
  model: string | null;
  rated_power_mw: number | null;
  rated_energy_mwh: number | null;
  nominal_dc_voltage: number | null;
  status: string | null;
  created_at: string | null;
  chemistry_code: string;
  series_cells: number;
  parallel_cells: number;
  commissioned_on: string | null;
  bms_firmware: string | null;
}

export type BatterySystemInput = Omit<BatterySystem, 'battery_system_id' | 'created_at'>;

export interface BatteryChemistry {
  chemistry_code: string;
  description: string;
  nominal_cell_v: number;
  min_cell_v: number;
  max_cell_v: number;
}
