import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  EffCycle,
  EffCycleIn,
  EffCycleResult,
  EffDirection,
  EffModelInfo,
  EffModelOption,
  EffOptions,
  EffPointIn,
  EffPointResult,
  EffPreview,
  EffRun,
  EffRunDetail,
  EffSample,
  EffScoreRow,
  EffSelection,
  EffTrainRequest
} from '../models/efficiency.model';

/** The PCS conversion & round-trip efficiency use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class EfficiencyService {
  private readonly baseUrl = 'http://localhost:8100/efficiency';

  constructor(private http: HttpClient) {}

  options(): Observable<EffOptions> {
    return this.http.get<EffOptions>(`${this.baseUrl}/options`);
  }

  preview(selection: EffSelection): Observable<EffPreview> {
    return this.http.post<EffPreview>(`${this.baseUrl}/preview`, selection);
  }

  /** Fits the grey-box, the GAM and the residual booster, extracts the cycles; resolves with the stored run. */
  train(request: EffTrainRequest): Observable<EffRunDetail> {
    return this.http.post<EffRunDetail>(`${this.baseUrl}/runs`, request);
  }

  runs(): Observable<EffRun[]> {
    return this.http.get<EffRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<EffRunDetail> {
    return this.http.get<EffRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  cycles(runId: number): Observable<EffCycle[]> {
    return this.http.get<EffCycle[]>(`${this.baseUrl}/runs/${runId}/cycles`);
  }

  scores(): Observable<EffScoreRow[]> {
    return this.http.get<EffScoreRow[]>(`${this.baseUrl}/scores`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  // ---------------------------------------------------------------- estimator

  models(): Observable<EffModelOption[]> {
    return this.http.get<EffModelOption[]>(`${this.baseUrl}/models`);
  }

  modelInfo(model: string): Observable<EffModelInfo> {
    return this.http.get<EffModelInfo>(`${this.baseUrl}/model-info`, { params: { model } });
  }

  sample(model: string, pcsId: number, direction?: EffDirection): Observable<EffSample> {
    const params: Record<string, string | number> = { model, pcs_id: pcsId };
    if (direction) {
      params['direction'] = direction;
    }
    return this.http.get<EffSample>(`${this.baseUrl}/sample`, { params });
  }

  predict(model: string, point: EffPointIn): Observable<EffPointResult> {
    return this.http.post<EffPointResult>(`${this.baseUrl}/predict`, point, { params: { model } });
  }

  cycle(model: string, body: EffCycleIn): Observable<EffCycleResult> {
    return this.http.post<EffCycleResult>(`${this.baseUrl}/cycle`, body, { params: { model } });
  }
}
