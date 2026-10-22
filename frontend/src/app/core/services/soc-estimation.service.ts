import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  SocEstModelOption,
  SocEstOptions,
  SocEstPoint,
  SocEstRun,
  SocEstRunDetail,
  SocEstTrainRequest,
  SocEstimate,
  SocStepRequest,
  SocStepResult
} from '../models/soc-estimation.model';

/** The SOC estimation / correction use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class SocEstimationService {
  private readonly baseUrl = 'http://localhost:8100/soc-estimation';

  constructor(private http: HttpClient) {}

  options(): Observable<SocEstOptions> {
    return this.http.get<SocEstOptions>(`${this.baseUrl}/options`);
  }

  train(request: SocEstTrainRequest): Observable<SocEstRunDetail> {
    return this.http.post<SocEstRunDetail>(`${this.baseUrl}/runs`, request);
  }

  runs(): Observable<SocEstRun[]> {
    return this.http.get<SocEstRun[]>(`${this.baseUrl}/runs`);
  }

  run(runId: number): Observable<SocEstRunDetail> {
    return this.http.get<SocEstRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  models(): Observable<SocEstModelOption[]> {
    return this.http.get<SocEstModelOption[]>(`${this.baseUrl}/models`);
  }

  range(runId: number, systemId: number): Observable<{ from: string | null; to: string | null; test_from: string | null }> {
    return this.http.get<{ from: string | null; to: string | null; test_from: string | null }>(`${this.baseUrl}/runs/${runId}/range`, {
      params: { system_id: systemId }
    });
  }

  points(runId: number, systemId: number, from: string, to: string): Observable<SocEstPoint[]> {
    return this.http.get<SocEstPoint[]>(`${this.baseUrl}/runs/${runId}/points`, {
      params: { system_id: systemId, ts_from: from, ts_to: to }
    });
  }

  estimate(model: string, systemId: number, asOf: string | null, historyHours: number, reset = false): Observable<SocEstimate> {
    return this.http.post<SocEstimate>(
      `${this.baseUrl}/estimate`,
      { system_id: systemId, as_of: asOf, history_hours: historyHours, reset },
      { params: { model } }
    );
  }

  step(model: string, request: SocStepRequest): Observable<SocStepResult> {
    return this.http.post<SocStepResult>(`${this.baseUrl}/estimate/step`, request, { params: { model } });
  }
}
