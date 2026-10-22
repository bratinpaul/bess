import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { DailySummary, TelemetryDateRange } from '../models/analytics.model';

@Injectable({ providedIn: 'root' })
export class AnalyticsService {
  private readonly baseUrl = 'http://localhost:8000/api/analytics';

  constructor(private http: HttpClient) {}

  telemetryDateRange(systemId: number): Observable<TelemetryDateRange> {
    const params = new HttpParams().set('system_id', systemId);
    return this.http.get<TelemetryDateRange>(`${this.baseUrl}/telemetry-date-range`, { params });
  }

  dailySummary(systemId: number, isoDate: string): Observable<DailySummary> {
    const params = new HttpParams().set('system_id', systemId).set('date', isoDate);
    return this.http.get<DailySummary>(`${this.baseUrl}/daily-summary`, { params });
  }

  dailySeries(systemId: number, startIsoDate: string, endIsoDate: string): Observable<DailySummary[]> {
    const params = new HttpParams()
      .set('system_id', systemId)
      .set('start', startIsoDate)
      .set('end', endIsoDate);
    return this.http.get<DailySummary[]>(`${this.baseUrl}/daily-series`, { params });
  }
}
