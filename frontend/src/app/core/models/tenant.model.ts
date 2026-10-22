export type TenantStatus = 'active' | 'suspended' | 'inactive';

export const TENANT_STATUSES: TenantStatus[] = ['active', 'suspended', 'inactive'];

/** Longer labels for the tenant_type enum values (the values themselves come from GET /api/tenants/types). */
export const TENANT_TYPE_LABELS: Record<string, string> = {
  IPP: 'IPP — Independent Power Producer',
  'C&I': 'C&I — Commercial & Industrial',
  'Aggregator / VPP': 'Aggregator / VPP — Virtual Power Plant'
};

export interface Tenant {
  tenant_id: number;
  name: string;
  legal_name: string | null;
  tenant_type: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state_province: string | null;
  postal_code: string | null;
  country: string | null;
  phone: string | null;
  email: string | null;
  status: TenantStatus;
  created_at: string;
  updated_at: string;
  /** Sites this tenant owns (tenant_site rows). */
  site_count: number;
  contact_count: number;
  primary_contact_name: string | null;
}

export type TenantInput = Omit<
  Tenant,
  'tenant_id' | 'created_at' | 'updated_at' | 'site_count' | 'contact_count' | 'primary_contact_name'
> & {
  /** On update the tenant's contacts are made to match this list; leave it out to keep them unchanged. */
  contacts?: TenantFormContact[];
};

export interface TenantContact {
  contact_id: number;
  tenant_id: number;
  contact_name: string;
  role: string | null;
  phone: string | null;
  email: string | null;
  /** At most one per tenant; the API clears the others when one is set. */
  is_primary: boolean;
  created_at: string;
  updated_at: string;
}

export type TenantContactInput = Omit<TenantContact, 'contact_id' | 'tenant_id' | 'created_at' | 'updated_at'>;

/** A contact sent with the tenant form: contact_id set = existing contact, null = new one. */
export interface TenantFormContact extends TenantContactInput {
  contact_id: number | null;
}

/** A site owned (in part) by the tenant. */
export interface TenantSiteLink {
  site_id: number;
  site_code: string;
  site_name: string;
  ownership_pct: number | null;
  is_primary_owner: boolean;
}

export interface TenantDetail extends Tenant {
  contacts: TenantContact[];
  sites: TenantSiteLink[];
}
