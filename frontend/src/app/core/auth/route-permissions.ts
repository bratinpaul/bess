/**
 * Which permission a page needs - the frontend mirror of the backend's rbac_map.py. Used by routeAccessGuard (typing a URL)
 * and the nav filter (hiding left-nav entries). Longest prefix wins; `/new` and `/edit` pages need the resource's `:write`.
 * Each page's API still enforces the same rule - this only keeps the UI honest.
 */
const PAGES: [string, string][] = [
  ['/dashboard', 'dashboard:read'],
  ['/plant-view', 'dashboard:read'],
  ['/tenants', 'master.tenant:read'],
  ['/sites', 'master.asset:read'],
  ['/battery-systems', 'master.asset:read'],
  ['/battery-containers', 'master.asset:read'],
  ['/battery-packs', 'master.asset:read'],
  ['/battery-modules', 'master.asset:read'],
  ['/pcs', 'master.asset:read'],
  ['/ems-controllers', 'master.asset:read'],
  ['/hvac-units', 'master.asset:read'],
  ['/asset-hierarchy', 'master.hierarchy:read'],
  ['/alarm-catalog', 'master.reference:read'],
  ['/tariff-bands', 'master.reference:read'],
  ['/calendar', 'master.reference:read'],
  ['/ocv-curve', 'master.reference:read'],
  ['/current-sensor-cal', 'master.reference:read'],
  ['/soc-reference', 'master.reference:read'],
  ['/aging-snapshots', 'master.reference:read'],
  ['/capacity-tests', 'master.reference:read'],
  ['/lifecycle-events', 'master.reference:read'],
  ['/battery-provenance', 'master.reference:read'],
  ['/dam-prices', 'market:read'],
  ['/rt-prices', 'market:read'],
  ['/as-prices', 'market:read'],
  ['/price-forecasts', 'market:read'],
  ['/dispatch', 'market:read'],
  ['/fault', 'fault:read'],
  ['/telemetry', 'telemetry:read'],
  ['/forecast-feed', 'telemetry:read'],
  ['/analytics', 'reports:read'],
  ['/batch', 'batch:read'],
  ['/admin', 'admin:read'],
  ['/admin/activity', 'audit:read'],
  // ML Model (training) pages - trainers only; Insights viewers - everyone who can read results
  ['/ml/training', 'ml.run:read'],
  ['/ml/weak-module-model', 'ml.run:read'],
  ['/ml/mv-anomaly-model', 'ml.run:read'],
  ['/ml/rul-model', 'ml.run:read'],
  ['/ml/efficiency-model', 'ml.run:read'],
  ['/ml/loss-model', 'ml.run:read'],
  ['/ml/price-forecast-model', 'ml.run:read'],
  ['/ml/soc-forecast-model', 'ml.run:read'],
  ['/ml/soc-estimation-model', 'ml.run:read'],
  ['/ml/thermal-forecast-model', 'ml.run:read'],
  ['/ml/netload-forecast-model', 'ml.run:read'],
  ['/ml/aux-forecast-model', 'ml.run:read'],
  ['/ml/heat-load-model', 'ml.run:read'],
  ['/ml/hvac-cop-model', 'ml.run:read'],
  ['/ml/arbitrage-model', 'ml.run:read'],
  ['/ml/fault-diag-model', 'ml.run:read'],
  ['/ml', 'ml.results:read']
];
const SORTED = [...PAGES].sort((a, b) => b[0].length - a[0].length);

function path(url: string): string {
  return (url.split(/[?#]/)[0] || '/').replace(/\/+$/, '') || '/';
}

/** The read permission of the page at `url` (null = any signed-in user, e.g. '/'). */
export function readPermissionFor(url: string): string | null {
  const p = path(url);
  const hit = SORTED.find(([prefix]) => p === prefix || p.startsWith(prefix + '/'));
  return hit ? hit[1] : null;
}

/** The permission needed to open `url`: the page's read permission, or its resource's `:write` for /new and /edit. */
export function permissionFor(url: string): string | null {
  const read = readPermissionFor(url);
  if (!read) {
    return null;
  }
  const p = path(url);
  return /\/(new|edit)$/.test(p) || /\/:?[^/]+\/edit$/.test(p) ? read.replace(/:read$/, ':write') : read;
}

/** Resource of the page at `url` (e.g. 'master.asset'), for in-page write / delete buttons. */
export function resourceFor(url: string): string | null {
  const read = readPermissionFor(url);
  return read ? read.replace(/:read$/, '') : null;
}
