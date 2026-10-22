import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  PfBacktest,
  PfForecast,
  PfModelOption,
  PfOptions,
  PfPreview,
  PfRun,
  PfRunDetail,
  PfSelection,
  PfTrainRequest
} from '../models/price-forecast.model';

/** The electricity-price forecasting use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class PriceForecastService {
  private readonly baseUrl = 'http://localhost:8100/price-forecast';

  constructor(private http: HttpClient) {}

  options(): Observable<PfOptions> {
    return this.http.get<PfOptions>(`${this.baseUrl}/options`);
  }

  preview(selection: PfSelection): Observable<PfPreview> {
    return this.http.post<PfPreview>(`${this.baseUrl}/preview`, selection);
  }

  /** Fits every chosen model and backtests them (about 1-3 minutes); resolves with the stored run. */
  train(request: PfTrainRequest): Observable<PfRunDetail> {
    return this.http.post<PfRunDetail>(`${this.baseUrl}/runs`, request);
  }

  runs(): Observable<PfRun[]> {
    return this.http.get<PfRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<PfRunDetail> {
    return this.http.get<PfRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  models(): Observable<PfModelOption[]> {
    return this.http.get<PfModelOption[]>(`${this.baseUrl}/models`);
  }

  forecast(model: string, emsId: number, historyHours = 72): Observable<PfForecast> {
    return this.http.get<PfForecast>(`${this.baseUrl}/forecast`, { params: { model, ems_id: emsId, history_hours: historyHours } });
  }

  origins(runId: number, emsId: number): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/runs/${runId}/origins`, { params: { ems_id: emsId } });
  }

  backtest(runId: number, emsId: number, originTs: string): Observable<PfBacktest> {
    return this.http.get<PfBacktest>(`${this.baseUrl}/runs/${runId}/backtest`, { params: { ems_id: emsId, origin_ts: originTs } });
  }
}
