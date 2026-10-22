export interface BatteryContainer {
  container_id: number;
  battery_system_id: number;
  container_number: string | null;
  manufacturer: string | null;
  installation_date: string | null;
  status: string | null;
  container_type: string | null;
  ip_rating: string | null;
  fire_suppression: string | null;
  /** UUID in the source system (static data loader); read-only. */
  source_uuid?: string | null;
}

export type BatteryContainerInput = Omit<BatteryContainer, 'container_id'>;
