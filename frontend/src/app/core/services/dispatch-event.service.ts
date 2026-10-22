import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, map } from 'rxjs';

import {
  BulkDispatchEventResult,
  DispatchEvent,
  DispatchEventAnalytics,
  DispatchEventFilters,
  DispatchEventInput,
  DispatchEventLookups,
  DispatchEventPage
} from '../models/dispatch-event.model';

@Injectable({ providedIn: 'root' })
export class DispatchEventService {
  private readonly baseUrl = 'http://localhost:8000/api/dispatch-events';

  constructor(private http: HttpClient) {}

  list(filters: DispatchEventFilters): Observable<DispatchEventPage> {
    return this.http.get<DispatchEventPage>(this.baseUrl, { params: this.params(filters) });
  }

  /** Aggregates for the graphical tab; same filters as list() (paging is ignored). */
  analytics(filters: DispatchEventFilters): Observable<DispatchEventAnalytics> {
    return this.http.get<DispatchEventAnalytics>(`${this.baseUrl}/analytics`, { params: this.params(filters) });
  }

  lookups(): Observable<DispatchEventLookups> {
    return this.http.get<DispatchEventLookups>(`${this.baseUrl}/lookups`);
  }

  nextId(): Observable<string> {
    return this.http.get<{ dispatch_id: string }>(`${this.baseUrl}/next-id`).pipe(map((r) => r.dispatch_id));
  }

  get(dispatchId: string): Observable<DispatchEvent> {
    return this.http.get<DispatchEvent>(`${this.baseUrl}/${encodeURIComponent(dispatchId)}`);
  }

  create(payload: DispatchEventInput): Observable<DispatchEvent> {
    return this.http.post<DispatchEvent>(this.baseUrl, payload);
  }

  update(dispatchId: string, payload: DispatchEventInput): Observable<DispatchEvent> {
    return this.http.put<DispatchEvent>(`${this.baseUrl}/${encodeURIComponent(dispatchId)}`, payload);
  }

  delete(dispatchId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${encodeURIComponent(dispatchId)}`);
  }

  /** .xlsx (its 'Dispatch Events' sheet) or .csv; existing (dispatch_id, effective_from) rows are updated. */
  bulkUpload(file: File): Observable<BulkDispatchEventResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<BulkDispatchEventResult>(`${this.baseUrl}/bulk`, form);
  }

  private params(filters: DispatchEventFilters): HttpParams {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== null && value !== undefined && value !== '') {
        params = params.set(key, String(value));
      }
    }
    return params;
  }
}
