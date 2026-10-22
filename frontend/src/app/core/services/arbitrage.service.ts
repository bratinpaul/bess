import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ArbBulkResult, ArbLookups, ArbPage, ArbRow } from '../models/arbitrage.model';

/** Arbitrage decision tables (battery_master): one service for the six Core -> Dispatch pages. `endpoint` is the
 *  table's API path (optimization-runs, decision-states, dispatch-schedules, dispatch-outcomes, as-awards,
 *  price-scenarios); a row's key is its key fields joined as path segments. */
@Injectable({ providedIn: 'root' })
export class ArbitrageService {
  private readonly baseUrl = 'http://localhost:8000/api';

  constructor(private http: HttpClient) {}

  lookups(): Observable<ArbLookups> {
    return this.http.get<ArbLookups>(`${this.baseUrl}/arbitrage/lookups`);
  }

  list(endpoint: string, query: Record<string, string | number | null | undefined>): Observable<ArbPage> {
    let params = new HttpParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== null && v !== undefined && v !== '') {
        params = params.set(k, String(v));
      }
    }
    return this.http.get<ArbPage>(`${this.baseUrl}/${endpoint}`, { params });
  }

  add(endpoint: string, payload: ArbRow): Observable<ArbRow> {
    return this.http.post<ArbRow>(`${this.baseUrl}/${endpoint}`, payload);
  }

  update(endpoint: string, key: (string | number)[], payload: ArbRow): Observable<ArbRow> {
    return this.http.put<ArbRow>(this.keyUrl(endpoint, key), payload);
  }

  delete(endpoint: string, key: (string | number)[]): Observable<void> {
    return this.http.delete<void>(this.keyUrl(endpoint, key));
  }

  bulkUpload(endpoint: string, file: File): Observable<ArbBulkResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<ArbBulkResult>(`${this.baseUrl}/${endpoint}/bulk`, form);
  }

  /** Timestamps in a key carry a +05:30 offset; encode each segment so the '+' survives the path. */
  private keyUrl(endpoint: string, key: (string | number)[]): string {
    return `${this.baseUrl}/${endpoint}/${key.map((k) => encodeURIComponent(String(k))).join('/')}`;
  }
}
