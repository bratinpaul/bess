import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { FaultBulkResult, FaultLookups, FaultPage, FaultRow } from '../models/fault.model';

/** Fault-diagnosis tables (battery_master): one service for the six Core -> Fault pages. `endpoint` is the table's API
 *  path under /api/fault (fault-catalog, fault-signatures, fault-episodes, fault-alarm-links, maintenance-actions,
 *  fault-predictions); a row's key is its key fields joined as path segments. */
@Injectable({ providedIn: 'root' })
export class FaultService {
  private readonly baseUrl = 'http://localhost:8000/api/fault';

  constructor(private http: HttpClient) {}

  lookups(): Observable<FaultLookups> {
    return this.http.get<FaultLookups>(`${this.baseUrl}/lookups`);
  }

  list(endpoint: string, query: Record<string, string | number | boolean | null | undefined>): Observable<FaultPage> {
    let params = new HttpParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== null && v !== undefined && v !== '') {
        params = params.set(k, String(v));
      }
    }
    return this.http.get<FaultPage>(`${this.baseUrl}/${endpoint}`, { params });
  }

  add(endpoint: string, payload: FaultRow): Observable<FaultRow> {
    return this.http.post<FaultRow>(`${this.baseUrl}/${endpoint}`, payload);
  }

  update(endpoint: string, key: (string | number)[], payload: FaultRow): Observable<FaultRow> {
    return this.http.put<FaultRow>(this.keyUrl(endpoint, key), payload);
  }

  delete(endpoint: string, key: (string | number)[]): Observable<void> {
    return this.http.delete<void>(this.keyUrl(endpoint, key));
  }

  bulkUpload(endpoint: string, file: File): Observable<FaultBulkResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<FaultBulkResult>(`${this.baseUrl}/${endpoint}/bulk`, form);
  }

  private keyUrl(endpoint: string, key: (string | number)[]): string {
    return `${this.baseUrl}/${endpoint}/${key.map((k) => encodeURIComponent(String(k))).join('/')}`;
  }
}
