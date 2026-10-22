import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { AgingSnapshot, AgingSnapshotPage, AgingSnapshotValues, AgingSystemSummary } from '../models/aging-snapshot.model';

export interface AgingQuery {
  systemId?: number | null;
  start?: string;
  end?: string;
  eol?: boolean | null;
  censored?: boolean | null;
  sort?: string;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** RUL aging snapshots (battery_master.aging_snapshot): view, edit, delete. */
@Injectable({ providedIn: 'root' })
export class AgingSnapshotService {
  private readonly baseUrl = 'http://localhost:8000/api/aging-snapshots';

  constructor(private http: HttpClient) {}

  systems(): Observable<AgingSystemSummary[]> {
    return this.http.get<AgingSystemSummary[]>(`${this.baseUrl}/systems`);
  }

  list(query: AgingQuery = {}): Observable<AgingSnapshotPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 50))
      .set('sort', query.sort ?? 'snapshot_date')
      .set('order', query.order ?? 'asc');
    if (query.systemId !== null && query.systemId !== undefined) {
      params = params.set('system_id', String(query.systemId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    if (query.eol !== null && query.eol !== undefined) {
      params = params.set('eol_reached', String(query.eol));
    }
    if (query.censored !== null && query.censored !== undefined) {
      params = params.set('is_censored', String(query.censored));
    }
    return this.http.get<AgingSnapshotPage>(this.baseUrl, { params });
  }

  update(systemId: number, snapshotDate: string, values: AgingSnapshotValues): Observable<AgingSnapshot> {
    return this.http.put<AgingSnapshot>(`${this.baseUrl}/${systemId}/${snapshotDate}`, values);
  }

  delete(systemId: number, snapshotDate: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${systemId}/${snapshotDate}`);
  }
}
