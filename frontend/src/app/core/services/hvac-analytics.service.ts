import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { HvacDailySummary, HvacLatestReading, HvacTelemetryDateRange } from '../models/hvac-analytics.model';

@Injectable({ providedIn: 'root' })
export class HvacAnalyticsService {
  private readonly baseUrl = 'http://localhost:8000/api/hvac-analytics';

  constructor(private http: HttpClient) {}

  telemetryDateRange(hvacId: number): Observable<HvacTelemetryDateRange> {
    const params = new HttpParams().set('hvac_id', String(hvacId));
    return this.http.get<HvacTelemetryDateRange>(`${this.baseUrl}/telemetry-date-range`, { params });
  }

  dailySummary(hvacId: number, isoDate: string): Observable<HvacDailySummary> {
    const params = new HttpParams().set('hvac_id', String(hvacId)).set('date', isoDate);
    return this.http.get<HvacDailySummary>(`${this.baseUrl}/daily-summary`, { params });
  }

  dailySeries(hvacId: number, startIsoDate: string, endIsoDate: string): Observable<HvacDailySummary[]> {
    const params = new HttpParams()
      .set('hvac_id', String(hvacId))
      .set('start', startIsoDate)
      .set('end', endIsoDate);
    return this.http.get<HvacDailySummary[]>(`${this.baseUrl}/daily-series`, { params });
  }

  latest(hvacId: number): Observable<HvacLatestReading> {
    const params = new HttpParams().set('hvac_id', String(hvacId));
    return this.http.get<HvacLatestReading>(`${this.baseUrl}/latest`, { params });
  }
}
