export interface DashboardSummary {
  site_count: number;
  total_power_mw: number;
  total_energy_mwh: number;
}

export interface SiteMapPoint {
  site_id: number;
  site_code: string;
  site_name: string;
  latitude: number;
  longitude: number;
  rated_power_mw: number | null;
  rated_energy_mwh: number | null;
}
