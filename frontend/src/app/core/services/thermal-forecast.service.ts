import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  ThermalModelOption,
  ThermalOptions,
  ThermalPrediction,
  ThermalRun,
  ThermalRunDetail,
  ThermalSeriesPoint,
  ThermalTrainRequest
} from '../models/thermal-forecast.model';

/** The temperature forecasting use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class ThermalForecastService {
  private readonly baseUrl = 'http://localhost:8100/thermal-forecast';

  constructor(private http: HttpClient) {}

  options(): Observable<ThermalOptions> {
    return this.http.get<ThermalOptions>(`${this.baseUrl}/options`);
  }

  train(request: ThermalTrainRequest): Observable<ThermalRunDetail> {
    return this.http.post<ThermalRunDetail>(`${this.baseUrl}/runs`, request);
  }

  runs(): Observable<ThermalRun[]> {
    return this.http.get<ThermalRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<ThermalRunDetail> {
    return this.http.get<ThermalRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  models(): Observable<ThermalModelOption[]> {
    return this.http.get<ThermalModelOption[]>(`${this.baseUrl}/models`);
  }

  predict(model: string, systemId: number, horizons: number[], planSource: string | null, maxAgeMin: number | null): Observable<ThermalPrediction> {
    return this.http.post<ThermalPrediction>(
      `${this.baseUrl}/predict`,
      { system_id: systemId, horizons_min: horizons, plan_source: planSource, max_data_age_min: maxAgeMin, history_hours: 6 },
      { params: { model } }
    );
  }

  series(runId: number, systemId: number, target: string, horizon: number, methods: string[]): Observable<ThermalSeriesPoint[]> {
    return this.http.get<ThermalSeriesPoint[]>(`${this.baseUrl}/runs/${runId}/series`, {
      params: { system_id: systemId, target, horizon_min: horizon, methods: methods.join(',') }
    });
  }
}
