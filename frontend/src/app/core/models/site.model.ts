export interface Site {
  site_id: number;
  site_code: string;
  site_name: string;
  latitude: number | null;
  longitude: number | null;
  address: string | null;
  rated_power_mw: number | null;
  rated_energy_mwh: number | null;
  commission_date: string | null;
  created_at: string | null;
  timezone: string;
  grid_operator: string | null;
  state: string | null;
  grid_voltage_kv: number | null;
  /** UUID in the source system (static data loader); read-only. */
  source_uuid?: string | null;
  /** Tenants owning the site (tenant_site), primary owner first. */
  owners: SiteOwner[];
  /** Read-only, filled in by the API. */
  primary_owner_name?: string | null;
}

export interface SiteOwnerInput {
  tenant_id: number;
  /** Share of the site, 0 < pct <= 100; all owners together at most 100. */
  ownership_pct: number | null;
  is_primary_owner: boolean;
}

export interface SiteOwner extends SiteOwnerInput {
  tenant_name: string;
  tenant_status: string;
}

type SiteWritable = Omit<Site, 'site_id' | 'created_at' | 'owners' | 'primary_owner_name'>;
export type SiteCreateInput = SiteWritable & { owners: SiteOwnerInput[] };
/** `owners` omitted keeps the site's owners; a list (even empty) replaces them. */
export type SiteUpdateInput = Omit<SiteWritable, 'timezone'> & { owners?: SiteOwnerInput[] };
