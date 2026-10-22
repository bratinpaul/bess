/** Time-of-use tariff bands (battery_master.ems_tariff_period). */

export type PriceLevel = 'SUPER_OFF_PEAK' | 'OFF_PEAK' | 'SHOULDER' | 'SHOULDER_HIGH' | 'PEAK';
export type DayType = 'ALL' | 'WEEKDAY' | 'WEEKEND';

export const PRICE_LEVEL_LABELS: Record<PriceLevel, string> = {
  SUPER_OFF_PEAK: 'Super off-peak',
  OFF_PEAK: 'Off-peak',
  SHOULDER: 'Shoulder',
  SHOULDER_HIGH: 'High shoulder',
  PEAK: 'Peak'
};

export const DAY_TYPE_LABELS: Record<DayType, string> = { ALL: 'Every day', WEEKDAY: 'Weekdays', WEEKEND: 'Weekends' };

export interface TariffPeriodInput {
  ems_id: number | null;
  band_code: string;
  band_name: string;
  price_level: PriceLevel;
  start_hour: number;
  end_hour: number;
  day_type: DayType;
  season: string;
  reference_price_mwh: number | null;
  valid_from: string | null;
  valid_to: string | null;
  note: string | null;
}

export interface TariffPeriod extends Omit<TariffPeriodInput, 'reference_price_mwh'> {
  tariff_period_id: number;
  reference_price_mwh: string | number | null;
  ems_code: string | null;
  site_name: string | null;
  created_at: string;
}

export interface TariffEmsOption {
  ems_id: number;
  ems_code: string;
  site_name: string | null;
}

export interface TariffPeriodLookups {
  price_levels: PriceLevel[];
  day_types: DayType[];
  seasons: string[];
  ems: TariffEmsOption[];
}
