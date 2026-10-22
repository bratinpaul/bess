import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BatchLogPage,
  BatchRunResult,
  BatchStatus,
  BatchStatusValue,
  GeneratorOptions,
  GeneratorPreview,
  GeneratorRunRequest,
  GeneratorStatus,
  SimulatorInfo,
  SimulatorRequest,
  SimulatorResult,
  HistoricalLoadRequest,
  HistoricalOptions,
  HistoricalScan,
  HistoricalStatus,
  StaticBatchStatus
} from '../models/batch.model';

const STATIC_URL = 'http://localhost:8000/api/batch/static';
const HISTORICAL_URL = 'http://localhost:8000/api/batch/historical';
const GENERATOR_URL = 'http://localhost:8000/api/batch/history-generator';

type LogFilters = { status?: BatchStatusValue | ''; q?: string; limit: number; offset: number };

function logParams(filters: LogFilters): HttpParams {
  let params = new HttpParams().set('limit', filters.limit).set('offset', filters.offset);
  if (filters.status) {
    params = params.set('status', filters.status);
  }
  if (filters.q?.trim()) {
    params = params.set('q', filters.q.trim());
  }
  return params;
}

@Injectable({ providedIn: 'root' })
export class BatchService {
  private readonly baseUrl = 'http://localhost:8000/api/batch/realtime';

  constructor(private http: HttpClient) {}

  status(): Observable<BatchStatus> {
    return this.http.get<BatchStatus>(`${this.baseUrl}/status`);
  }

  /** Runs the batch now (same as a scheduled run); resolves when it has finished. */
  run(): Observable<BatchRunResult> {
    return this.http.post<BatchRunResult>(`${this.baseUrl}/run`, {});
  }

  logs(filters: LogFilters): Observable<BatchLogPage> {
    return this.http.get<BatchLogPage>(`${this.baseUrl}/logs`, { params: logParams(filters) });
  }

  // ---------------------------------------------------------------- static master data batch

  staticStatus(): Observable<StaticBatchStatus> {
    return this.http.get<StaticBatchStatus>(`${STATIC_URL}/status`);
  }

  /** Loads every JSON file in input/static; resolves when the batch has finished. */
  runStatic(): Observable<BatchRunResult> {
    return this.http.post<BatchRunResult>(`${STATIC_URL}/run`, {});
  }

  staticLogs(filters: LogFilters): Observable<BatchLogPage> {
    return this.http.get<BatchLogPage>(`${STATIC_URL}/logs`, { params: logParams(filters) });
  }

  // ---------------------------------------------------------------- historical telemetry loader

  historicalOptions(): Observable<HistoricalOptions> {
    return this.http.get<HistoricalOptions>(`${HISTORICAL_URL}/options`);
  }

  /** Which files of the folder load as which feed, checked against the system's master data. */
  historicalScan(request: HistoricalLoadRequest): Observable<HistoricalScan> {
    return this.http.post<HistoricalScan>(`${HISTORICAL_URL}/scan`, request);
  }

  /** Starts the load in the background; follow it with historicalStatus(). */
  historicalRun(request: HistoricalLoadRequest): Observable<HistoricalStatus> {
    return this.http.post<HistoricalStatus>(`${HISTORICAL_URL}/run`, request);
  }

  historicalStatus(): Observable<HistoricalStatus> {
    return this.http.get<HistoricalStatus>(`${HISTORICAL_URL}/status`);
  }

  historicalLogs(filters: LogFilters): Observable<BatchLogPage> {
    return this.http.get<BatchLogPage>(`${HISTORICAL_URL}/logs`, { params: logParams(filters) });
  }

  // ---------------------------------------------------------------- historical file generator

  generatorOptions(): Observable<GeneratorOptions> {
    return this.http.get<GeneratorOptions>(`${GENERATOR_URL}/options`);
  }

  /** A site's mapping from master data (with the page's overrides applied) and its proposed scenario calendar. */
  generatorPreview(request: {
    battery_system_id: number;
    date_from: string;
    date_to: string;
    overrides?: Record<string, number | string>;
  }): Observable<GeneratorPreview> {
    return this.http.post<GeneratorPreview>(`${GENERATOR_URL}/preview`, request);
  }

  /** Starts generating the sites one after another in the background; follow it with generatorStatus(). */
  generatorRun(request: GeneratorRunRequest): Observable<GeneratorStatus> {
    return this.http.post<GeneratorStatus>(`${GENERATOR_URL}/run`, request);
  }

  generatorStatus(): Observable<GeneratorStatus> {
    return this.http.get<GeneratorStatus>(`${GENERATOR_URL}/status`);
  }

  generatorLogs(filters: LogFilters): Observable<BatchLogPage> {
    return this.http.get<BatchLogPage>(`${GENERATOR_URL}/logs`, { params: logParams(filters) });
  }

  // ---------------------------------------------------------------- snapshot simulator

  simulatorInfo(): Observable<SimulatorInfo> {
    return this.http.get<SimulatorInfo>('http://localhost:8000/api/batch/simulator/info');
  }

  /** Writes one snapshot file per 5 minutes into the realtime inbox. */
  simulate(request: SimulatorRequest): Observable<SimulatorResult> {
    return this.http.post<SimulatorResult>('http://localhost:8000/api/batch/simulator/run', request);
  }
}
