import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkTelemetryResult,
  SystemTelemetry,
  SystemTelemetryCreateInput,
  SystemTelemetryPage,
  SystemTelemetrySeries,
  TelemetryLookups
} from '../models/system-telemetry.model';

export interface TelemetryQuery {
  systemId?: number;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

@Injectable({ providedIn: 'root' })
export class SystemTelemetryService {
  private readonly baseUrl = 'http://localhost:8000/api/system-telemetry';

  constructor(private http: HttpClient) {}

  list(query: TelemetryQuery = {}): Observable<SystemTelemetryPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 25));
    if (query.systemId) {
      params = params.set('system_id', query.systemId);
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<SystemTelemetryPage>(this.baseUrl, { params });
  }

  series(systemId: number, start?: string, end?: string): Observable<SystemTelemetrySeries> {
    let params = new HttpParams().set('system_id', systemId);
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<SystemTelemetrySeries>(`${this.baseUrl}/series`, { params });
  }

  lookups(): Observable<TelemetryLookups> {
    return this.http.get<TelemetryLookups>(`${this.baseUrl}/lookups`);
  }

  add(payload: SystemTelemetryCreateInput): Observable<SystemTelemetry> {
    return this.http.post<SystemTelemetry>(this.baseUrl, payload);
  }

  bulkUpload(file: File): Observable<BulkTelemetryResult> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<BulkTelemetryResult>(`${this.baseUrl}/bulk`, formData);
  }
}
