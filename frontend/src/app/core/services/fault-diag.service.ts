import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  FdCandidate, FdCompare, FdEffect, FdExample, FdExampleDetail, FdFishbone, FdOptions, FdOverview, FdPareto, FdRun,
  FdScanPoint, FdScanResult, FdTrainRequest
} from '../models/fault-diag.model';

export interface FdFilter {
  date_from?: string | null;
  date_to?: string | null;
  system_id?: number | null;
}

/** Fault classification / diagnosis use case of the ML service (/fault-diag). */
@Injectable({ providedIn: 'root' })
export class FaultDiagService {
  private readonly baseUrl = 'http://localhost:8100/fault-diag';

  constructor(private http: HttpClient) {}

  private params(f: Record<string, string | number | null | undefined>): HttpParams {
    let p = new HttpParams();
    for (const [k, v] of Object.entries(f)) {
      if (v !== null && v !== undefined && v !== '') {
        p = p.set(k, v);
      }
    }
    return p;
  }

  options(): Observable<FdOptions> {
    return this.http.get<FdOptions>(`${this.baseUrl}/options`);
  }

  /** Builds the dataset, scores the engine / ML / fused models out-of-fold and refits (about 10–30 s). */
  createRun(body: FdTrainRequest): Observable<FdRun> {
    return this.http.post<FdRun>(`${this.baseUrl}/runs`, body);
  }

  runs(): Observable<FdRun[]> {
    return this.http.get<FdRun[]>(`${this.baseUrl}/runs`);
  }

  run(id: number): Observable<FdRun> {
    return this.http.get<FdRun>(`${this.baseUrl}/runs/${id}`);
  }

  deleteRun(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${id}`);
  }

  makeDefault(id: number): Observable<FdRun> {
    return this.http.post<FdRun>(`${this.baseUrl}/runs/${id}/default`, {});
  }

  publish(id: number): Observable<{ model_version: string; rows: number }> {
    return this.http.post<{ model_version: string; rows: number }>(`${this.baseUrl}/runs/${id}/publish`, {});
  }

  examples(id: number, kind?: 'episode' | 'none'): Observable<FdExample[]> {
    return this.http.get<FdExample[]>(`${this.baseUrl}/runs/${id}/examples`, { params: this.params({ kind }) });
  }

  example(id: number, key: string): Observable<FdExampleDetail> {
    return this.http.get<FdExampleDetail>(`${this.baseUrl}/runs/${id}/examples/${encodeURIComponent(key)}`);
  }

  compare(id: number, modelVersion?: string): Observable<FdCompare> {
    return this.http.get<FdCompare>(`${this.baseUrl}/runs/${id}/compare`, { params: this.params({ model_version: modelVersion }) });
  }

  scan(id: number, body: { system_id: number; date_from: string; date_to: string; step_min: number; threshold: number }): Observable<FdScanResult> {
    return this.http.post<FdScanResult>(`${this.baseUrl}/runs/${id}/scan`, body);
  }

  scans(id: number): Observable<{ system_id: number; system_name: string; date_from: string; date_to: string; windows: number }[]> {
    return this.http.get<{ system_id: number; system_name: string; date_from: string; date_to: string; windows: number }[]>(`${this.baseUrl}/runs/${id}/scans`);
  }

  scanPoints(id: number, systemId: number, from: string, to: string): Observable<FdScanPoint[]> {
    return this.http.get<FdScanPoint[]>(`${this.baseUrl}/runs/${id}/scan-points`, { params: this.params({ system_id: systemId, date_from: from, date_to: to }) });
  }

  candidates(id: number, systemId?: number | null): Observable<FdCandidate[]> {
    return this.http.get<FdCandidate[]>(`${this.baseUrl}/runs/${id}/candidates`, { params: this.params({ system_id: systemId }) });
  }

  review(candidateId: number, status: 'CONFIRMED' | 'REJECTED' | 'NEW', actual?: string | null): Observable<unknown> {
    return this.http.post(`${this.baseUrl}/candidates/${candidateId}/review`, { status, actual_fault_code: actual ?? null });
  }

  overview(f: FdFilter): Observable<FdOverview> {
    return this.http.get<FdOverview>(`${this.baseUrl}/analytics/overview`, { params: this.params({ ...f }) });
  }

  pareto(measure: string, groupBy: string, f: FdFilter, cutoff = 0.8): Observable<FdPareto> {
    return this.http.get<FdPareto>(`${this.baseUrl}/analytics/pareto`, { params: this.params({ measure, group_by: groupBy, cutoff, ...f }) });
  }

  effects(): Observable<FdEffect[]> {
    return this.http.get<FdEffect[]>(`${this.baseUrl}/analytics/effects`);
  }

  fishbone(effect: string, f: FdFilter, runId?: number | null): Observable<FdFishbone> {
    return this.http.get<FdFishbone>(`${this.baseUrl}/analytics/fishbone`, { params: this.params({ effect, run_id: runId, ...f }) });
  }
}
