import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  NfBacktest,
  NfForecast,
  NfModelOption,
  NfOptions,
  NfPeak,
  NfPreviewUnit,
  NfRun,
  NfRunDetail,
  NfSelection,
  NfTrainRequest
} from '../models/netload-forecast.model';

/** The net-load & demand / peak forecasting use case of the ML service. */
@Injectable({ providedIn: 'root' })
export class NetloadForecastService {
  private readonly baseUrl = 'http://localhost:8100/netload-forecast';

  constructor(private http: HttpClient) {}

  options(): Observable<NfOptions> {
    return this.http.get<NfOptions>(`${this.baseUrl}/options`);
  }

  preview(selection: NfSelection): Observable<{ units: NfPreviewUnit[] }> {
    return this.http.post<{ units: NfPreviewUnit[] }>(`${this.baseUrl}/preview`, selection);
  }

  train(body: NfTrainRequest): Observable<NfRunDetail> {
    return this.http.post<NfRunDetail>(`${this.baseUrl}/runs`, body);
  }

  runs(): Observable<NfRun[]> {
    return this.http.get<NfRun[]>(`${this.baseUrl}/runs`);
  }

  run(id: number): Observable<NfRunDetail> {
    return this.http.get<NfRunDetail>(`${this.baseUrl}/runs/${id}`);
  }

  makeDefault(id: number): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/runs/${id}/default`, {});
  }

  deleteRun(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${id}`);
  }

  models(): Observable<NfModelOption[]> {
    return this.http.get<NfModelOption[]>(`${this.baseUrl}/models`);
  }

  origins(runId: number, mpId: number): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/runs/${runId}/origins`, { params: { mp_id: mpId } });
  }

  peaks(runId: number, mpId: number): Observable<NfPeak[]> {
    return this.http.get<NfPeak[]>(`${this.baseUrl}/runs/${runId}/peaks`, { params: { mp_id: mpId } });
  }

  backtest(runId: number, mpId: number, originTs: string): Observable<NfBacktest> {
    return this.http.get<NfBacktest>(`${this.baseUrl}/runs/${runId}/backtest`, {
      params: { mp_id: mpId, origin_ts: originTs, history_hours: 24 }
    });
  }

  forecast(mpId: number, model: string, thresholdKw: number | null, historyHours = 48): Observable<NfForecast> {
    let params = new HttpParams().set('mp_id', mpId).set('model', model).set('history_hours', historyHours);
    if (thresholdKw) {
      params = params.set('threshold_kw', thresholdKw);
    }
    return this.http.get<NfForecast>(`${this.baseUrl}/forecast`, { params });
  }
}
