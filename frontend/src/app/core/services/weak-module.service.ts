import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  WeakDetectRequest,
  WeakOptions,
  WeakPoint,
  WeakPreview,
  WeakRun,
  WeakRunDetail,
  WeakSeriesPoint,
  WeakWindow
} from '../models/weak-module.model';

/** The weak module use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class WeakModuleService {
  private readonly baseUrl = 'http://localhost:8100/weak-module';

  constructor(private http: HttpClient) {}

  options(): Observable<WeakOptions> {
    return this.http.get<WeakOptions>(`${this.baseUrl}/options`);
  }

  preview(window: WeakWindow): Observable<WeakPreview> {
    return this.http.post<WeakPreview>(`${this.baseUrl}/preview`, window);
  }

  /** Fits Isolation Forest and DBSCAN on the window; resolves with the stored run and its module verdicts. */
  detect(request: WeakDetectRequest): Observable<WeakRunDetail> {
    return this.http.post<WeakRunDetail>(`${this.baseUrl}/runs`, request);
  }

  /** Applies a train run's saved models to another window (a new score run). */
  score(runId: number, body: { date_from: string | null; date_to: string | null; run_name: string | null }): Observable<WeakRunDetail> {
    return this.http.post<WeakRunDetail>(`${this.baseUrl}/runs/${runId}/score`, body);
  }

  runs(systemId?: number): Observable<WeakRun[]> {
    const params = systemId ? new HttpParams().set('battery_system_id', systemId) : undefined;
    return this.http.get<WeakRun[]>(`${this.baseUrl}/runs`, { params });
  }

  run(runId: number): Observable<WeakRunDetail> {
    return this.http.get<WeakRunDetail>(`${this.baseUrl}/runs/${runId}`);
  }

  points(runId: number): Observable<WeakPoint[]> {
    return this.http.get<WeakPoint[]>(`${this.baseUrl}/runs/${runId}/points`);
  }

  series(runId: number, moduleId: number, grain: 'hour' | 'day' = 'hour'): Observable<WeakSeriesPoint[]> {
    return this.http.get<WeakSeriesPoint[]>(`${this.baseUrl}/runs/${runId}/modules/${moduleId}/series`, {
      params: { grain }
    });
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }
}
