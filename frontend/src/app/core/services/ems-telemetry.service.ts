import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkEmsTelemetryResult,
  EmsTelemetry,
  EmsTelemetryCreateInput,
  EmsTelemetryLookups,
  EmsTelemetryPage,
  EmsTelemetrySeries
} from '../models/ems-telemetry.model';

export interface EmsTelemetryQuery {
  emsId?: number;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

@Injectable({ providedIn: 'root' })
export class EmsTelemetryService {
  private readonly baseUrl = 'http://localhost:8000/api/ems-telemetry';

  constructor(private http: HttpClient) {}

  list(query: EmsTelemetryQuery = {}): Observable<EmsTelemetryPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 25));
    if (query.emsId) {
      params = params.set('ems_id', String(query.emsId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<EmsTelemetryPage>(this.baseUrl, { params });
  }

  series(emsId: number, start?: string, end?: string): Observable<EmsTelemetrySeries> {
    let params = new HttpParams().set('ems_id', String(emsId));
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<EmsTelemetrySeries>(`${this.baseUrl}/series`, { params });
  }

  lookups(): Observable<EmsTelemetryLookups> {
    return this.http.get<EmsTelemetryLookups>(`${this.baseUrl}/lookups`);
  }

  add(payload: EmsTelemetryCreateInput): Observable<EmsTelemetry> {
    return this.http.post<EmsTelemetry>(this.baseUrl, payload);
  }

  bulkUpload(file: File, emsCode: string): Observable<BulkEmsTelemetryResult> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('ems_code', emsCode);
    return this.http.post<BulkEmsTelemetryResult>(`${this.baseUrl}/bulk`, formData);
  }
}
