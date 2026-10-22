import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ArbDayItem, ArbDayView, ArbOptions, ArbStudy, ArbStudyRequest } from '../models/arbitrage-optimizer.model';

/** Energy-arbitrage optimizer use case of the ML service (/arbitrage). */
@Injectable({ providedIn: 'root' })
export class ArbitrageOptimizerService {
  private readonly baseUrl = 'http://localhost:8100/arbitrage';

  constructor(private http: HttpClient) {}

  options(): Observable<ArbOptions> {
    return this.http.get<ArbOptions>(`${this.baseUrl}/options`);
  }

  /** Runs the whole backtest (seconds to about a minute); resolves with the stored study. */
  runStudy(body: ArbStudyRequest): Observable<ArbStudy> {
    return this.http.post<ArbStudy>(`${this.baseUrl}/studies`, body);
  }

  studies(): Observable<ArbStudy[]> {
    return this.http.get<ArbStudy[]>(`${this.baseUrl}/studies`);
  }

  study(id: number): Observable<ArbStudy> {
    return this.http.get<ArbStudy>(`${this.baseUrl}/studies/${id}`);
  }

  deleteStudy(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/studies/${id}`);
  }

  days(source: 'pack' | 'study', studyId?: number | null): Observable<{ system_id: number; days: ArbDayItem[] }> {
    let params = new HttpParams().set('source', source);
    if (studyId) {
      params = params.set('study_id', studyId);
    }
    return this.http.get<{ system_id: number; days: ArbDayItem[] }>(`${this.baseUrl}/days`, { params });
  }

  day(day: string, source: 'pack' | 'study', studyId?: number | null): Observable<ArbDayView> {
    let params = new HttpParams().set('day', day).set('source', source);
    if (studyId) {
      params = params.set('study_id', studyId);
    }
    return this.http.get<ArbDayView>(`${this.baseUrl}/day`, { params });
  }
}
