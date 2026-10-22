import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { LossDay, LossLedgerRow, LossOptions, LossRun, LossRunRequest } from '../models/loss-decomposition.model';

/** Loss decomposition / performance benchmarking use case of the ML service (/loss). */
@Injectable({ providedIn: 'root' })
export class LossDecompositionService {
  private readonly baseUrl = 'http://localhost:8100/loss';

  constructor(private http: HttpClient) {}

  options(): Observable<LossOptions> {
    return this.http.get<LossOptions>(`${this.baseUrl}/options`);
  }

  /** Computes the ledger, benchmark and scorecard (about 2-3 s per battery system); resolves with the stored run. */
  createRun(body: LossRunRequest): Observable<LossRun> {
    return this.http.post<LossRun>(`${this.baseUrl}/runs`, body);
  }

  runs(): Observable<LossRun[]> {
    return this.http.get<LossRun[]>(`${this.baseUrl}/runs`);
  }

  run(id: number): Observable<LossRun> {
    return this.http.get<LossRun>(`${this.baseUrl}/runs/${id}`);
  }

  deleteRun(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${id}`);
  }

  days(id: number, systemId: number): Observable<LossDay[]> {
    return this.http.get<LossDay[]>(`${this.baseUrl}/runs/${id}/days`, { params: { system_id: systemId } });
  }

  ledger(id: number, systemId: number, dayFrom: string, dayTo?: string): Observable<LossLedgerRow[]> {
    let params = new HttpParams().set('system_id', systemId).set('day_from', dayFrom);
    if (dayTo) {
      params = params.set('day_to', dayTo);
    }
    return this.http.get<LossLedgerRow[]>(`${this.baseUrl}/runs/${id}/ledger`, { params });
  }
}
