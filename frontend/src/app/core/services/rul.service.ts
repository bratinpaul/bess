import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  RulBacktestPoint,
  RulForecastRow,
  RulModelOption,
  RulOptions,
  RulPrediction,
  RulRun,
  RulRunDetail,
  RulTrainRequest
} from '../models/rul.model';

/** The Remaining Useful Life use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class RulService {
  private readonly baseUrl = 'http://localhost:8100/rul';

  constructor(private http: HttpClient) {}

  options(): Observable<RulOptions> {
    return this.http.get<RulOptions>(`${this.baseUrl}/options`);
  }

  train(request: RulTrainRequest): Observable<RulRunDetail> {
    return this.http.post<RulRunDetail>(`${this.baseUrl}/runs`, request);
  }

  runs(): Observable<RulRun[]> {
    return this.http.get<RulRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<RulRunDetail> {
    return this.http.get<RulRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  models(): Observable<RulModelOption[]> {
    return this.http.get<RulModelOption[]>(`${this.baseUrl}/models`);
  }

  forecasts(runId: number): Observable<RulForecastRow[]> {
    return this.http.get<RulForecastRow[]>(`${this.baseUrl}/runs/${runId}/forecasts`);
  }

  backtest(runId: number, systemId: number, methods: string[]): Observable<RulBacktestPoint[]> {
    return this.http.get<RulBacktestPoint[]>(`${this.baseUrl}/runs/${runId}/backtest`, {
      params: { system_id: systemId, methods: methods.join(',') }
    });
  }

  predict(model: string, systemId: number, cyclesPerDay: number | null, tempC: number | null): Observable<RulPrediction> {
    return this.http.post<RulPrediction>(
      `${this.baseUrl}/predict`,
      { system_id: systemId, cycles_per_day: cyclesPerDay, temp_c: tempC },
      { params: { model } }
    );
  }
}
