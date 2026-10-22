import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { HeatLedgerRow, HeatOptions, HeatPoint, HeatRun, HeatRunRequest } from '../models/heat-load.model';

/** Heat-load prediction / thermal design use case of the ML service (/heatload). */
@Injectable({ providedIn: 'root' })
export class HeatLoadService {
  private readonly baseUrl = 'http://localhost:8100/heatload';

  constructor(private http: HttpClient) {}

  options(): Observable<HeatOptions> {
    return this.http.get<HeatOptions>(`${this.baseUrl}/options`);
  }

  /** Ledger, calibration, forecast backtest and design for every system (about 3 s each); resolves with the stored run. */
  createRun(body: HeatRunRequest): Observable<HeatRun> {
    return this.http.post<HeatRun>(`${this.baseUrl}/runs`, body);
  }

  runs(): Observable<HeatRun[]> {
    return this.http.get<HeatRun[]>(`${this.baseUrl}/runs`);
  }

  run(id: number): Observable<HeatRun> {
    return this.http.get<HeatRun>(`${this.baseUrl}/runs/${id}`);
  }

  deleteRun(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${id}`);
  }

  ledger(id: number, systemId: number, dayFrom: string, dayTo?: string): Observable<HeatLedgerRow[]> {
    let params = new HttpParams().set('system_id', systemId).set('day_from', dayFrom);
    if (dayTo) {
      params = params.set('day_to', dayTo);
    }
    return this.http.get<HeatLedgerRow[]>(`${this.baseUrl}/runs/${id}/ledger`, { params });
  }

  issues(id: number, systemId: number): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/runs/${id}/issues`, { params: { system_id: systemId } });
  }

  horizon(id: number, systemId: number, horizon: number, dayFrom: string, dayTo: string): Observable<HeatPoint[]> {
    const params = new HttpParams().set('system_id', systemId).set('horizon_min', horizon).set('day_from', dayFrom).set('day_to', dayTo);
    return this.http.get<HeatPoint[]>(`${this.baseUrl}/runs/${id}/horizon`, { params });
  }

  trajectory(id: number, systemId: number, issuedAt: string): Observable<HeatPoint[]> {
    return this.http.get<HeatPoint[]>(`${this.baseUrl}/runs/${id}/trajectory`, { params: { system_id: systemId, issued_at: issuedAt } });
  }
}
