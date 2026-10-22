import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, map } from 'rxjs';

import {
  BulkDemandTelemetryResult,
  DemandTelemetry,
  DemandTelemetryCreateInput,
  DemandTelemetryInput,
  DemandTelemetryPage,
  DemandTelemetrySeries,
  MeteringPoint
} from '../models/demand-telemetry.model';

export interface DemandTelemetryQuery {
  meteringPointId?: number;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

/** Site demand readings (battery_telemetry.demand_telemetry) per metering point. */
@Injectable({ providedIn: 'root' })
export class DemandTelemetryService {
  private readonly baseUrl = 'http://localhost:8000/api/demand-telemetry';

  constructor(private http: HttpClient) {}

  list(query: DemandTelemetryQuery = {}): Observable<DemandTelemetryPage> {
    let params = new HttpParams().set('page', String(query.page ?? 1)).set('page_size', String(query.pageSize ?? 25));
    if (query.meteringPointId) {
      params = params.set('metering_point_id', String(query.meteringPointId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<DemandTelemetryPage>(this.baseUrl, { params });
  }

  lookups(): Observable<MeteringPoint[]> {
    return this.http.get<{ metering_points: MeteringPoint[] }>(`${this.baseUrl}/lookups`).pipe(map((r) => r.metering_points));
  }

  series(meteringPointId: number, start?: string, end?: string): Observable<DemandTelemetrySeries> {
    let params = new HttpParams().set('metering_point_id', String(meteringPointId));
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<DemandTelemetrySeries>(`${this.baseUrl}/series`, { params });
  }

  add(payload: DemandTelemetryCreateInput): Observable<DemandTelemetry> {
    return this.http.post<DemandTelemetry>(this.baseUrl, payload);
  }

  update(meteringPointId: number, ts: string, payload: DemandTelemetryInput): Observable<DemandTelemetry> {
    return this.http.put<DemandTelemetry>(`${this.baseUrl}/${meteringPointId}/${encodeURIComponent(ts)}`, payload);
  }

  delete(meteringPointId: number, ts: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${meteringPointId}/${encodeURIComponent(ts)}`);
  }

  /** .csv or .xlsx; without a metering_point_code column the chosen metering point is used for every row. */
  bulkUpload(file: File, meteringPointCode: string | null): Observable<BulkDemandTelemetryResult> {
    const form = new FormData();
    form.append('file', file);
    if (meteringPointCode) {
      form.append('metering_point_code', meteringPointCode);
    }
    return this.http.post<BulkDemandTelemetryResult>(`${this.baseUrl}/bulk`, form);
  }
}
