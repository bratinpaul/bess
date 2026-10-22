import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { EmsDailySummary, EmsTelemetryDateRange } from '../models/ems-analytics.model';

@Injectable({ providedIn: 'root' })
export class EmsAnalyticsService {
  private readonly baseUrl = 'http://localhost:8000/api/ems-analytics';

  constructor(private http: HttpClient) {}

  telemetryDateRange(emsId: number): Observable<EmsTelemetryDateRange> {
    const params = new HttpParams().set('ems_id', String(emsId));
    return this.http.get<EmsTelemetryDateRange>(`${this.baseUrl}/telemetry-date-range`, { params });
  }

  dailySummary(emsId: number, isoDate: string): Observable<EmsDailySummary> {
    const params = new HttpParams().set('ems_id', String(emsId)).set('date', isoDate);
    return this.http.get<EmsDailySummary>(`${this.baseUrl}/daily-summary`, { params });
  }

  dailySeries(emsId: number, startIsoDate: string, endIsoDate: string): Observable<EmsDailySummary[]> {
    const params = new HttpParams()
      .set('ems_id', String(emsId))
      .set('start', startIsoDate)
      .set('end', endIsoDate);
    return this.http.get<EmsDailySummary[]>(`${this.baseUrl}/daily-series`, { params });
  }
}
