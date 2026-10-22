import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { LifecycleEvent, LifecycleEventPage, LifecycleEventValues, LifecycleSystem } from '../models/lifecycle-event.model';

export interface LifecycleQuery {
  systemId?: number | null;
  eventType?: string;
  start?: string;
  end?: string;
  sort?: string;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** RUL lifecycle events (battery_master.lifecycle_event): view, edit, delete. */
@Injectable({ providedIn: 'root' })
export class LifecycleEventService {
  private readonly baseUrl = 'http://localhost:8000/api/lifecycle-events';

  constructor(private http: HttpClient) {}

  types(): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/types`);
  }

  systems(): Observable<LifecycleSystem[]> {
    return this.http.get<LifecycleSystem[]>(`${this.baseUrl}/systems`);
  }

  list(query: LifecycleQuery = {}): Observable<LifecycleEventPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 50))
      .set('sort', query.sort ?? 'event_date')
      .set('order', query.order ?? 'asc');
    if (query.systemId !== null && query.systemId !== undefined) {
      params = params.set('system_id', String(query.systemId));
    }
    if (query.eventType) {
      params = params.set('event_type', query.eventType);
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<LifecycleEventPage>(this.baseUrl, { params });
  }

  update(eventId: number, values: LifecycleEventValues): Observable<LifecycleEvent> {
    return this.http.put<LifecycleEvent>(`${this.baseUrl}/${eventId}`, values);
  }

  delete(eventId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${eventId}`);
  }
}
