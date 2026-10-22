import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AuxAmbientSource,
  AuxBacktestPoint,
  AuxDailyRow,
  AuxModelOption,
  AuxOptions,
  AuxPlanSource,
  AuxPrediction,
  AuxRun,
  AuxRunDetail,
  AuxTrainRequest
} from '../models/aux-forecast.model';

export interface AuxPredictRequest {
  ems_id: number;
  horizon_hours: number;
  plan_source: AuxPlanSource;
  ambient_source: AuxAmbientSource;
  as_of: string | null;
  max_data_age_min: number | null;
}

/** The auxiliary / HVAC energy forecasting use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class AuxForecastService {
  private readonly baseUrl = 'http://localhost:8100/aux-forecast';

  constructor(private http: HttpClient) {}

  options(): Observable<AuxOptions> {
    return this.http.get<AuxOptions>(`${this.baseUrl}/options`);
  }

  train(request: AuxTrainRequest): Observable<AuxRunDetail> {
    return this.http.post<AuxRunDetail>(`${this.baseUrl}/runs`, request);
  }

  runs(): Observable<AuxRun[]> {
    return this.http.get<AuxRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<AuxRunDetail> {
    return this.http.get<AuxRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  models(): Observable<AuxModelOption[]> {
    return this.http.get<AuxModelOption[]>(`${this.baseUrl}/models`);
  }

  predict(model: string, request: AuxPredictRequest): Observable<AuxPrediction> {
    return this.http.post<AuxPrediction>(`${this.baseUrl}/predict`, { ...request, history_hours: 24 }, { params: { model } });
  }

  origins(runId: number, emsId: number): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/runs/${runId}/origins`, { params: { ems_id: emsId } });
  }

  trajectory(runId: number, emsId: number, originTs: string, methods: string[]): Observable<AuxBacktestPoint[]> {
    return this.http.get<AuxBacktestPoint[]>(`${this.baseUrl}/runs/${runId}/trajectory`, {
      params: { ems_id: emsId, origin_ts: originTs, methods: methods.join(',') }
    });
  }

  series(runId: number, emsId: number, horizon: number, methods: string[]): Observable<AuxBacktestPoint[]> {
    return this.http.get<AuxBacktestPoint[]>(`${this.baseUrl}/runs/${runId}/series`, {
      params: { ems_id: emsId, horizon_min: horizon, methods: methods.join(',') }
    });
  }

  daily(runId: number, emsId: number): Observable<AuxDailyRow[]> {
    return this.http.get<AuxDailyRow[]>(`${this.baseUrl}/runs/${runId}/daily`, { params: { ems_id: emsId } });
  }
}
