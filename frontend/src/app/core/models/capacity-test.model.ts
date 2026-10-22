/** RUL capacity tests (battery_master.capacity_test): periodic RPT checkpoints of the RUL fleet systems. */

export interface CapacityTestValues {
  test_date: string;
  age_days: number | null;
  equiv_full_cycles: number | null;
  measured_capacity_kwh: number | null;
  soh_pct: number | null;
  internal_resistance_mohm: number | null;
  test_temp_c: number | null;
  method: string | null;
}

export interface CapacityTest extends CapacityTestValues {
  test_id: number;
  system_id: number;
  system_code: string | null;
}

export interface CapacityTestPage {
  items: CapacityTest[];
  total: number;
  page: number;
  page_size: number;
}

export interface CapacityTestSystem {
  system_id: number;
  system_code: string;
  tests: number;
  first_date: string | null;
  last_date: string | null;
  first_capacity_kwh: number | null;
  latest_capacity_kwh: number | null;
  latest_soh_pct: number | null;
}
