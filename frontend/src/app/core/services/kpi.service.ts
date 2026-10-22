import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  KpiCalculateRequest,
  KpiCalculateResult,
  KpiConfig,
  KpiData,
  KpiDateRange,
  KpiDomain,
  KpiEntity,
  KpiRun
} from '../models/kpi.model';

/** KPI API of a domain: /api/bms-kpi (system_id), /api/pcs-kpi (pcs_id) or /api/ems-kpi (ems_id). */
@Injectable({ providedIn: 'root' })
export class KpiService {
  private readonly baseUrl = 'http://localhost:8000/api';

  constructor(private http: HttpClient) {}

  private url(d: KpiDomain, path = ''): string {
    return `${this.baseUrl}/${d.apiPath}${path}`;
  }

  config(d: KpiDomain): Observable<KpiConfig> {
    return this.http.get<KpiConfig>(this.url(d, '/config'));
  }

  entities(d: KpiDomain): Observable<KpiEntity[]> {
    return this.http.get<KpiEntity[]>(this.url(d, '/entities'));
  }

  dateRange(d: KpiDomain, entityId: number): Observable<KpiDateRange> {
    return this.http.get<KpiDateRange>(this.url(d, '/date-range'), { params: { [d.idParam]: entityId } });
  }

  list(d: KpiDomain, entityId: number, start?: string, end?: string): Observable<KpiData> {
    let params = new HttpParams().set(d.idParam, entityId);
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<KpiData>(this.url(d), { params });
  }

  calculate(d: KpiDomain, req: KpiCalculateRequest): Observable<KpiCalculateResult> {
    return this.http.post<KpiCalculateResult>(this.url(d, '/calculate'), {
      [d.idParam]: req.entityId,
      start_date: req.start_date,
      end_date: req.end_date,
      dry_run: req.dry_run ?? false
    });
  }

  systemParams(d: KpiDomain, entityId: number): Observable<Record<string, number | null>> {
    return this.http.get<Record<string, number | null>>(this.url(d, '/system-params'), {
      params: { [d.idParam]: entityId }
    });
  }

  runs(d: KpiDomain, limit = 8): Observable<KpiRun[]> {
    return this.http.get<KpiRun[]>(this.url(d, '/runs'), { params: { limit } });
  }
}
