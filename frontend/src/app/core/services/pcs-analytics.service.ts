import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { PcsDailySummary, PcsTelemetryDateRange } from '../models/pcs-analytics.model';

@Injectable({ providedIn: 'root' })
export class PcsAnalyticsService {
  private readonly baseUrl = 'http://localhost:8000/api/pcs-analytics';

  constructor(private http: HttpClient) {}

  telemetryDateRange(pcsId: number): Observable<PcsTelemetryDateRange> {
    const params = new HttpParams().set('pcs_id', String(pcsId));
    return this.http.get<PcsTelemetryDateRange>(`${this.baseUrl}/telemetry-date-range`, { params });
  }

  dailySummary(pcsId: number, isoDate: string): Observable<PcsDailySummary> {
    const params = new HttpParams().set('pcs_id', String(pcsId)).set('date', isoDate);
    return this.http.get<PcsDailySummary>(`${this.baseUrl}/daily-summary`, { params });
  }

  dailySeries(pcsId: number, startIsoDate: string, endIsoDate: string): Observable<PcsDailySummary[]> {
    const params = new HttpParams()
      .set('pcs_id', String(pcsId))
      .set('start', startIsoDate)
      .set('end', endIsoDate);
    return this.http.get<PcsDailySummary[]>(`${this.baseUrl}/daily-series`, { params });
  }
}
