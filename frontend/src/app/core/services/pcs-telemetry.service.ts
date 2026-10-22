import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkPcsTelemetryResult,
  PcsTelemetry,
  PcsTelemetryCreateInput,
  PcsTelemetryPage,
  PcsTelemetryLookups,
  PcsTelemetrySeries
} from '../models/pcs-telemetry.model';

export interface PcsTelemetryQuery {
  pcsId?: number;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

@Injectable({ providedIn: 'root' })
export class PcsTelemetryService {
  private readonly baseUrl = 'http://localhost:8000/api/pcs-telemetry';

  constructor(private http: HttpClient) {}

  list(query: PcsTelemetryQuery = {}): Observable<PcsTelemetryPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 25));
    if (query.pcsId) {
      params = params.set('pcs_id', String(query.pcsId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<PcsTelemetryPage>(this.baseUrl, { params });
  }

  series(pcsId: string, start?: string, end?: string): Observable<PcsTelemetrySeries> {
    let params = new HttpParams().set('pcs_id', pcsId);
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<PcsTelemetrySeries>(`${this.baseUrl}/series`, { params });
  }

  lookups(): Observable<PcsTelemetryLookups> {
    return this.http.get<PcsTelemetryLookups>(`${this.baseUrl}/lookups`);
  }

  add(payload: PcsTelemetryCreateInput): Observable<PcsTelemetry> {
    return this.http.post<PcsTelemetry>(this.baseUrl, payload);
  }

  bulkUpload(file: File): Observable<BulkPcsTelemetryResult> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<BulkPcsTelemetryResult>(`${this.baseUrl}/bulk`, formData);
  }
}
