import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  MvAlarm,
  MvContributors,
  MvEpisode,
  MvLiveResult,
  MvOptions,
  MvPreview,
  MvRun,
  MvSignals,
  MvTimelinePoint,
  MvTrainRequest,
  MvWindow
} from '../models/mv-anomaly.model';

/** The multivariate anomaly detection use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class MvAnomalyService {
  private readonly baseUrl = 'http://localhost:8100/mv-anomaly';

  constructor(private http: HttpClient) {}

  options(): Observable<MvOptions> {
    return this.http.get<MvOptions>(`${this.baseUrl}/options`);
  }

  preview(window: MvWindow): Observable<MvPreview> {
    return this.http.post<MvPreview>(`${this.baseUrl}/preview`, window);
  }

  train(request: MvTrainRequest): Observable<MvRun> {
    return this.http.post<MvRun>(`${this.baseUrl}/runs`, request);
  }

  runs(systemId?: number): Observable<MvRun[]> {
    const params = systemId ? new HttpParams().set('system_id', systemId) : undefined;
    return this.http.get<MvRun[]>(`${this.baseUrl}/runs`, { params });
  }

  run(runId: number): Observable<MvRun> {
    return this.http.get<MvRun>(`${this.baseUrl}/runs/${runId}`);
  }

  makeDefault(runId: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${runId}/default`, {});
  }

  deleteRun(runId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${runId}`);
  }

  /** Applies a built model to another window (a new score run). */
  score(runId: number, body: { date_from: string | null; date_to: string | null; run_name: string | null }): Observable<MvRun> {
    return this.http.post<MvRun>(`${this.baseUrl}/runs/${runId}/score`, body);
  }

  /** Scores the newest telemetry with the system's default model into its live run. */
  live(systemId: number, hours: number): Observable<MvLiveResult[]> {
    return this.http.post<MvLiveResult[]>(`${this.baseUrl}/live/score`, { system_id: systemId, hours });
  }

  timeline(runId: number, maxPoints = 2000): Observable<MvTimelinePoint[]> {
    return this.http.get<MvTimelinePoint[]>(`${this.baseUrl}/runs/${runId}/timeline`, { params: { max_points: maxPoints } });
  }

  episodes(runId: number): Observable<MvEpisode[]> {
    return this.http.get<MvEpisode[]>(`${this.baseUrl}/runs/${runId}/episodes`);
  }

  alarms(runId: number): Observable<MvAlarm[]> {
    return this.http.get<MvAlarm[]>(`${this.baseUrl}/runs/${runId}/alarms`);
  }

  contributors(runId: number): Observable<MvContributors> {
    return this.http.get<MvContributors>(`${this.baseUrl}/runs/${runId}/contributors`);
  }

  signals(runId: number, start: string, end: string, features: string[]): Observable<MvSignals> {
    return this.http.get<MvSignals>(`${this.baseUrl}/runs/${runId}/signals`, {
      params: { start, end, features: features.join(',') }
    });
  }
}
