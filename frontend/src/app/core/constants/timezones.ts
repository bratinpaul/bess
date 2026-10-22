const FALLBACK_TIMEZONES: string[] = [
  'UTC',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Africa/Cairo',
  'Africa/Johannesburg',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Sao_Paulo',
  'Australia/Sydney',
  'Pacific/Auckland'
];

export function getAllTimezones(): string[] {
  const supportedValuesOf = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] })
    .supportedValuesOf;
  let zones = FALLBACK_TIMEZONES;
  if (typeof supportedValuesOf === 'function') {
    try {
      zones = supportedValuesOf('timeZone');
    } catch {
      zones = FALLBACK_TIMEZONES;
    }
  }

  // Some runtimes report legacy link names (e.g. "Asia/Calcutta" instead of "Asia/Kolkata"),
  // and "UTC" itself is not part of Intl.supportedValuesOf('timeZone') in most engines
  // even though it's a valid, commonly-stored value — make sure both stay selectable.
  const mustInclude = ['UTC', 'Asia/Kolkata'];
  const missing = mustInclude.filter((zone) => !zones.includes(zone));
  if (missing.length > 0) {
    zones = [...zones, ...missing].sort();
  }
  return zones;
}
