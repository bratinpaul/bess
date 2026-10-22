import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkHvacTelemetryResult,
  HvacTelemetry,
  HvacTelemetryCreateInput,
  HvacTelemetryLookups,
  HvacTelemetryPage,
  HvacTelemetrySeries
} from '../models/hvac-telemetry.model';

export interface HvacTelemetryQuery {
  hvacId?: number;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

@Injectable({ providedIn: 'root' })
export class HvacTelemetryService {
  private readonly baseUrl = 'http://localhost:8000/api/hvac-telemetry';

  constructor(private http: HttpClient) {}

  list(query: HvacTelemetryQuery = {}): Observable<HvacTelemetryPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 25));
    if (query.hvacId) {
      params = params.set('hvac_id', String(query.hvacId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<HvacTelemetryPage>(this.baseUrl, { params });
  }

  series(hvacId: number, start?: string, end?: string): Observable<HvacTelemetrySeries> {
    let params = new HttpParams().set('hvac_id', String(hvacId));
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<HvacTelemetrySeries>(`${this.baseUrl}/series`, { params });
  }

  lookups(): Observable<HvacTelemetryLookups> {
    return this.http.get<HvacTelemetryLookups>(`${this.baseUrl}/lookups`);
  }

  add(payload: HvacTelemetryCreateInput): Observable<HvacTelemetry> {
    return this.http.post<HvacTelemetry>(this.baseUrl, payload);
  }

  bulkUpload(file: File, hvacCode: string): Observable<BulkHvacTelemetryResult> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('hvac_code', hvacCode);
    return this.http.post<BulkHvacTelemetryResult>(`${this.baseUrl}/bulk`, formData);
  }
}
