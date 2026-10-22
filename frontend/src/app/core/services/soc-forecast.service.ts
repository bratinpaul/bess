import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  PlanBlock,
  PlanSource,
  SocBacktest,
  SocForecast,
  SocModelOption,
  SocOptions,
  SocRun,
  SocRunDetail,
  SocTrainRequest
} from '../models/soc-forecast.model';

/** The SOC trajectory forecasting use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class SocForecastService {
  private readonly baseUrl = 'http://localhost:8100/soc-forecast';

  constructor(private http: HttpClient) {}

  options(): Observable<SocOptions> {
    return this.http.get<SocOptions>(`${this.baseUrl}/options`);
  }

  train(request: SocTrainRequest): Observable<SocRunDetail> {
    return this.http.post<SocRunDetail>(`${this.baseUrl}/runs`, request);
  }

  runs(): Observable<SocRun[]> {
    return this.http.get<SocRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<SocRunDetail> {
    return this.http.get<SocRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  models(): Observable<SocModelOption[]> {
    return this.http.get<SocModelOption[]>(`${this.baseUrl}/models`);
  }

  forecast(model: string, emsId: number, source: PlanSource, blocks: PlanBlock[] = [], horizonH?: number): Observable<SocForecast> {
    return this.http.post<SocForecast>(
      `${this.baseUrl}/forecast`,
      { ems_id: emsId, source, blocks, horizon_h: horizonH ?? null, history_hours: 24 },
      { params: { model } }
    );
  }

  origins(runId: number, emsId: number): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/runs/${runId}/origins`, { params: { ems_id: emsId } });
  }

  backtest(runId: number, emsId: number, originTs: string): Observable<SocBacktest> {
    return this.http.get<SocBacktest>(`${this.baseUrl}/runs/${runId}/backtest`, { params: { ems_id: emsId, origin_ts: originTs } });
  }
}
