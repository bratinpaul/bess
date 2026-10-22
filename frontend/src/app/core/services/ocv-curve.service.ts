import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { OcvCurveSummary, OcvOptions, OcvPoint } from '../models/ocv-curve.model';

export interface OcvQuery {
  chemistry?: string;
  direction?: string;
  tempC?: number | null;
}

/** OCV curves (battery_master.ocv_curve): view, edit, delete points. */
@Injectable({ providedIn: 'root' })
export class OcvCurveService {
  private readonly baseUrl = 'http://localhost:8000/api/ocv-curve';

  constructor(private http: HttpClient) {}

  private params(q: OcvQuery): HttpParams {
    let p = new HttpParams();
    if (q.chemistry) {
      p = p.set('chemistry', q.chemistry);
    }
    if (q.direction) {
      p = p.set('direction', q.direction);
    }
    if (q.tempC !== null && q.tempC !== undefined) {
      p = p.set('temp_c', String(q.tempC));
    }
    return p;
  }

  options(): Observable<OcvOptions> {
    return this.http.get<OcvOptions>(`${this.baseUrl}/options`);
  }

  curves(q: OcvQuery = {}): Observable<OcvCurveSummary[]> {
    return this.http.get<OcvCurveSummary[]>(`${this.baseUrl}/curves`, { params: this.params(q) });
  }

  list(q: OcvQuery = {}): Observable<OcvPoint[]> {
    return this.http.get<OcvPoint[]>(this.baseUrl, { params: this.params(q) });
  }

  private url(p: OcvPoint): string {
    return `${this.baseUrl}/${encodeURIComponent(p.chemistry)}/${p.direction}/${p.temp_c}/${p.soc_pct}`;
  }

  update(p: OcvPoint, ocvV: number): Observable<OcvPoint> {
    return this.http.put<OcvPoint>(this.url(p), { ocv_v: ocvV });
  }

  delete(p: OcvPoint): Observable<void> {
    return this.http.delete<void>(this.url(p));
  }
}
