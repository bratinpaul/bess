import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, map } from 'rxjs';

import {
  AlarmEvent,
  AlarmEventAnalytics,
  AlarmEventFilters,
  AlarmEventInput,
  AlarmEventLookups,
  AlarmEventPage,
  BulkAlarmEventResult
} from '../models/alarm-event.model';

@Injectable({ providedIn: 'root' })
export class AlarmEventService {
  private readonly baseUrl = 'http://localhost:8000/api/alarm-events';

  constructor(private http: HttpClient) {}

  list(filters: AlarmEventFilters): Observable<AlarmEventPage> {
    return this.http.get<AlarmEventPage>(this.baseUrl, { params: this.params(filters) });
  }

  /** Aggregates for the graphical tab; same filters as list() (paging is ignored). */
  analytics(filters: AlarmEventFilters): Observable<AlarmEventAnalytics> {
    return this.http.get<AlarmEventAnalytics>(`${this.baseUrl}/analytics`, { params: this.params(filters) });
  }

  lookups(): Observable<AlarmEventLookups> {
    return this.http.get<AlarmEventLookups>(`${this.baseUrl}/lookups`);
  }

  nextId(): Observable<string> {
    return this.http.get<{ alarm_id: string }>(`${this.baseUrl}/next-id`).pipe(map((r) => r.alarm_id));
  }

  get(alarmId: string): Observable<AlarmEvent> {
    return this.http.get<AlarmEvent>(`${this.baseUrl}/${encodeURIComponent(alarmId)}`);
  }

  create(payload: AlarmEventInput): Observable<AlarmEvent> {
    return this.http.post<AlarmEvent>(this.baseUrl, payload);
  }

  update(alarmId: string, payload: AlarmEventInput): Observable<AlarmEvent> {
    return this.http.put<AlarmEvent>(`${this.baseUrl}/${encodeURIComponent(alarmId)}`, payload);
  }

  delete(alarmId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${encodeURIComponent(alarmId)}`);
  }

  /** .xlsx (its 'Alarms' sheet) or .csv; existing (alarm_id, start time) rows are updated. */
  bulkUpload(file: File): Observable<BulkAlarmEventResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<BulkAlarmEventResult>(`${this.baseUrl}/bulk`, form);
  }

  private params(filters: AlarmEventFilters): HttpParams {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== null && value !== undefined && value !== '') {
        params = params.set(key, String(value));
      }
    }
    return params;
  }
}
