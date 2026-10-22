export type DayType = 'Weekday' | 'Weekend' | 'Holiday';

export interface CalendarDay {
  calendar_date: string;
  day_of_week: string;
  is_weekend: boolean;
  is_holiday: boolean;
  holiday_name: string | null;
  day_type: DayType;
}

/** Day of week, weekend and day type follow from the date and the holiday flag. */
export interface CalendarDayInput {
  is_holiday: boolean;
  holiday_name: string | null;
}

export interface CalendarDayCreateInput extends CalendarDayInput {
  calendar_date: string;
}

export interface CalendarDayPage {
  items: CalendarDay[];
  total: number;
  page: number;
  page_size: number;
  counts: Partial<Record<DayType, number>>;
  first_date: string | null;
  last_date: string | null;
  missing_days: number;
}

export interface BulkCalendarResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; errors: string[] }[];
  first_date: string | null;
  last_date: string | null;
  holidays: number;
}
