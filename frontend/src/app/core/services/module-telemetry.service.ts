import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkModuleTelemetryResult,
  ModuleOption,
  ModuleTelemetry,
  ModuleTelemetryCreateInput,
  ModuleTelemetryPage,
  ModuleTelemetryDateRange,
  ModuleTelemetrySeries,
  ModuleTelemetrySummary
} from '../models/module-telemetry.model';

export interface ModuleTelemetryQuery {
  moduleId?: number;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

@Injectable({ providedIn: 'root' })
export class ModuleTelemetryService {
  private readonly baseUrl = 'http://localhost:8000/api/module-telemetry';

  constructor(private http: HttpClient) {}

  list(query: ModuleTelemetryQuery = {}): Observable<ModuleTelemetryPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 25));
    if (query.moduleId) {
      params = params.set('module_id', String(query.moduleId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<ModuleTelemetryPage>(this.baseUrl, { params });
  }

  series(moduleId: number, start?: string, end?: string): Observable<ModuleTelemetrySeries> {
    let params = new HttpParams().set('module_id', String(moduleId));
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<ModuleTelemetrySeries>(`${this.baseUrl}/series`, { params });
  }

  /** Optional scope for the summary endpoints: one pack and/or one battery system. */
  private scopeParams(params: HttpParams, packId?: number | null, systemId?: number | null): HttpParams {
    if (packId) {
      params = params.set('pack_id', String(packId));
    }
    if (systemId) {
      params = params.set('battery_system_id', String(systemId));
    }
    return params;
  }

  dateRange(packId?: number | null, systemId?: number | null): Observable<ModuleTelemetryDateRange> {
    const params = this.scopeParams(new HttpParams(), packId, systemId);
    return this.http.get<ModuleTelemetryDateRange>(`${this.baseUrl}/date-range`, { params });
  }

  summary(
    startDate: string,
    endDate: string,
    packId?: number | null,
    systemId?: number | null
  ): Observable<ModuleTelemetrySummary> {
    const params = this.scopeParams(
      new HttpParams().set('start_date', startDate).set('end_date', endDate),
      packId,
      systemId
    );
    return this.http.get<ModuleTelemetrySummary>(`${this.baseUrl}/summary`, { params });
  }

  modules(): Observable<ModuleOption[]> {
    return this.http.get<ModuleOption[]>(`${this.baseUrl}/modules`);
  }

  add(payload: ModuleTelemetryCreateInput): Observable<ModuleTelemetry> {
    return this.http.post<ModuleTelemetry>(this.baseUrl, payload);
  }

  bulkUpload(file: File): Observable<BulkModuleTelemetryResult> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<BulkModuleTelemetryResult>(`${this.baseUrl}/bulk`, formData);
  }
}
