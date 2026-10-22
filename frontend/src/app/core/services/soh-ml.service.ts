import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  SohEstimateResponse,
  SohModelInfo,
  SohModelList,
  SohSampleReading,
  SohSystemAverage,
  SohSystemOption
} from '../models/soh-ml.model';
import {
  MlDataSelection,
  MlPreview,
  MlRun,
  MlRunDetail,
  MlTrainOptions,
  MlTrainRequest
} from '../models/ml-training.model';

@Injectable({ providedIn: 'root' })
export class SohMlService {
  /** The SOH use case of the ML service (the un-prefixed URLs remain only as aliases). */
  private readonly baseUrl = 'http://localhost:8100/soh';

  constructor(private http: HttpClient) {}

  // model: "active" (default: the default run, else the latest run) or a run id

  /** Models the estimator can use: completed runs - for a battery system, the base runs and its own runs. */
  models(systemId?: number | null): Observable<SohModelList> {
    const params: Record<string, string> = systemId === null || systemId === undefined ? {} : { system_id: String(systemId) };
    return this.http.get<SohModelList>(`${this.baseUrl}/models`, { params });
  }

  /** With model "active", systemId picks that battery system's default (else the base default). */
  modelInfo(model = 'active', systemId?: number | null): Observable<SohModelInfo> {
    const params: Record<string, string> = { model };
    if (systemId !== null && systemId !== undefined) {
      params['system_id'] = String(systemId);
    }
    return this.http.get<SohModelInfo>(`${this.baseUrl}/model-info`, { params });
  }

  /** Sites and their battery systems (for the estimator's pickers). */
  systems(): Observable<SohSystemOption[]> {
    return this.http.get<SohSystemOption[]>(`${this.baseUrl}/systems`);
  }

  /** The latest reading of a battery system as the model's inputs (its features, at its grain). */
  sample(model = 'active', systemId?: number): Observable<SohSampleReading> {
    const params: Record<string, string> = { model };
    if (systemId !== undefined) {
      params['system_id'] = String(systemId);
    }
    return this.http.get<SohSampleReading>(`${this.baseUrl}/sample`, { params });
  }

  /** A battery system's mean of the model's features over the model's training data. */
  average(systemId: number, model = 'active'): Observable<SohSystemAverage> {
    return this.http.get<SohSystemAverage>(`${this.baseUrl}/average`, {
      params: { model, system_id: String(systemId) }
    });
  }

  predict(payload: Record<string, number | null>, model = 'active'): Observable<SohEstimateResponse> {
    return this.http.post<SohEstimateResponse>(`${this.baseUrl}/predict`, payload, { params: { model } });
  }

  // ---------------------------------------------------------------- Model Training

  trainOptions(): Observable<MlTrainOptions> {
    return this.http.get<MlTrainOptions>(`${this.baseUrl}/train/options`);
  }

  preview(selection: MlDataSelection): Observable<MlPreview> {
    return this.http.post<MlPreview>(`${this.baseUrl}/train/preview`, selection);
  }

  /** Trains and scores one model; resolves with the stored run when training has finished. */
  train(request: MlTrainRequest): Observable<MlRunDetail> {
    return this.http.post<MlRunDetail>(`${this.baseUrl}/train`, request);
  }

  runs(): Observable<MlRun[]> {
    return this.http.get<MlRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<MlRunDetail> {
    return this.http.get<MlRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  /** Make a run the default of its scope (the base default, or its battery system's default). runId null removes
   *  the default of a scope: systemId's, or the base default when systemId is null. */
  activate(runId: number | null, systemId: number | null = null): Observable<unknown> {
    if (runId !== null) {
      return this.http.post(`${this.baseUrl}/runs/${runId}/activate`, {});
    }
    const params: Record<string, string> = systemId === null ? {} : { system_id: String(systemId) };
    return this.http.post(`${this.baseUrl}/runs/deactivate`, {}, { params });
  }
}
