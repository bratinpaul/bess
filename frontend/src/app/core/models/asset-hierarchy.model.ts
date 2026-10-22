export type AssetType =
  | 'tenant'
  | 'site'
  | 'battery_system'
  | 'battery_container'
  | 'battery_pack'
  | 'battery_module'
  | 'pcs'
  | 'ems_controller'
  | 'hvac_unit';

/** In hierarchy order (parents first). */
export const ASSET_TYPES: AssetType[] = [
  'tenant',
  'site',
  'battery_system',
  'battery_container',
  'battery_pack',
  'battery_module',
  'pcs',
  'ems_controller',
  'hvac_unit'
];

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  tenant: 'Tenant',
  site: 'Site',
  battery_system: 'Battery System',
  battery_container: 'Container',
  battery_pack: 'Pack',
  battery_module: 'Module',
  pcs: 'PCS',
  ems_controller: 'EMS',
  hvac_unit: 'HVAC'
};

/** Master-data page of each asset type's record. */
export const ASSET_RECORD_ROUTES: Record<AssetType, string> = {
  tenant: '/tenants',
  site: '/sites',
  battery_system: '/battery-systems',
  battery_container: '/battery-containers',
  battery_pack: '/battery-packs',
  battery_module: '/battery-modules',
  pcs: '/pcs',
  ems_controller: '/ems-controllers',
  hvac_unit: '/hvac-units'
};

/** Nested node from GET /api/asset-hierarchy/tree. */
export interface AssetTreeNode {
  /** The node's own UUID. */
  asset_id: string;
  asset_type: AssetType;
  /** Id of the record the node stands for (tenant_id / site_id / battery_system_id). */
  source_id: number;
  asset_name: string | null;
  external_id: string | null;
  children: AssetTreeNode[];
}

export interface AssetNode {
  asset_id: string;
  asset_type: AssetType;
  source_id: number;
  asset_name: string | null;
  external_id: string | null;
  parent_asset_id: string | null;
  created_at: string | null;
  /** Read from the parent node. */
  parent_asset_type: AssetType | null;
  parent_source_id: number | null;
  parent_name: string | null;
  child_count: number;
}

export interface AssetNodeDetail extends AssetNode {
  /** Root first. */
  ancestors: AssetNode[];
  children: AssetNode[];
}

export interface AssetSyncResult {
  created: number;
  updated: number;
}
