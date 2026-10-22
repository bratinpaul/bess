import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkCalendarResult,
  CalendarDay,
  CalendarDayCreateInput,
  CalendarDayInput,
  CalendarDayPage,
  DayType
} from '../models/calendar-day.model';

export interface CalendarQuery {
  start?: string;
  end?: string;
  dayType?: DayType | '';
  holidaysOnly?: boolean;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** Reference calendar (battery_master.calendar_day). */
@Injectable({ providedIn: 'root' })
export class CalendarDayService {
  private readonly baseUrl = 'http://localhost:8000/api/calendar-days';

  constructor(private http: HttpClient) {}

  list(query: CalendarQuery = {}): Observable<CalendarDayPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 50))
      .set('order', query.order ?? 'asc');
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    if (query.dayType) {
      params = params.set('day_type', query.dayType);
    }
    if (query.holidaysOnly) {
      params = params.set('holidays_only', 'true');
    }
    return this.http.get<CalendarDayPage>(this.baseUrl, { params });
  }

  add(payload: CalendarDayCreateInput): Observable<CalendarDay> {
    return this.http.post<CalendarDay>(this.baseUrl, payload);
  }

  update(date: string, payload: CalendarDayInput): Observable<CalendarDay> {
    return this.http.put<CalendarDay>(`${this.baseUrl}/${date}`, payload);
  }

  delete(date: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${date}`);
  }

  bulkUpload(file: File): Observable<BulkCalendarResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<BulkCalendarResult>(`${this.baseUrl}/bulk`, form);
  }
}
