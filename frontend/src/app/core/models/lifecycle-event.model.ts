/** RUL lifecycle events (battery_master.lifecycle_event) of the RUL fleet systems. */

export type LifecycleEventType = 'COMMISSION' | 'AUGMENTATION' | 'MODULE_REPLACE' | 'EOL_REACHED' | 'FAILURE' | 'DECOMMISSION';

export interface LifecycleEventValues {
  event_type: LifecycleEventType;
  event_date: string;
  age_days: number | null;
  soh_at_event: number | null;
  failure_mode: string | null;
  note: string | null;
}

export interface LifecycleEvent extends LifecycleEventValues {
  event_id: number;
  system_id: number;
  system_code: string | null;
}

export interface LifecycleEventPage {
  items: LifecycleEvent[];
  total: number;
  page: number;
  page_size: number;
  counts: Record<string, number>;
}

export interface LifecycleSystem {
  system_id: number;
  system_code: string;
  events: number;
  commissioned_on: string | null;
  last_event_type: LifecycleEventType | null;
  last_event_date: string | null;
}
