export interface EmsController {
  ems_id: number;
  ems_code: string;
  battery_system_id: number | null;
  /** Name of its battery system (returned by the API). */
  system_name: string | null;
  manufacturer: string | null;
  model: string | null;
  firmware_version: string | null;
  control_mode: string | null;
  /** UUID in the source system (static data loader); read-only. */
  source_uuid?: string | null;
}

export interface EmsControllerInput {
  ems_code: string;
  battery_system_id: number;
  manufacturer: string | null;
  model: string | null;
  firmware_version: string | null;
  control_mode: string | null;
}
